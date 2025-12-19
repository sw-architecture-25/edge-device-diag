# -*- coding: utf-8 -*-
"""
CNN+LSTM prewindow inference + evaluation (FINAL)

Includes:
- CNN+LSTM probability inference
- spike-conditioned probability scaling
- spike-specific rolling threshold
- ✅ minimal rule-based safeguard: (spike_both & z_delta >= k)
- day-level confusion matrix
- event-level evaluation
- alert episodes & annual coverage
"""

import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from pathlib import Path

EPS = 1e-9

# =========================================================
# Model (same as training)
# =========================================================
class CNNLSTM(nn.Module):
    def __init__(self, F):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv1d(F, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(32, 32, kernel_size=5, padding=2),
            nn.ReLU(),
        )
        self.lstm = nn.LSTM(32, 64, batch_first=True)
        self.fc = nn.Linear(64, 1)

    def forward(self, x):
        # x: [B, T, F]
        x = x.transpose(1, 2)   # [B, F, T]
        x = self.cnn(x)
        x = x.transpose(1, 2)   # [B, T, C]
        _, (h, _) = self.lstm(x)
        return self.fc(h[-1]).squeeze(-1)

# =========================================================
# Feature engineering
# =========================================================
def rolling_z(x, w):
    mu = x.rolling(w, min_periods=w).mean()
    sd = x.rolling(w, min_periods=w).std(ddof=0)
    return (x - mu) / (sd + EPS)

def rolling_slope(arr):
    x = np.arange(len(arr))
    xm, ym = x.mean(), arr.mean()
    return np.sum((x-xm)*(arr-ym)) / (np.sum((x-xm)**2) + EPS)

def add_features(df):
    df = df.copy()

    df["resid"] = df["motor_actual"] - df["motor_est"]
    df["delta_resid"] = df["resid"].diff()
    df["abs_delta_resid"] = df["delta_resid"].abs()

    df["z_delta"] = rolling_z(df["abs_delta_resid"], 30)

    df["vol_short"] = df["resid"].rolling(7, min_periods=7).std(ddof=0)
    df["vol_long"]  = df["resid"].rolling(30, min_periods=30).std(ddof=0)
    df["vol_ratio"] = df["vol_short"] / (df["vol_long"] + EPS)
    df["z_volratio"] = rolling_z(df["vol_ratio"], 30)

    df["risk_score_change"] = 0.65*df["z_delta"] + 0.35*df["z_volratio"]

    # spike definitions
    df["spike_delta"] = (df["abs_delta_resid"] >= 9).astype(int)
    df["spike_vol"]   = (df["z_volratio"] >= 1.2).astype(int)
    df["spike_both"]  = (df["spike_delta"] & df["spike_vol"]).astype(int)

    for w in [3, 5]:
        df[f"spike_cnt_{w}"] = df["spike_both"].rolling(w, min_periods=w).sum()

    df["zvol_slope_5"] = (
        df["z_volratio"]
        .rolling(5, min_periods=5)
        .apply(lambda a: rolling_slope(np.array(a)), raw=False)
    )

    return df

# =========================================================
# Key-day label (used only for evaluation)
# =========================================================
def build_keyday_label(df, event_col, horizon):
    y = np.zeros(len(df), dtype=int)
    events = df.loc[df[event_col] == 1, "date"].tolist()
    for ed in events:
        s = ed - pd.Timedelta(days=horizon)
        e = ed - pd.Timedelta(days=1)
        m = (df["date"] >= s) & (df["date"] <= e) & (df["spike_both"] == 1)
        y[m.values] = 1
    return y

# =========================================================
# Evaluation helpers
# =========================================================
def confusion(y_true, y_pred):
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    return tp, fp, tn, fn

def alert_episodes(df):
    eps = []
    a = df["alert"].values
    d = df["date"].values
    i = 0
    while i < len(a):
        if a[i] == 1:
            j = i
            while j+1 < len(a) and a[j+1] == 1:
                j += 1
            eps.append((pd.to_datetime(d[i]), pd.to_datetime(d[j])))
            i = j + 1
        else:
            i += 1
    return eps

# =========================================================
# Main
# =========================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--event_col", default="synthetic_event")

    ap.add_argument("--seq_len", type=int, default=60)
    ap.add_argument("--horizon_days", type=int, default=10)

    ap.add_argument("--alpha", type=float, default=10.0)
    ap.add_argument("--cal_w", type=int, default=90)
    ap.add_argument("--q_base", type=float, default=0.995)
    ap.add_argument("--q_spike", type=float, default=0.99)

    # 🔥 NEW: safeguard threshold
    ap.add_argument("--z_delta_thr", type=float, default=2.0)

    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------
    # Load & features
    # -----------------------------------------------------
    df = pd.read_csv(args.csv, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = add_features(df)

    # label only for evaluation
    df["y"] = build_keyday_label(df, args.event_col, args.horizon_days)

    feat_cols = [
        "resid","delta_resid","abs_delta_resid","z_delta",
        "vol_ratio","z_volratio","risk_score_change",
        "spike_delta","spike_vol","spike_both",
        "spike_cnt_3","spike_cnt_5","zvol_slope_5"
    ]

    X = df[feat_cols].values.astype(np.float32)

    # -----------------------------------------------------
    # Load model
    # -----------------------------------------------------
    model = CNNLSTM(len(feat_cols))
    model.load_state_dict(torch.load(args.model, map_location="cpu"))
    model.eval()

    # -----------------------------------------------------
    # Inference
    # -----------------------------------------------------
    p = np.full(len(df), np.nan)
    with torch.no_grad():
        for i in range(args.seq_len-1, len(df)):
            xs = X[i-args.seq_len+1:i+1]
            if not np.isfinite(xs).all():
                continue
            logit = model(torch.tensor(xs).unsqueeze(0)).item()
            p[i] = 1.0 / (1.0 + np.exp(-logit))

    df["p_pre_event"] = p

    # -----------------------------------------------------
    # Spike-conditioned scaling
    # -----------------------------------------------------
    df["p_adj"] = df["p_pre_event"]
    m = (df["spike_both"] == 1) & df["p_pre_event"].notna()
    df.loc[m, "p_adj"] = np.minimum(1.0, args.alpha * df.loc[m, "p_pre_event"])

    # -----------------------------------------------------
    # Spike-specific rolling thresholds
    # -----------------------------------------------------
    df["p_thr_base"] = df["p_adj"].rolling(args.cal_w, min_periods=args.cal_w).quantile(args.q_base)
    df["p_thr_spike"] = df["p_adj"].rolling(args.cal_w, min_periods=args.cal_w).quantile(args.q_spike)

    df["p_thr"] = np.where(
        df["spike_both"] == 1,
        df["p_thr_spike"],
        df["p_thr_base"],
    )

    # -----------------------------------------------------
    # Main alert (probability-based)
    # -----------------------------------------------------
    df["alert_main"] = (df["p_adj"] >= df["p_thr"]) & df["p_thr"].notna()

    # -----------------------------------------------------
    # 🔥 NEW: minimal safeguard rule
    # -----------------------------------------------------
    df["alert_safeguard"] = (
        (df["spike_both"] == 1) &
        (df["z_delta"] >= args.z_delta_thr)
    )

    # -----------------------------------------------------
    # Final alert
    # -----------------------------------------------------
    df["alert"] = (df["alert_main"] | df["alert_safeguard"]).astype(int)

    # =====================================================
    # Evaluation (2024)
    # =====================================================
    df_test = df[(df["date"] >= "2024-01-01") & (df["date"] <= "2024-12-31")].copy()

    tp, fp, tn, fn = confusion(df_test["y"].values, df_test["alert"].values)

    events = df_test.loc[df_test[args.event_col] == 1, "date"].tolist()
    episodes = alert_episodes(df_test)

    print("\n=== DAY-LEVEL CONFUSION (2024) ===")
    print(f"TP={tp}, FP={fp}, TN={tn}, FN={fn}")

    print("\n=== EVENT-LEVEL RESULTS ===")
    for ed in events:
        hit = False
        first = None
        for s, e in episodes:
            if s < ed <= s + pd.Timedelta(days=args.horizon_days):
                hit = True
                first = s
                break
        print({
            "event_date": str(ed.date()),
            "hit": hit,
            "first_alert": str(first.date()) if first else None,
            "lead_days": (ed - first).days if first else None
        })

    print("\n=== ALERT EPISODES ===")
    for s, e in episodes:
        print(f"{s.date()} ~ {e.date()}")

    covered = set()
    for s, e in episodes:
        for d in pd.date_range(s, s + pd.Timedelta(days=args.horizon_days)):
            covered.add(d.date())
    coverage = len(covered) / 365.0

    print(f"\nCoverage (2024): {coverage*100:.2f}%")

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------
    out_csv = out / "temperature_with_alerts.csv"
    df.to_csv(out_csv, index=False)
    print("\nSaved:", out_csv)

# =========================================================
if __name__ == "__main__":
    main()

