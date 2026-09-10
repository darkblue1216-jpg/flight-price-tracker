"""
航空券価格 定点観測ダッシュボード
データ: Travelpayouts Data API（Aviasales実検索キャッシュの集計値）
知りたいこと: 出発何日前が一番安いか / 曜日による価格傾向
"""
import glob
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

st.set_page_config(
    page_title="航空券価格 定点観測ダッシュボード",
    page_icon="✈️",
    layout="wide",
)

COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "text": "#e6edf3",
    "grid": "#21262d",
    "line": "#58a6ff",
    "point": "#58a6ff",
    "trend": "#f85149",
    "box": "#3fb950",
}

DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DOW_LABEL_JA = {"Mon": "月", "Tue": "火", "Wed": "水", "Thu": "木", "Fri": "金", "Sat": "土", "Sun": "日"}

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "config", "routes.yaml")
HISTORY_DIR = os.path.join(BASE, "data", "price_history")


@st.cache_data(ttl=1800)
def load_route_labels():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    labels = {}
    for r in cfg.get("routes", []):
        labels[(r["origin"], r["destination"])] = r.get("label", f"{r['origin']} → {r['destination']}")
    return labels


@st.cache_data(ttl=1800)
def load_history():
    files = sorted(glob.glob(os.path.join(HISTORY_DIR, "*.csv")))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(f, dtype={"airline": str, "num_stops": "Int64"}) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["snapshot_datetime"] = pd.to_datetime(df["snapshot_datetime"], utc=True, errors="coerce")
    df["departure_date"] = pd.to_datetime(df["departure_date"], errors="coerce")
    df["price_jpy"] = pd.to_numeric(df["price_jpy"], errors="coerce")
    df["days_before_departure"] = pd.to_numeric(df["days_before_departure"], errors="coerce")
    return df


def route_key(row):
    return f"{row['origin']}-{row['destination']}"


def layout_common(fig, title, xaxis_title, yaxis_title, height=480):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=COLORS["text"])),
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        height=height,
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]),
        legend=dict(orientation="h", y=1.08),
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=70, b=40),
    )
    return fig


def timeseries_chart(df, departure_date):
    d = df[df["departure_date"] == departure_date].sort_values("snapshot_datetime")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["snapshot_datetime"], y=d["price_jpy"], mode="lines+markers",
        line=dict(color=COLORS["line"]), marker=dict(size=6), name="価格(円)",
        connectgaps=False,
    ))
    label = pd.Timestamp(departure_date).strftime("%Y-%m-%d(%a)")
    return layout_common(fig, f"出発日 {label} の価格推移（取得日時ごと）", "取得日時", "価格（円）")


def days_before_scatter(df):
    d = df.dropna(subset=["price_jpy", "days_before_departure"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["days_before_departure"], y=d["price_jpy"], mode="markers",
        marker=dict(color=COLORS["point"], size=5, opacity=0.5), name="価格(円)",
    ))
    if len(d) >= 2:
        coeffs = np.polyfit(d["days_before_departure"], d["price_jpy"], 1)
        xs = np.linspace(d["days_before_departure"].min(), d["days_before_departure"].max(), 50)
        ys = np.polyval(coeffs, xs)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", line=dict(color=COLORS["trend"], width=2), name="線形トレンド",
        ))
    fig.update_xaxes(autorange="reversed")
    return layout_common(fig, "出発何日前が安いか（残り日数 × 価格）", "出発までの残り日数（右=直前）", "価格（円）")


def day_of_week_box(df):
    d = df.dropna(subset=["price_jpy", "day_of_week"]).copy()
    d["day_of_week"] = pd.Categorical(d["day_of_week"], categories=DOW_ORDER, ordered=True)
    d = d.sort_values("day_of_week")
    fig = go.Figure()
    for dow in DOW_ORDER:
        vals = d.loc[d["day_of_week"] == dow, "price_jpy"]
        if vals.empty:
            continue
        fig.add_trace(go.Box(y=vals, name=DOW_LABEL_JA[dow], marker_color=COLORS["box"]))
    return layout_common(fig, "曜日別の価格分布（出発日の曜日）", "出発日の曜日", "価格（円）")


def main():
    st.title("✈️ 航空券価格 定点観測ダッシュボード")
    st.caption("Travelpayouts Data API（Aviasales実検索キャッシュ集計値）に基づく相場・トレンド観測ツール。通知機能なし。")

    df = load_history()
    if df.empty:
        st.warning("data/price_history/ にスナップショットCSVがまだありません。fetch_prices.py を実行してください。")
        return

    labels = load_route_labels()
    df["route"] = list(zip(df["origin"], df["destination"]))
    df["route_display"] = df["route"].map(lambda k: labels.get(k, f"{k[0]} → {k[1]}"))

    st.sidebar.header("フィルタ")
    route_options = sorted(df["route_display"].dropna().unique())
    selected_route = st.sidebar.selectbox("路線", route_options)
    d_route = df[df["route_display"] == selected_route]

    total = len(d_route)
    missing = d_route["price_jpy"].isna().sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("記録行数", f"{total:,}")
    c2.metric("価格欠測数", f"{missing:,}")
    c3.metric("欠測率（検索母数不足の目安）", f"{missing / total:.1%}" if total else "-")

    st.subheader("① 路線別：残り日数 × 価格（何日前が安いか）")
    st.plotly_chart(days_before_scatter(d_route), use_container_width=True)

    st.subheader("② 路線別：出発日ごとの価格推移（取得日時 × 価格）")
    dep_dates = sorted(d_route["departure_date"].dropna().unique())
    if dep_dates:
        dep_choice = st.selectbox(
            "出発日を選択",
            dep_dates,
            format_func=lambda x: pd.Timestamp(x).strftime("%Y-%m-%d(%a)"),
        )
        st.plotly_chart(timeseries_chart(d_route, dep_choice), use_container_width=True)
    else:
        st.info("この路線にはまだ出発日データがありません。")

    st.subheader("③ 曜日別の価格分布")
    st.plotly_chart(day_of_week_box(d_route), use_container_width=True)


if __name__ == "__main__":
    main()
