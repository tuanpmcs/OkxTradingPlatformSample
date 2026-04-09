from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd


FEATURE_COLUMNS: List[str] = [
    "momentum_3",
    "momentum_5",
    "momentum_8",
    "momentum_13",
    "momentum_21",
    "volatility_10",
    "volatility_20",
    "range_10",
    "range_20",
    "ema_gap_12_26",
    "rsi_14",
]


@dataclass
class FeatureConfig:
    horizon_sec: int = 30


def load_ticks(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "ts" not in df.columns or "price" not in df.columns:
        raise ValueError("CSV must contain columns: ts, price")

    out = df.copy()
    out["ts"] = pd.to_numeric(out["ts"], errors="coerce")
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["ts", "price"]).sort_values("ts").reset_index(drop=True)

    optional_numeric = ["bidPx", "askPx", "bidSz", "askSz"]
    for col in optional_numeric:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def build_realtime_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    px = out["price"]

    out["momentum_3"] = (px / px.shift(3)) - 1.0
    out["momentum_5"] = (px / px.shift(5)) - 1.0
    out["momentum_8"] = (px / px.shift(8)) - 1.0
    out["momentum_13"] = (px / px.shift(13)) - 1.0
    out["momentum_21"] = (px / px.shift(21)) - 1.0

    roll10 = px.rolling(window=10, min_periods=10)
    mean10 = roll10.mean()
    std10 = roll10.std(ddof=0)
    max10 = roll10.max()
    min10 = roll10.min()

    roll20 = px.rolling(window=20, min_periods=20)
    mean20 = roll20.mean()
    std20 = roll20.std(ddof=0)
    max20 = roll20.max()
    min20 = roll20.min()

    out["volatility_10"] = np.where(mean10 != 0, std10 / mean10, 0.0)
    out["volatility_20"] = np.where(mean20 != 0, std20 / mean20, 0.0)
    out["range_10"] = np.where(mean10 != 0, (max10 - min10) / mean10, 0.0)
    out["range_20"] = np.where(mean20 != 0, (max20 - min20) / mean20, 0.0)

    ema12 = px.ewm(span=12, adjust=False).mean()
    ema26 = px.ewm(span=26, adjust=False).mean()
    out["ema_gap_12_26"] = np.where(px != 0, (ema12 - ema26) / px, 0.0)

    delta = px.diff()
    gain = delta.clip(lower=0).rolling(window=14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=14).mean()
    rs = np.where(loss != 0, gain / loss, 0.0)
    out["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))
    out["rsi_14"] = out["rsi_14"] / 100.0

    # Optional order-book context features (when bid/ask are present).
    if "bidPx" in out.columns and "askPx" in out.columns:
        bid = pd.to_numeric(out["bidPx"], errors="coerce")
        ask = pd.to_numeric(out["askPx"], errors="coerce")
        mid = 0.5 * (bid + ask)
        valid = (mid > 0) & (ask > 0) & (bid > 0)
        out["mid_price"] = np.where(valid, mid, np.nan)
        out["spread_bps"] = np.where(valid, ((ask - bid) / mid) * 10000.0, np.nan)
    else:
        out["mid_price"] = np.nan
        out["spread_bps"] = np.nan

    if "bidSz" in out.columns and "askSz" in out.columns:
        bid_sz = pd.to_numeric(out["bidSz"], errors="coerce")
        ask_sz = pd.to_numeric(out["askSz"], errors="coerce")
        denom = bid_sz + ask_sz
        out["book_imbalance"] = np.where(denom > 0, (bid_sz - ask_sz) / denom, np.nan)
    else:
        out["book_imbalance"] = np.nan

    return out


def create_future_labels(df_feat: pd.DataFrame, cfg: FeatureConfig) -> pd.DataFrame:
    out = df_feat.copy()
    horizon_ms = cfg.horizon_sec * 1000
    future_ts = out["ts"] + horizon_ms
    idx = np.searchsorted(out["ts"].to_numpy(), future_ts.to_numpy(), side="left")
    idx = np.clip(idx, 0, len(out) - 1)
    future_price = out["price"].to_numpy()[idx]
    out["target_return"] = (future_price / out["price"]) - 1.0
    out["target_price"] = future_price
    out["target_ts"] = out["ts"].to_numpy()[idx]

    return out


def build_features(df: pd.DataFrame, cfg: FeatureConfig) -> pd.DataFrame:
    # Backward-compatible helper used by existing scripts.
    return create_future_labels(build_realtime_features(df), cfg)


def select_training_rows(df_feat: pd.DataFrame) -> pd.DataFrame:
    cols = FEATURE_COLUMNS + ["target_return", "price", "target_price", "ts"]
    out = df_feat[cols].copy()
    out = out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    return out


def latest_feature_vector_from_prices(prices: np.ndarray, feature_cols: List[str]) -> np.ndarray:
    if prices.size < 32:
        raise ValueError("need at least 32 price points for robust feature extraction")

    ts = np.arange(prices.size, dtype=np.int64) * 1000
    df = pd.DataFrame({"ts": ts, "price": prices})
    feat = build_features(df, FeatureConfig(horizon_sec=30))
    feat = feat.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols)
    if feat.empty:
        raise ValueError("not enough valid rows after feature extraction")
    last = feat.iloc[-1]
    return np.array([float(last[c]) for c in feature_cols], dtype=float)
