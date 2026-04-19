from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from typing import Deque
from typing import List

import numpy as np
import pandas as pd


FEATURE_COLUMNS: List[str] = [
    "mid_price",
    "spread",
    "imbalance",
    "trade_volume",
    "trade_imbalance",
]


@dataclass
class FeatureConfig:
    horizon_sec: int = 30
    horizon_ms: int | None = None
    trade_lookback_ms: int = 1000
    book_channel: str = "books"
    trade_channel: str = "trades"

    def resolved_horizon_ms(self) -> int:
        if self.horizon_ms is not None:
            return max(1, int(self.horizon_ms))
        return max(1, int(self.horizon_sec) * 1000)


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


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
        if np.isfinite(out):
            return out
    except Exception:
        pass
    return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _fallback_price_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mid_price"] = pd.to_numeric(out.get("price", 0.0), errors="coerce").fillna(0.0)
    out["spread"] = 0.0
    out["imbalance"] = 0.0
    out["trade_volume"] = 0.0
    out["trade_imbalance"] = 0.0
    return out


def _safe_div(num: float, den: float) -> float:
    if abs(den) < 1e-12:
        return 0.0
    return num / den


def _extract_l2_from_raw_json(raw_json: object, max_levels: int = 5) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if not isinstance(raw_json, str) or not raw_json.strip():
        return [], []
    try:
        payload = json.loads(raw_json)
    except Exception:
        return [], []

    bids_out: list[tuple[float, float]] = []
    asks_out: list[tuple[float, float]] = []
    bids = payload.get("bids", [])
    asks = payload.get("asks", [])

    for lvl in bids[:max_levels]:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        px = _to_float(lvl[0], 0.0)
        sz = _to_float(lvl[1], 0.0)
        if px > 0.0 and sz >= 0.0:
            bids_out.append((px, sz))

    for lvl in asks[:max_levels]:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        px = _to_float(lvl[0], 0.0)
        sz = _to_float(lvl[1], 0.0)
        if px > 0.0 and sz >= 0.0:
            asks_out.append((px, sz))

    return bids_out, asks_out


def _sum_sizes(levels: list[tuple[float, float]], n: int = 5) -> float:
    return sum(sz for _, sz in levels[:n])


def _weighted_depth(levels: list[tuple[float, float]], n: int = 5) -> float:
    total = 0.0
    for idx, (_, sz) in enumerate(levels[:n]):
        total += sz / float(idx + 1)
    return total


def build_realtime_features(df: pd.DataFrame, cfg: FeatureConfig | None = None) -> pd.DataFrame:
    cfg = cfg or FeatureConfig()
    if df.empty:
        return df.copy()

    out = df.copy().sort_values("ts").reset_index(drop=True)
    has_stream_cols = ("channel" in out.columns) or ("event_type" in out.columns)
    if not has_stream_cols:
        return _fallback_price_features(out)

    channels = out["channel"].astype(str).str.lower() if "channel" in out.columns else pd.Series("", index=out.index)
    event_types = (
        out["event_type"].astype(str).str.lower() if "event_type" in out.columns else pd.Series("", index=out.index)
    )
    trade_sides = out["trade_side"].astype(str).str.lower() if "trade_side" in out.columns else pd.Series("", index=out.index)

    trades: Deque[tuple[int, str, float, float, str]] = deque()
    feature_rows: list[dict[str, object]] = []

    prev_mid: float | None = None
    prev_spread: float | None = None
    prev_imbalance5: float | None = None

    lookback_ms = max(1, int(cfg.trade_lookback_ms))
    book_channel = _normalize_text(cfg.book_channel)
    trade_channel = _normalize_text(cfg.trade_channel)

    for idx, row in out.iterrows():
        ts_ms = _to_int(row.get("ts"), 0)
        channel = _normalize_text(channels.iloc[idx])
        event_type = _normalize_text(event_types.iloc[idx])
        trade_side = _normalize_text(trade_sides.iloc[idx])
        inst_id = str(row.get("instId", "") or row.get("instrument_name", "") or "")

        is_trade = (event_type == "trade") or (trade_channel and trade_channel in channel) or (channel == "trades")
        if is_trade:
            trade_size = _to_float(row.get("trade_size"), 0.0)
            trade_price = _to_float(row.get("price"), 0.0)
            if trade_size > 0.0 and trade_price > 0.0 and trade_side in {"buy", "sell"}:
                trades.append((ts_ms, inst_id, trade_price, trade_size, trade_side))

        cutoff_ms = ts_ms - lookback_ms
        while trades and trades[0][0] < cutoff_ms:
            trades.popleft()

        is_books = (book_channel and channel == book_channel) or (channel in {"books", "books5"})
        if not is_books:
            continue

        bid_px = _to_float(row.get("bidPx"), 0.0)
        ask_px = _to_float(row.get("askPx"), 0.0)
        bid_sz = _to_float(row.get("bidSz"), 0.0)
        ask_sz = _to_float(row.get("askSz"), 0.0)
        bids_l2: list[tuple[float, float]] = []
        asks_l2: list[tuple[float, float]] = []
        if "raw_json" in row:
            bids_l2, asks_l2 = _extract_l2_from_raw_json(row.get("raw_json"))

        mid = 0.0
        spread = 0.0
        if bid_px > 0.0 and ask_px > bid_px:
            mid = 0.5 * (bid_px + ask_px)
            spread = ask_px - bid_px
        else:
            mid = _to_float(row.get("mid_price_feat"), _to_float(row.get("mid_price"), _to_float(row.get("price"), 0.0)))
            spread = _to_float(row.get("spread_feat"), _to_float(row.get("spread"), 0.0))
        if mid <= 0.0:
            continue

        rel_spread = _safe_div(spread, mid)
        top_denom = bid_sz + ask_sz
        imbalance1 = _safe_div(bid_sz - ask_sz, top_denom)
        microprice = (
            ((ask_px * bid_sz) + (bid_px * ask_sz)) / top_denom
            if (top_denom > 0.0 and bid_px > 0.0 and ask_px > 0.0)
            else mid
        )

        if bids_l2 and asks_l2:
            bid_vol_5 = _sum_sizes(bids_l2, 5)
            ask_vol_5 = _sum_sizes(asks_l2, 5)
            weighted_bid_depth = _weighted_depth(bids_l2, 5)
            weighted_ask_depth = _weighted_depth(asks_l2, 5)
        else:
            bid_vol_5 = bid_sz
            ask_vol_5 = ask_sz
            weighted_bid_depth = bid_sz
            weighted_ask_depth = ask_sz
        imbalance5 = _safe_div(bid_vol_5 - ask_vol_5, bid_vol_5 + ask_vol_5)

        trade_count = 0
        buy_count = 0
        sell_count = 0
        trade_vol = 0.0
        buy_vol = 0.0
        sell_vol = 0.0
        trade_notional = 0.0

        for t_ts, t_inst, t_px, t_sz, t_side in trades:
            if t_ts < cutoff_ms:
                continue
            if inst_id and t_inst and t_inst != inst_id:
                continue
            trade_count += 1
            trade_vol += t_sz
            trade_notional += t_px * t_sz
            if t_side == "buy":
                buy_count += 1
                buy_vol += t_sz
            elif t_side == "sell":
                sell_count += 1
                sell_vol += t_sz

        trade_imbalance = _safe_div(buy_vol - sell_vol, buy_vol + sell_vol)
        signed_vol = buy_vol - sell_vol
        trade_vwap = (trade_notional / trade_vol) if trade_vol > 0.0 else mid
        trade_vwap_dev = _safe_div(trade_vwap - mid, mid)

        prev_mid_price = prev_mid if prev_mid is not None else mid
        prev_spread_price = prev_spread if prev_spread is not None else spread
        prev_imb5 = prev_imbalance5 if prev_imbalance5 is not None else imbalance5
        delta_mid = mid - prev_mid_price
        delta_spread = spread - prev_spread_price
        imbalance5_delta = imbalance5 - prev_imb5

        feature_rows.append(
            {
                "ts": ts_ms,
                "price": mid,
                "event_type": row.get("event_type", "order_book"),
                "channel": row.get("channel", cfg.book_channel),
                "instId": inst_id,
                # C++ feature_row parity fields:
                "inst_id": inst_id,
                "book_ts": ts_ms,
                "book_recv_ts": _to_int(row.get("book_recv_ts"), _to_int(row.get("recv_ts"), ts_ms)),
                "book_seq_id": _to_int(row.get("seqId"), _to_int(row.get("book_seq_id"), 0)),
                "best_bid_px": bid_px,
                "best_ask_px": ask_px,
                "best_bid_sz": bid_sz,
                "best_ask_sz": ask_sz,
                "mid_price": mid,
                "spread": spread,
                "rel_spread": rel_spread,
                "microprice": microprice,
                "imbalance_l1": imbalance1,
                "imbalance_l5": imbalance5,
                "bid_vol_l5": bid_vol_5,
                "ask_vol_l5": ask_vol_5,
                "weighted_bid_depth": weighted_bid_depth,
                "weighted_ask_depth": weighted_ask_depth,
                "trade_count": trade_count,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "trade_volume": trade_vol,
                "buy_volume": buy_vol,
                "sell_volume": sell_vol,
                "trade_imbalance": trade_imbalance,
                "trade_vwap": trade_vwap,
                "trade_vwap_dev_from_mid": trade_vwap_dev,
                "prev_mid_price": prev_mid_price,
                "prev_spread": prev_spread_price,
                "delta_mid_price": delta_mid,
                "delta_spread": delta_spread,
                "delta_imbalance_l5": imbalance5_delta,
                # Backward compatibility aliases:
                "imbalance1": imbalance1,
                "imbalance5": imbalance5,
                "bid_vol_5": bid_vol_5,
                "ask_vol_5": ask_vol_5,
                "trade_count_lookback": trade_count,
                "buy_count_lookback": buy_count,
                "sell_count_lookback": sell_count,
                "trade_vol_lookback": trade_vol,
                "buy_vol_lookback": buy_vol,
                "sell_vol_lookback": sell_vol,
                "signed_vol": signed_vol,
                "trade_imbalance_ratio": trade_imbalance,
                "trade_vwap_dev": trade_vwap_dev,
                "mid_prev": prev_mid_price,
                "spread_prev": prev_spread_price,
                "delta_mid": delta_mid,
                "delta_spread": delta_spread,
                "imbalance5_delta": imbalance5_delta,
                "lookback_ms": lookback_ms,
                # Keep training compatibility: legacy feature name maps to level-5 imbalance.
                "imbalance": imbalance5,
            }
        )

        prev_mid = mid
        prev_spread = spread
        prev_imbalance5 = imbalance5

    if not feature_rows:
        return _fallback_price_features(out)

    return pd.DataFrame(feature_rows)


def create_future_labels(df_feat: pd.DataFrame, cfg: FeatureConfig) -> pd.DataFrame:
    out = df_feat.copy()
    out = out.sort_values("ts").reset_index(drop=True)
    horizon_ms = cfg.resolved_horizon_ms()

    ts_values = pd.to_numeric(out["ts"], errors="coerce").to_numpy(dtype=np.int64)
    future_ts = ts_values + horizon_ms
    idx = np.searchsorted(ts_values, future_ts, side="left")
    valid = idx < len(out)

    current_mid = (
        pd.to_numeric(out["mid_price"], errors="coerce")
        if "mid_price" in out.columns
        else pd.Series(np.nan, index=out.index)
    )
    current_price = pd.to_numeric(out["price"], errors="coerce")
    current_mid = current_mid.where(current_mid.notna(), current_price)

    future_mid = np.full(len(out), np.nan, dtype=float)
    target_ts = np.full(len(out), np.nan, dtype=float)
    if np.any(valid):
        current_mid_np = current_mid.to_numpy(dtype=float)
        future_mid[valid] = current_mid_np[idx[valid]]
        target_ts[valid] = ts_values[idx[valid]]

    out["target_delta"] = future_mid - current_mid
    out["target_return"] = (future_mid / current_mid) - 1.0
    out["target_price"] = future_mid
    out["target_ts"] = target_ts

    return out


def attach_direction_label(df_feat: pd.DataFrame, eps: float, spread_multiplier: float = 0.3) -> pd.DataFrame:
    out = df_feat.copy()
    fallback_eps = max(float(eps), 0.0)

    if "target_delta" in out.columns and "spread" in out.columns:
        delta = pd.to_numeric(out["target_delta"], errors="coerce").fillna(0.0)
        spread = pd.to_numeric(out["spread"], errors="coerce")
        dynamic_eps = spread_multiplier * spread
        label_eps = dynamic_eps.where(dynamic_eps.notna() & (dynamic_eps >= 0.0), fallback_eps)
    else:
        delta = pd.to_numeric(out["target_return"], errors="coerce").fillna(0.0)
        label_eps = pd.Series(fallback_eps, index=out.index)

    out["label_eps"] = label_eps
    out["label"] = np.where(delta > label_eps, "up", np.where(delta < -label_eps, "down", "neutral"))
    return out


def build_features(df: pd.DataFrame, cfg: FeatureConfig) -> pd.DataFrame:
    # Backward-compatible helper used by existing scripts.
    return create_future_labels(build_realtime_features(df, cfg), cfg)


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
