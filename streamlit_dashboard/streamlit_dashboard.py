# streamlit_dashboard.py
# ------------------------------------------------------------
# Edge Device Diagnosis - Streamlit Dashboard
#  - Auto refresh
#  - Trend chart (T1, mu, thresholds)
#  - Alerts table
#  - Threshold control (manual numeric / dynamic mode)
#
# Usage:
#   streamlit run streamlit_dashboard.py
# ------------------------------------------------------------
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    # Parse ts if possible
    for col in ["ts", "timestamp"]:
        if col in df.columns:
            df["ts_dt"] = pd.to_datetime(df[col], errors="coerce")
            break
    if "ts_dt" not in df.columns:
        df["ts_dt"] = pd.NaT
    # Sort ascending for chart
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

# threshold source heuristic
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
    # Normalize manual_threshold display if sentinel used
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

    # display current manual/dynamic view
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
st.subheader("📈 Trend")
if not trend_res.ok:
    st.error(f"/trend error: {trend_res.error}")
elif trend_df.empty:
    st.info("No trend data yet.")
else:
    # Choose motor_id filter if multiple
    if "motor_id" in trend_df.columns:
        mids = sorted(trend_df["motor_id"].dropna().unique().tolist())
        mid_sel = st.selectbox("Trend motor_id", mids, index=0)
        df_plot = trend_df[trend_df["motor_id"] == mid_sel].copy()
    else:
        df_plot = trend_df.copy()

    df_plot = df_plot.sort_values("ts_dt", ascending=True)
    df_plot = df_plot.set_index("ts_dt")

    # Streamlit line chart expects numeric cols
    cols = [c for c in ["t1", "mu", "dynamic_threshold", "final_threshold"] if c in df_plot.columns]
    if cols:
        st.line_chart(df_plot[cols])
    else:
        st.dataframe(df_plot.reset_index())

    # highlight anomalies table
    if "is_anomaly" in df_plot.columns:
        anom_df = df_plot[df_plot["is_anomaly"] == 1] if df_plot["is_anomaly"].dtype != bool else df_plot[df_plot["is_anomaly"]]
        with st.expander("Show anomaly points"):
            st.dataframe(anom_df.reset_index()[["ts_dt"] + [c for c in cols if c in anom_df.columns] + ["is_anomaly"]])

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
        # Filter UI
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

        show_cols = [c for c in [
            "id", "created_at", "timestamp", "motor_id", "severity",
            "threshold_source", "dynamic_threshold", "final_threshold", "message"
        ] if c in df_f.columns]
        st.dataframe(df_f[show_cols], use_container_width=True)

# ---- Status ----
with st.expander("🔎 Raw /status"):
    if status_res.ok:
        st.json(status_res.data)
    else:
        st.error(status_res.error)
