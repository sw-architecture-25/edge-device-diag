# -*- coding: utf-8 -*-
"""
CNN+LSTM pre-event (key-day spike) predictor

- Focuses on rare spike days BEFORE events
- Emphasizes |delta_resid| + z_volratio coincidence
"""

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

EPS = 1e-9

# -------------------------
# Utilities
# -------------------------
def ensure_sorted(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

def rolling_z(x, w):
    mu = x.rolling(w, min_periods=w).mean()
    sd = x.rolling(w, min_periods=w).std(ddof=0)
    return (x - mu) / (sd + EPS)

def rolling_slope(arr):
    x = np.arange(len(arr))
    xm, ym = x.mean(), arr.mean()
    return np.sum((x-xm)*(arr-ym)) / (np.sum((x-xm)**2) + EPS)

# -------------------------
# Feature engineering
# -------------------------
def add_features(df, z_w=30, vol_s=7, vol_l=30):
    df = df.copy()

    df["resid"] = df["motor_actual"] - df["motor_est"]
    df["delta_resid"] = df["resid"].diff()
    df["abs_delta_resid"] = df["delta_resid"].abs()

    df["z_delta"] = rolling_z(df["abs_delta_resid"], z_w)

    df["vol_short"] = df["resid"].rolling(vol_s, min_periods=vol_s).std(ddof=0)
    df["vol_long"]  = df["resid"].rolling(vol_l, min_periods=vol_l).std(ddof=0)
    df["vol_ratio"] = df["vol_short"] / (df["vol_long"] + EPS)
    df["z_volratio"] = rolling_z(df["vol_ratio"], z_w)

    df["risk_score_change"] = 0.65*df["z_delta"] + 0.35*df["z_volratio"]

    return df

def add_spike_features(df, spike_delta_thr=9, spike_vol_thr=1.2):
    df = df.copy()
    df["spike_delta"] = (df["abs_delta_resid"] >= spike_delta_thr).astype(int)
    df["spike_vol"]   = (df["z_volratio"] >= spike_vol_thr).astype(int)
    df["spike_both"]  = (df["spike_delta"] & df["spike_vol"]).astype(int)

    for w in [3,5]:
        df[f"spike_cnt_{w}"] = df["spike_both"].rolling(w, min_periods=w).sum()

    df["zvol_slope_5"] = (
        df["z_volratio"]
        .rolling(5, min_periods=5)
        .apply(lambda a: rolling_slope(np.array(a)), raw=False)
    )
    return df

# -------------------------
# Label: key-day prewindow
# -------------------------
def build_keyday_label(df, event_col, horizon):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    events = df.loc[df[event_col]==1, "date"].tolist()

    y = np.zeros(len(df), dtype=int)
    for ed in events:
        s = ed - pd.Timedelta(days=horizon)
        e = ed - pd.Timedelta(days=1)
        mask = (df["date"]>=s)&(df["date"]<=e)&(df["spike_both"]==1)
        y[mask.values] = 1
    return y

# -------------------------
# Dataset
# -------------------------
class SeqDataset(Dataset):
    def __init__(self, X, y, seq_len):
        self.seq_len = seq_len
        self.samples = []

        for i in range(len(X) - seq_len):
            xs = X[i:i+seq_len]
            yt = y[i+seq_len-1]

            # 🔥 NaN / Inf 하나라도 있으면 버림
            if not np.isfinite(xs).all():
                continue

            self.samples.append((xs, yt))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        xs, yt = self.samples[idx]
        return (
            torch.tensor(xs, dtype=torch.float32),
            torch.tensor(yt, dtype=torch.float32),
        )


# -------------------------
# Model
# -------------------------
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
        # x: (B,T,F)
        x = x.transpose(1,2)        # (B,F,T)
        x = self.cnn(x)             # (B,32,T)
        x = x.transpose(1,2)        # (B,T,32)
        _, (h, _) = self.lstm(x)    # h:(1,B,64)
        out = self.fc(h[-1])
        return out.squeeze(-1)

# -------------------------
# Train
# -------------------------
def train_epoch(model, loader, opt, crit):
    model.train()
    tot = 0
    for X,y in loader:
        opt.zero_grad()
        p = model(X)
        loss = crit(p, y)
        loss.backward()
        opt.step()
        tot += loss.item()
    return tot/len(loader)

# -------------------------
# Main
# -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--event_col", default="synthetic_event")
    ap.add_argument("--horizon_days", type=int, default=10)
    ap.add_argument("--seq_len", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=20)
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    df = ensure_sorted(pd.read_csv(args.csv))
    df = add_features(df)
    df = add_spike_features(df)

    df["y"] = build_keyday_label(df, args.event_col, args.horizon_days)
    print("Total raw rows:", len(df))
    print("Positive labels:", df["y"].sum())

    feat_cols = [
        "resid","delta_resid","abs_delta_resid","z_delta",
        "vol_ratio","z_volratio","risk_score_change",
        "spike_delta","spike_vol","spike_both",
        "spike_cnt_3","spike_cnt_5","zvol_slope_5"
    ]

    data = df[feat_cols].values
    labels = df["y"].values

    # split (time-based)
    dates = df["date"]
    tr = dates<"2023-01-01"
    va = (dates>="2023-01-01")&(dates<"2024-01-01")
    te = dates>="2024-01-01"

    ds_tr = SeqDataset(data[tr], labels[tr], args.seq_len)
    dl_tr = DataLoader(ds_tr, batch_size=32, shuffle=True)
    print("Train samples after NaN filter:", len(ds_tr))

    model = CNNLSTM(F=len(feat_cols))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    # weighted BCE
    pos_weight = torch.tensor(5.0)
    crit = nn.BCEWithLogitsLoss()

    for ep in range(args.epochs):
        loss = train_epoch(model, dl_tr, opt, crit)
        print(f"[Epoch {ep+1}] loss={loss:.4f}")

    torch.save(model.state_dict(), out/"cnn_lstm_keyday.pth")
    df.to_csv(out/"dataset_with_labels.csv", index=False)

    print("Saved model & dataset")

if __name__=="__main__":
    main()

