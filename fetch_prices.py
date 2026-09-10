"""
Travelpayouts Data API (/v1/prices/calendar) から config/routes.yaml に登録した
各路線の将来出発日の価格を取得し、日次スナップショットCSVに保存する。

データソース: Travelpayouts Data API
  https://support.travelpayouts.com/hc/en-us/articles/203956163
  無料登録 + Aviasalesアフィリエイトプログラム連携で取得したトークンが必要（環境変数
  TRAVELPAYOUTS_TOKEN）。Aviasales実検索キャッシュに基づく集計値であり、リアルタイムの
  見積もりではなく相場・トレンド把握用のデータである点に注意。

取得方法:
  calendar APIは「出発月（YYYY-MM）」を指定するとその月の日別最安値を一括で返す。
  lookahead_days（既定180日）をカバーする月数分だけ呼び出し、各路線ごとに
  「今日〜今日+lookahead_days」の全日付についてレコードを作る。calendarに該当日の
  データが無い場合も、価格nullの行としてそのまま記録する（検索母数不足の分析に使うため）。

保存先: data/price_history/{YYYY-MM-DD}.csv （取得日ごとのスナップショット、
  後続のダッシュボードが積み上げて時系列・残り日数分析に使う）
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "config", "routes.yaml")
HISTORY_DIR = os.path.join(BASE, "data", "price_history")

CALENDAR_URL = "https://api.travelpayouts.com/v1/prices/calendar"
FX_URL = "https://api.frankfurter.app/latest"

TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
UA = "flight-price-tracker/1.0"
JST = dt.timezone(dt.timedelta(hours=9))

FIELDNAMES = [
    "snapshot_datetime", "origin", "destination", "departure_date",
    "price_jpy", "days_before_departure", "day_of_week", "airline", "num_stops",
]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_json(url, params, timeout=20):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_usdjpy_rate():
    try:
        data = fetch_json(FX_URL, {"from": "USD", "to": "JPY"})
        return float(data["rates"]["JPY"])
    except Exception as e:
        print(f"[WARN] USD/JPY為替レート取得失敗: {e}", file=sys.stderr)
        return None


def months_to_query(today, lookahead_days, max_months_ahead):
    end = today + dt.timedelta(days=lookahead_days)
    months = []
    cur = dt.date(today.year, today.month, 1)
    count = 0
    while cur <= end and count < max_months_ahead:
        months.append(cur.strftime("%Y-%m"))
        cur = dt.date(cur.year + 1, 1, 1) if cur.month == 12 else dt.date(cur.year, cur.month + 1, 1)
        count += 1
    return months


def fetch_calendar_month(origin, destination, depart_month, currency):
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": depart_month,
        "currency": currency,
        "token": TOKEN,
    }
    try:
        data = fetch_json(CALENDAR_URL, params)
    except urllib.error.HTTPError as e:
        print(f"[WARN] calendar HTTPエラー {origin}->{destination} {depart_month}: {e}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[WARN] calendar取得エラー {origin}->{destination} {depart_month}: {e}", file=sys.stderr)
        return {}
    if not data.get("success"):
        print(f"[WARN] calendar取得失敗 {origin}->{destination} {depart_month}: {data}", file=sys.stderr)
        return {}
    return data.get("data", {}) or {}


def to_jpy(price, currency, usdjpy_rate):
    if price is None:
        return None
    if currency == "jpy":
        return round(price)
    if currency == "usd" and usdjpy_rate:
        return round(price * usdjpy_rate)
    return None


def main():
    if not TOKEN:
        print("[ERROR] 環境変数 TRAVELPAYOUTS_TOKEN が未設定です", file=sys.stderr)
        sys.exit(1)

    cfg = load_config()
    routes = cfg.get("routes", [])
    settings = cfg.get("settings", {})
    currency = settings.get("currency", "usd")
    lookahead_days = settings.get("lookahead_days", 180)
    max_months_ahead = settings.get("max_months_ahead", 7)

    usdjpy_rate = get_usdjpy_rate() if currency != "jpy" else None
    if currency == "usd" and usdjpy_rate is None:
        print("[WARN] 為替レート取得失敗のため price_jpy は null で記録します", file=sys.stderr)

    now_jst = dt.datetime.now(JST)
    today = now_jst.date()
    months = months_to_query(today, lookahead_days, max_months_ahead)

    rows = []
    for route in routes:
        origin, destination = route["origin"], route["destination"]

        calendar_data = {}
        for month in months:
            calendar_data.update(fetch_calendar_month(origin, destination, month, currency))
            time.sleep(1)  # レート制限への配慮

        for offset in range(lookahead_days + 1):
            dep_date = today + dt.timedelta(days=offset)
            date_str = dep_date.isoformat()
            info = calendar_data.get(date_str)
            info = info if isinstance(info, dict) else None

            price = info.get("price") if info else None
            price_jpy = to_jpy(price, currency, usdjpy_rate)

            rows.append({
                "snapshot_datetime": now_jst.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "origin": origin,
                "destination": destination,
                "departure_date": date_str,
                "price_jpy": price_jpy if price_jpy is not None else "",
                "days_before_departure": offset,
                "day_of_week": dep_date.strftime("%a"),
                "airline": (info.get("airline") or "") if info else "",
                "num_stops": (info.get("transfers", "") if info else ""),
            })

    os.makedirs(HISTORY_DIR, exist_ok=True)
    out_path = os.path.join(HISTORY_DIR, f"{today.isoformat()}.csv")
    file_exists = os.path.exists(out_path)
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"{len(rows)}行を保存: {out_path}")


if __name__ == "__main__":
    main()
