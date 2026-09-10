"""
路線候補の価格データ有無を素早く確認するための単発診断ツール。

fetch_prices.py の本番パイプライン（config/routes.yaml, data/price_history/ への書き込み）には
一切影響しない。特定の出発地・到着地の組み合わせで、Travelpayouts calendar APIに
どれくらい価格キャッシュがあるかを確認したいときに使う（例: 新しい路線を追加する前の下調べ）。

使い方: python diagnostic_test.py --origin HND --destinations MXP,CAI,DEL,HEL,PVG,DAD
"""
import argparse
import datetime as dt

from fetch_prices import TOKEN, fetch_calendar_month, months_to_query


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destinations", required=True, help="カンマ区切りのIATAコード")
    parser.add_argument("--currency", default="usd")
    parser.add_argument("--lookahead-days", type=int, default=180)
    parser.add_argument("--max-months-ahead", type=int, default=7)
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("環境変数 TRAVELPAYOUTS_TOKEN が未設定です")

    today = dt.date.today()
    months = months_to_query(today, args.lookahead_days, args.max_months_ahead)
    destinations = [d.strip() for d in args.destinations.split(",") if d.strip()]
    total_days = args.lookahead_days + 1

    for dest in destinations:
        calendar_data = {}
        for month in months:
            calendar_data.update(fetch_calendar_month(args.origin, dest, month, args.currency))

        priced_dates = [
            date_str for date_str, info in calendar_data.items()
            if isinstance(info, dict) and info.get("price") is not None
        ]
        sample = calendar_data.get(priced_dates[0]) if priced_dates else None

        print(f"{args.origin}->{dest}: {len(priced_dates)}/{total_days}日 に価格あり "
              f"({len(priced_dates) / total_days:.0%})  sample={sample}")


if __name__ == "__main__":
    main()
