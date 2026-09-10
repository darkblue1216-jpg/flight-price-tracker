# flight-price-tracker

航空券価格の定点観測・時系列可視化ツール（通知機能なし）。

## 知りたいこと
- 出発何日前が一番安いか
- 曜日による価格傾向

## データソース
[Travelpayouts Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163) の
`/v1/prices/calendar`（出発月を指定するとその月の日別最安値を一括取得できるエンドポイント）を使用。
Aviasales実検索キャッシュに基づく集計値であり、**リアルタイムの見積もりではなく相場・トレンド用途**。

無料登録＋Aviasalesアフィリエイトプログラム連携でトークンを取得し、環境変数 `TRAVELPAYOUTS_TOKEN` に設定する。

## 構成
- `config/routes.yaml` — 追跡する路線を手動で追記する設定ファイル（3〜5路線を想定）
- `fetch_prices.py` — GitHub Actionsから毎日実行し、`data/price_history/{YYYY-MM-DD}.csv` に
  スナップショットを1ファイルずつ追記する取得スクリプト
- `.github/workflows/fetch_prices.yml` — 毎日1回（06:00 JST）の定期実行ワークフロー
- `app.py` — Streamlitダッシュボード（時系列推移／残り日数×価格の散布図・回帰／曜日別箱ひげ図）

`nk225-oi-dashboard` / `neco-stock-screen` と同じ「GitHub Actions定期実行＋日次スナップショットCSV蓄積」パターン。

## 記録する変数
`snapshot_datetime`（JST）, `origin`, `destination`, `departure_date`, `price_jpy`（JPY正規化済み）,
`days_before_departure`, `day_of_week`, `airline`（取得できれば）, `num_stops`（取得できれば）。

データ欠測時（calendarに該当日のデータが無い場合）は価格nullの行としてそのまま記録する
（検索母数不足の分析にも使えるようにするため）。

`price_jpy` は `settings.currency`（既定 usd）で取得した価格を、取得時点の
[frankfurter.app](https://www.frankfurter.app/) のUSD/JPYレートで換算したもの。
Travelpayouts API自体がjpyを直接サポートしない前提での設計。

`num_stops` は `/v1/prices/calendar` のレスポンスに乗数（`transfers`）が含まれる場合のみ埋まる。
通常のcalendarレスポンスには含まれないことが多く、その場合は空欄になる。

## セットアップ
1. Travelpayoutsでトークンを取得
2. GitHubリポジトリのSecretsに `TRAVELPAYOUTS_TOKEN` を登録
3. `config/routes.yaml` に路線を追記
4. GitHub Actionsが毎日 `data/price_history/` にスナップショットを蓄積

### ローカルでの動作確認
```bash
pip install -r requirements.txt
export TRAVELPAYOUTS_TOKEN=xxxx
python fetch_prices.py
streamlit run app.py
```

## 未検証の注意点
このツールはTravelpayouts APIの有効なトークンでは未検証（このセッションではトークンを保有していない）。
公開ドキュメント通りのレスポンス形式を前提にしているが、初回実行時にAPIレスポンス構造が
想定と異なる場合は `fetch_prices.py` の `fetch_calendar_month` / パース部分を調整すること。
