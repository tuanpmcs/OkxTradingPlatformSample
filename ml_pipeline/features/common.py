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
    "rel_spread",
    "microprice",
    "imbalance",
    "imbalance_l1",
    "imbalance_l5",
    "bid_vol_l5",
    "ask_vol_l5",
    "weighted_bid_depth",
    "weighted_ask_depth",
    "trade_count",
    "trade_volume",
    "trade_imbalance",
    "trade_vwap_dev_from_mid",
    "delta_mid_price",
    "delta_spread",
    "delta_imbalance_l5",
    "is_snapshot",
    "is_update",
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
    out["rel_spread"] = 0.0
    out["microprice"] = out["mid_price"]
    out["imbalance"] = 0.0
    out["imbalance_l1"] = 0.0
    out["imbalance_l5"] = 0.0
    out["bid_vol_l5"] = 0.0
    out["ask_vol_l5"] = 0.0
    out["weighted_bid_depth"] = 0.0
    out["weighted_ask_depth"] = 0.0
    out["trade_count"] = 0.0
    out["trade_volume"] = 0.0
    out["trade_imbalance"] = 0.0
    out["trade_vwap_dev_from_mid"] = 0.0
    out["delta_mid_price"] = out["mid_price"].diff().fillna(0.0)
    out["delta_spread"] = 0.0
    out["delta_imbalance_l5"] = 0.0
    out["is_snapshot"] = 1.0
    out["is_update"] = 0.0
    return out


def _normalize_live_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_existing = [
        "ts",
        "price",
        "mid_price",
        "spread",
        "rel_spread",
        "microprice",
        "imbalance",
        "imbalance_l1",
        "imbalance_l5",
        "bid_vol_l5",
        "ask_vol_l5",
        "weighted_bid_depth",
        "weighted_ask_depth",
        "trade_count",
        "trade_volume",
        "trade_imbalance",
        "trade_vwap_dev_from_mid",
        "delta_mid_price",
        "delta_spread",
        "delta_imbalance_l5",
        "is_snapshot",
        "is_update",
        "bidPx",
        "askPx",
        "bidSz",
        "askSz",
        "best_bid_px",
        "best_ask_px",
        "best_bid_sz",
        "best_ask_sz",
    ]
    for col in numeric_existing:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "mid_price" not in out.columns:
        if {"bidPx", "askPx"}.issubset(out.columns):
            out["mid_price"] = 0.5 * (out["bidPx"] + out["askPx"])
        elif "price" in out.columns:
            out["mid_price"] = pd.to_numeric(out["price"], errors="coerce")
        else:
            out["mid_price"] = 0.0

    if "spread" not in out.columns and {"bidPx", "askPx"}.issubset(out.columns):
        out["spread"] = out["askPx"] - out["bidPx"]
    elif "spread" not in out.columns:
        out["spread"] = 0.0

    if "rel_spread" not in out.columns:
        out["rel_spread"] = np.where(np.abs(out["mid_price"]) > 1e-12, out["spread"] / out["mid_price"], 0.0)

    if "microprice" not in out.columns and {"bidPx", "askPx", "bidSz", "askSz"}.issubset(out.columns):
        den = out["bidSz"] + out["askSz"]
        out["microprice"] = np.where(
            np.abs(den) > 1e-12,
            ((out["askPx"] * out["bidSz"]) + (out["bidPx"] * out["askSz"])) / den,
            out["mid_price"],
        )
    elif "microprice" not in out.columns:
        out["microprice"] = out["mid_price"]

    if "imbalance_l1" not in out.columns and {"bidSz", "askSz"}.issubset(out.columns):
        den = out["bidSz"] + out["askSz"]
        out["imbalance_l1"] = np.where(np.abs(den) > 1e-12, (out["bidSz"] - out["askSz"]) / den, 0.0)
    elif "imbalance_l1" not in out.columns:
        out["imbalance_l1"] = 0.0

    if "bid_vol_l5" not in out.columns:
        if "best_bid_sz" in out.columns:
            out["bid_vol_l5"] = out["best_bid_sz"]
        elif "bidSz" in out.columns:
            out["bid_vol_l5"] = out["bidSz"]
        else:
            out["bid_vol_l5"] = 0.0

    if "ask_vol_l5" not in out.columns:
        if "best_ask_sz" in out.columns:
            out["ask_vol_l5"] = out["best_ask_sz"]
        elif "askSz" in out.columns:
            out["ask_vol_l5"] = out["askSz"]
        else:
            out["ask_vol_l5"] = 0.0

    if "weighted_bid_depth" not in out.columns:
        out["weighted_bid_depth"] = out["bid_vol_l5"]
    if "weighted_ask_depth" not in out.columns:
        out["weighted_ask_depth"] = out["ask_vol_l5"]

    if "imbalance_l5" not in out.columns:
        den = out["bid_vol_l5"] + out["ask_vol_l5"]
        fallback = out["imbalance_l1"] if "imbalance_l1" in out.columns else 0.0
        out["imbalance_l5"] = np.where(np.abs(den) > 1e-12, (out["bid_vol_l5"] - out["ask_vol_l5"]) / den, fallback)

    if "imbalance" not in out.columns:
        out["imbalance"] = out["imbalance_l5"]

    defaults = {
        "trade_count": 0.0,
        "trade_volume": 0.0,
        "trade_imbalance": 0.0,
        "trade_vwap_dev_from_mid": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    if "delta_mid_price" not in out.columns:
        out["delta_mid_price"] = out["mid_price"].diff().fillna(0.0)
    if "delta_spread" not in out.columns:
        out["delta_spread"] = out["spread"].diff().fillna(0.0)
    if "delta_imbalance_l5" not in out.columns:
        out["delta_imbalance_l5"] = out["imbalance_l5"].diff().fillna(0.0)

    if "is_snapshot" not in out.columns or "is_update" not in out.columns:
        if "book_action" in out.columns:
            action = out["book_action"].astype(str).str.lower()
            out["is_snapshot"] = np.where(action == "snapshot", 1.0, 0.0)
            out["is_update"] = np.where(action == "update", 1.0, 0.0)
        else:
            out["is_snapshot"] = 0.0
            out["is_update"] = 0.0
            if len(out) > 0:
                out.loc[out.index[0], "is_snapshot"] = 1.0
                if len(out) > 1:
                    out.loc[out.index[1]:, "is_update"] = 1.0

    return out


def _safe_div(num: float, den: float) -> float:
    if abs(den) < 1e-12:
        return 0.0
    return num / den


def _book_payload_from_raw_json(raw_json: object) -> tuple[str, dict[str, object]]:
    if not isinstance(raw_json, str) or not raw_json.strip():
        return "", {}
    try:
        payload = json.loads(raw_json)
    except Exception:
        return "", {}

    action = _normalize_text(payload.get("action", ""))
    book_obj: dict[str, object] = {}
    data = payload.get("data", [])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        book_obj = data[0]
    elif isinstance(payload, dict):
        book_obj = payload
    return action, book_obj


def _extract_book_action(row: pd.Series, raw_action: str = "") -> str:
    for col in ("book_action", "action"):
        if col in row:
            value = _normalize_text(row.get(col))
            if value:
                return value
    if raw_action:
        return raw_action
    return ""


def _extract_l2_from_book_obj(book_obj: dict[str, object], max_levels: int = 5) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if not book_obj:
        return [], []

    bids_out: list[tuple[float, float]] = []
    asks_out: list[tuple[float, float]] = []
    bids = book_obj.get("bids", [])
    asks = book_obj.get("asks", [])

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


def _levels_from_top_of_book(row: pd.Series) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bid_px = _to_float(row.get("bidPx", row.get("best_bid_px", 0.0)), 0.0)
    ask_px = _to_float(row.get("askPx", row.get("best_ask_px", 0.0)), 0.0)
    bid_sz = _to_float(row.get("bidSz", row.get("best_bid_sz", 0.0)), 0.0)
    ask_sz = _to_float(row.get("askSz", row.get("best_ask_sz", 0.0)), 0.0)
    bids = [(bid_px, bid_sz)] if bid_px > 0.0 and bid_sz >= 0.0 else []
    asks = [(ask_px, ask_sz)] if ask_px > 0.0 and ask_sz >= 0.0 else []
    return bids, asks


def _apply_book_levels(
    book: dict[str, dict[float, float]],
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    action: str,
) -> None:
    if action == "snapshot":
        book["bids"].clear()
        book["asks"].clear()

    for px, sz in bids:
        if sz <= 0.0:
            book["bids"].pop(px, None)
        else:
            book["bids"][px] = sz
    for px, sz in asks:
        if sz <= 0.0:
            book["asks"].pop(px, None)
        else:
            book["asks"][px] = sz


def _top_levels(book: dict[str, dict[float, float]], max_levels: int = 5) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = sorted(book["bids"].items(), key=lambda x: x[0], reverse=True)[:max_levels]
    asks = sorted(book["asks"].items(), key=lambda x: x[0])[:max_levels]
    return bids, asks


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
    books_by_inst: dict[str, dict[str, dict[float, float]]] = {}

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

        raw_action = ""
        raw_book_obj: dict[str, object] = {}
        if "raw_json" in row:
            raw_action, raw_book_obj = _book_payload_from_raw_json(row.get("raw_json"))
        action = _extract_book_action(row, raw_action)

        bids_msg, asks_msg = _extract_l2_from_book_obj(raw_book_obj)
        if not bids_msg and not asks_msg:
            bids_msg, asks_msg = _levels_from_top_of_book(row)

        # books5 messages carry a complete top-5 image. books messages carry an initial
        # snapshot followed by deltas, so keep a per-instrument in-memory book.
        if channel == "books5":
            action = action or "snapshot"
            bids_l2, asks_l2 = bids_msg[:5], asks_msg[:5]
        else:
            action = action or ("snapshot" if inst_id not in books_by_inst else "update")
            book = books_by_inst.setdefault(inst_id, {"bids": {}, "asks": {}})
            _apply_book_levels(book, bids_msg, asks_msg, action)
            bids_l2, asks_l2 = _top_levels(book, 5)

        if not bids_l2 or not asks_l2:
            continue

        bid_px = bids_l2[0][0]
        ask_px = asks_l2[0][0]
        bid_sz = bids_l2[0][1]
        ask_sz = asks_l2[0][1]

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

        bid_vol_5 = _sum_sizes(bids_l2, 5)
        ask_vol_5 = _sum_sizes(asks_l2, 5)
        weighted_bid_depth = _weighted_depth(bids_l2, 5)
        weighted_ask_depth = _weighted_depth(asks_l2, 5)
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
                "book_action": action,
                "is_snapshot": 1.0 if action == "snapshot" else 0.0,
                "is_update": 1.0 if action == "update" else 0.0,
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
    future_bid = np.full(len(out), np.nan, dtype=float)
    future_ask = np.full(len(out), np.nan, dtype=float)
    target_ts = np.full(len(out), np.nan, dtype=float)
    if np.any(valid):
        current_mid_np = current_mid.to_numpy(dtype=float)
        future_mid[valid] = current_mid_np[idx[valid]]
        if "best_bid_px" in out.columns and "best_ask_px" in out.columns:
            bid_np = pd.to_numeric(out["best_bid_px"], errors="coerce").to_numpy(dtype=float)
            ask_np = pd.to_numeric(out["best_ask_px"], errors="coerce").to_numpy(dtype=float)
            future_bid[valid] = bid_np[idx[valid]]
            future_ask[valid] = ask_np[idx[valid]]
        target_ts[valid] = ts_values[idx[valid]]

    out["target_delta"] = future_mid - current_mid
    out["target_return"] = (future_mid / current_mid) - 1.0
    out["target_price"] = future_mid
    out["future_bid_px"] = future_bid
    out["future_ask_px"] = future_ask
    if "best_bid_px" in out.columns and "best_ask_px" in out.columns:
        current_bid = pd.to_numeric(out["best_bid_px"], errors="coerce")
        current_ask = pd.to_numeric(out["best_ask_px"], errors="coerce")
        out["buy_pnl"] = future_bid - current_ask
        out["sell_pnl"] = current_bid - future_ask
        out["best_pnl"] = np.maximum(out["buy_pnl"], out["sell_pnl"])
        buy_ret = out["buy_pnl"] / current_mid
        sell_ret = out["sell_pnl"] / current_mid
        out["target_exec_return"] = np.where(
            out["buy_pnl"] > out["sell_pnl"],
            buy_ret,
            np.where(out["sell_pnl"] > out["buy_pnl"], -sell_ret, 0.0),
        )
    out["target_ts"] = target_ts

    return out


def attach_direction_label(df_feat: pd.DataFrame, eps: float, spread_multiplier: float = 0.3) -> pd.DataFrame:
    out = df_feat.copy()
    fallback_eps = max(float(eps), 0.0)

    if {"buy_pnl", "sell_pnl"}.issubset(out.columns):
        buy_pnl = pd.to_numeric(out["buy_pnl"], errors="coerce").fillna(0.0)
        sell_pnl = pd.to_numeric(out["sell_pnl"], errors="coerce").fillna(0.0)
        spread = pd.to_numeric(out["spread"], errors="coerce") if "spread" in out.columns else pd.Series(np.nan, index=out.index)
        dynamic_eps = spread_multiplier * spread
        label_eps = dynamic_eps.where(dynamic_eps.notna() & (dynamic_eps >= 0.0), fallback_eps)
        out["label_eps"] = label_eps
        out["label"] = np.where(
            (buy_pnl > label_eps) & (buy_pnl > sell_pnl),
            "up",
            np.where((sell_pnl > label_eps) & (sell_pnl > buy_pnl), "down", "neutral"),
        )
        return out

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


def latest_feature_vector_from_price_points(points: list[dict[str, float]], feature_cols: List[str]) -> np.ndarray:
    if len(points) < 8:
        raise ValueError("need at least 8 price points for feature extraction")

    df = pd.DataFrame(points)
    if "ts" not in df.columns:
        df["ts"] = np.arange(len(df), dtype=np.int64) * 1000
    if "price" not in df.columns:
        raise ValueError("price points must include price")

    rename = {
        "bid_px": "bidPx",
        "ask_px": "askPx",
        "bid_sz": "bidSz",
        "ask_sz": "askSz",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    direct_feature_markers = {
        "mid_price",
        "spread",
        "microprice",
        "imbalance_l5",
        "weighted_bid_depth",
        "weighted_ask_depth",
        "trade_count",
        "trade_volume",
        "trade_imbalance",
        "delta_mid_price",
        "delta_spread",
        "delta_imbalance_l5",
        "is_snapshot",
        "is_update",
    }
    if direct_feature_markers & set(df.columns):
        feat = _normalize_live_feature_frame(df)
    elif {"bidPx", "askPx"}.issubset(df.columns):
        if "book_action" not in df.columns:
            df["book_action"] = np.where(np.arange(len(df)) == 0, "snapshot", "update")
        df["event_type"] = "order_book"
        df["channel"] = "books5"
        feat = build_realtime_features(df, FeatureConfig(horizon_sec=30))
    else:
        feat = _fallback_price_features(df)

    feat = feat.replace([np.inf, -np.inf], np.nan)
    for col in feature_cols:
        if col not in feat.columns:
            feat[col] = 0.0
    feat = feat.dropna(subset=feature_cols)
    if feat.empty:
        raise ValueError("not enough valid rows after feature extraction")
    last = feat.iloc[-1]
    return np.array([float(last[c]) for c in feature_cols], dtype=float)
