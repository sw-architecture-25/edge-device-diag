# streamlit_dashboard.py
# ------------------------------------------------------------
# Edge Device Diagnosis - Streamlit Dashboard
#  - Auto refresh
#  - Trend chart (T1, mu, thresholds) + prediction windows (alert CSV)
#  - Alerts table
#  - Threshold control (manual numeric / dynamic mode)
#
# Usage:
#   streamlit run streamlit_dashboard.py
# ------------------------------------------------------------
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


@dataclass
class ApiResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    status_code: Optional[int] = None


def _api_get(base_url: str, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> ApiResult:
    url = base_url.rstrip("/") + path
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        if r.ok:
            return ApiResult(True, r.json(), None, r.status_code)
        return ApiResult(False, None, f"{r.status_code} {r.text}", r.status_code)
    except Exception as e:
        return ApiResult(False, None, str(e), None)


def _api_put_json(base_url: str, path: str, payload: Dict[str, Any], timeout: float = 4.0) -> ApiResult:
    url = base_url.rstrip("/") + path
    try:
        r = requests.put(url, json=payload, timeout=timeout)
        if r.ok:
            return ApiResult(True, r.json(), None, r.status_code)
        return ApiResult(False, None, f"{r.status_code} {r.text}", r.status_code)
    except Exception as e:
        return ApiResult(False, None, str(e), None)


def _inject_autorefresh(interval_ms: int) -> None:
    """No-dependency auto refresh using a tiny JS snippet."""
    if interval_ms <= 0:
        return
    components.html(
        f"""
        <script>
          setTimeout(function() {{
            window.location.reload();
          }}, {interval_ms});
        </script>
        """,
        height=0,
    )


def _to_df_trend(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows or [])
    if df.empty:
        return df
    for col in ["ts", "timestamp"]:
        if col in df.columns:
            df["ts_dt"] = pd.to_datetime(df[col], errors="coerce")
            break
    if "ts_dt" not in df.columns:
        df["ts_dt"] = pd.NaT
    df = df.sort_values(["ts_dt"], ascending=True, na_position="last").reset_index(drop=True)
    return df


def _to_df_alerts(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows or [])
    if df.empty:
        return df
    if "created_at" in df.columns:
        df["created_at_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
    if "timestamp" in df.columns:
        df["ts_dt"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


def _pick_last(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {}
    return df.iloc[-1].to_dict()


def _read_alert_csv(csv_path: str) -> pd.DataFrame:
    """Read temperature_with_alerts.csv (or compatible).
    Expected:
      - date/time column: 'date' or 'timestamp' (fallback: first column)
      - alert column: 'alert' (1 means warning start day)
    """
    if not csv_path:
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return df

    time_col = None
    for c in ["date", "timestamp", "ts"]:
        if c in df.columns:
            time_col = c
            break
    if time_col is None:
        time_col = df.columns[0]

    df["ts_dt"] = pd.to_datetime(df[time_col], errors="coerce")
    if "alert" in df.columns:
        df["alert"] = pd.to_numeric(df["alert"], errors="coerce").fillna(0).astype(int)
    else:
        df["alert"] = 0

    df = df.dropna(subset=["ts_dt"]).sort_values("ts_dt").reset_index(drop=True)
    return df


def _merge_intervals(starts: List[pd.Timestamp], horizon_days: int) -> pd.DataFrame:
    """Create [start, end] intervals from start dates, then merge overlaps/adjacent."""
    if not starts:
        return pd.DataFrame(columns=["start", "end"])
    raw = []
    for t0 in starts:
        raw.append((pd.to_datetime(t0).normalize(), (pd.to_datetime(t0) + pd.Timedelta(days=horizon_days)).normalize()))
    raw.sort(key=lambda x: x[0])

    merged = []
    cur_s, cur_e = raw[0]
    for s, e in raw[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return pd.DataFrame(merged, columns=["start", "end"])


# ---------------- UI ----------------
st.set_page_config(page_title="Edge Device Dashboard", layout="wide")
st.title("🛠️ Edge Motor Temperature Dashboard")

with st.sidebar:
    st.header("Connection")
    base_url = st.text_input("API Base URL", value="http://localhost:8000")
    st.caption("FastAPI 서버 주소. 예: http://localhost:8000")

    st.header("Auto refresh")
    refresh_sec = st.slider("Refresh interval (sec)", min_value=0, max_value=30, value=3, step=1)
    _inject_autorefresh(refresh_sec * 1000)

    st.header("View options")
    trend_limit = st.slider("Trend points", min_value=50, max_value=2000, value=300, step=50)
    alert_limit = st.slider("Alerts", min_value=10, max_value=300, value=50, step=10)

    st.header("Prediction windows (CSV)")
    csv_path = st.text_input(
        "temperature_with_alerts.csv path",
        value=r"..\ml\assets_cnn_lstm_keyday_eval_final\temperature_with_alerts.csv",
        help="alert=1인 날짜부터 horizon_days 기간을 차트 배경 음영으로 표시함",
    )
    horizon_days = st.slider("Horizon days", 1, 60, 10, 1)
    show_windows = st.checkbox("Show prediction windows", value=True)
    show_window_table = st.checkbox("Show windows table", value=False)

# ---- Fetch data ----
status_res = _api_get(base_url, "/status")
trend_res = _api_get(base_url, "/trend", params={"limit": trend_limit})
thr_res = _api_get(base_url, "/thresholds")
notify_res = _api_get(base_url, "/notify", params={"limit": alert_limit})

# ---- Top KPI ----
kpi_cols = st.columns(4)
trend_df = _to_df_trend(trend_res.data if trend_res.ok else [])
last = _pick_last(trend_df)

current_t1 = last.get("t1")
mu = last.get("mu")
delta_t = last.get("delta_t")
dyn_thr = last.get("dynamic_threshold")
final_thr = last.get("final_threshold")
is_anom = last.get("is_anomaly")

thr_source = "unknown"
try:
    if dyn_thr is not None and final_thr is not None:
        thr_source = "manual" if abs(float(dyn_thr) - float(final_thr)) > 1e-6 else "dynamic"
except Exception:
    thr_source = "unknown"

kpi_cols[0].metric("Current T1", f"{current_t1:.2f}" if isinstance(current_t1, (int, float)) else "-")
kpi_cols[1].metric("Moving Avg (μ)", f"{mu:.2f}" if isinstance(mu, (int, float)) else "-", delta=f"{delta_t:+.2f}" if isinstance(delta_t, (int, float)) else None)
kpi_cols[2].metric("Final Threshold", f"{final_thr:.2f}" if isinstance(final_thr, (int, float)) else "-", delta=f"source={thr_source}")
kpi_cols[3].metric("Anomaly", "YES" if is_anom else "NO")

st.divider()

# ---- Threshold control ----
st.subheader("🎚️ Threshold Control")

thr_rows = thr_res.data if thr_res.ok else []
thr_df = pd.DataFrame(thr_rows)
if thr_df.empty:
    st.warning("Thresholds not available. Check API connection.")
else:
    if "manual_threshold" in thr_df.columns:
        def _norm(v):
            try:
                if v is None:
                    return None
                if float(v) <= 0:
                    return None
            except Exception:
                pass
            return v
        thr_df["manual_threshold_norm"] = thr_df["manual_threshold"].map(_norm)

    motor_ids = thr_df["motor_id"].tolist() if "motor_id" in thr_df.columns else []
    sel_motor = st.selectbox("motor_id", motor_ids, index=0 if motor_ids else None)

    row = thr_df[thr_df["motor_id"] == sel_motor].iloc[0].to_dict() if motor_ids else {}
    manual_now = row.get("manual_threshold_norm", row.get("manual_threshold"))
    updated_at = row.get("updated_at")

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        st.write("**Current mode**")
        st.code("dynamic" if manual_now in (None, "", "null") else f"manual ({manual_now})")
        if updated_at:
            st.caption(f"updated_at: {updated_at}")

    with c2:
        new_manual = st.number_input("Set manual threshold", min_value=0.0, value=float(manual_now) if isinstance(manual_now, (int, float)) else 0.0, step=0.5)
        apply_manual = st.button("Apply manual", use_container_width=True)

    with c3:
        st.write("**Switch to dynamic**")
        st.caption('Sends PUT value="dynamic" (if server supports), otherwise shows error.')
        apply_dynamic = st.button("Apply dynamic", use_container_width=True)

    if apply_manual:
        payload = {"motor_id": sel_motor, "value": float(new_manual)}
        r = _api_put_json(base_url, "/thresholds", payload)
        if r.ok:
            st.success(f"Applied manual threshold: {sel_motor} = {new_manual:.2f}")
        else:
            st.error(f"Failed: {r.error}")

    if apply_dynamic:
        payload = {"motor_id": sel_motor, "value": "dynamic"}
        r = _api_put_json(base_url, "/thresholds", payload)
        if r.ok:
            st.success(f"Switched to dynamic: {sel_motor}")
        else:
            st.error(
                "Dynamic mode failed.\n\n"
                "If you're on v2 (no dynamic mode), apply the v2_dynamic_fix patch or add support to PUT /thresholds.\n\n"
                f"Error: {r.error}"
            )

st.divider()

# ---- Trend chart ----
st.subheader("📈 Trend (with prediction windows)")

if not trend_res.ok:
    st.error(f"/trend error: {trend_res.error}")
elif trend_df.empty:
    st.info("No trend data yet.")
else:
    if "motor_id" in trend_df.columns:
        mids = sorted(trend_df["motor_id"].dropna().unique().tolist())
        mid_sel = st.selectbox("Trend motor_id", mids, index=0)
        df_plot = trend_df[trend_df["motor_id"] == mid_sel].copy()
    else:
        df_plot = trend_df.copy()

    df_plot = df_plot.dropna(subset=["ts_dt"]).sort_values("ts_dt", ascending=True).reset_index(drop=True)
    if df_plot.empty:
        st.info("No valid timestamps in trend.")
    else:
        win_df = pd.DataFrame(columns=["start", "end"])
        csv_df = _read_alert_csv(csv_path)
        if not csv_df.empty and "alert" in csv_df.columns:
            starts = csv_df.loc[csv_df["alert"] == 1, "ts_dt"].tolist()
            win_df = _merge_intervals(starts, horizon_days)

        x_min = df_plot["ts_dt"].min()
        x_max = df_plot["ts_dt"].max()
        if not win_df.empty:
            win_df = win_df.copy()
            win_df["start"] = pd.to_datetime(win_df["start"], errors="coerce")
            win_df["end"] = pd.to_datetime(win_df["end"], errors="coerce")
            win_df = win_df.dropna(subset=["start", "end"])
            win_df["start"] = win_df["start"].clip(lower=x_min, upper=x_max)
            win_df["end"] = win_df["end"].clip(lower=x_min, upper=x_max)
            win_df = win_df[win_df["end"] > win_df["start"]]

        if show_window_table and not win_df.empty:
            with st.expander("Prediction windows (merged)"):
                st.dataframe(win_df, use_container_width=True)

        series_cols = [c for c in ["t1", "mu", "dynamic_threshold", "final_threshold"] if c in df_plot.columns]
        if not series_cols:
            st.dataframe(df_plot)
        else:
            plot_long = df_plot.melt(id_vars=["ts_dt"], value_vars=series_cols, var_name="series", value_name="value").dropna(subset=["value"])

            layers = []
            if show_windows and not win_df.empty:
                rect = alt.Chart(win_df).mark_rect(opacity=0.12).encode(
                    x="start:T",
                    x2="end:T",
                    tooltip=[alt.Tooltip("start:T", title="warning_start"), alt.Tooltip("end:T", title="warning_end")],
                )
                layers.append(rect)

            lines = alt.Chart(plot_long).mark_line().encode(
                x=alt.X("ts_dt:T", title="Time"),
                y=alt.Y("value:Q", title="Value"),
                color=alt.Color("series:N", title="Series"),
                tooltip=[alt.Tooltip("ts_dt:T", title="time"), alt.Tooltip("series:N", title="series"), alt.Tooltip("value:Q", title="value", format=".2f")],
            )
            layers.append(lines)

            chart = alt.layer(*layers).properties(height=420).interactive()
            st.altair_chart(chart, use_container_width=True)

st.divider()

# ---- Alerts ----
st.subheader("🚨 Alerts (/notify)")
if not notify_res.ok:
    st.error(f"/notify error: {notify_res.error}")
else:
    alerts_df = _to_df_alerts(notify_res.data if notify_res.ok else [])
    if alerts_df.empty:
        st.info("No alerts yet.")
    else:
        fcols = st.columns([2, 2, 2, 2])
        severity_vals = sorted(alerts_df["severity"].dropna().unique().tolist()) if "severity" in alerts_df.columns else []
        motor_vals = sorted(alerts_df["motor_id"].dropna().unique().tolist()) if "motor_id" in alerts_df.columns else []

        sev_sel = fcols[0].multiselect("Severity", severity_vals, default=severity_vals)
        mot_sel = fcols[1].multiselect("motor_id", motor_vals, default=motor_vals)
        src_vals = sorted(alerts_df["threshold_source"].dropna().unique().tolist()) if "threshold_source" in alerts_df.columns else []
        src_sel = fcols[2].multiselect("threshold_source", src_vals, default=src_vals) if src_vals else []
        txt = fcols[3].text_input("Search message contains", value="")

        df_f = alerts_df.copy()
        if sev_sel and "severity" in df_f.columns:
            df_f = df_f[df_f["severity"].isin(sev_sel)]
        if mot_sel and "motor_id" in df_f.columns:
            df_f = df_f[df_f["motor_id"].isin(mot_sel)]
        if src_sel and "threshold_source" in df_f.columns:
            df_f = df_f[df_f["threshold_source"].isin(src_sel)]
        if txt.strip() and "message" in df_f.columns:
            df_f = df_f[df_f["message"].astype(str).str.contains(txt.strip(), case=False, na=False)]

        show_cols = [c for c in ["id", "created_at", "timestamp", "motor_id", "severity", "threshold_source", "dynamic_threshold", "final_threshold", "message"] if c in df_f.columns]
        st.dataframe(df_f[show_cols], use_container_width=True)

with st.expander("🔎 Raw /status"):
    if status_res.ok:
        st.json(status_res.data)
    else:
        st.error(status_res.error)
