from __future__ import annotations

import argparse
import csv
import json
import tarfile
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque

import numpy as np
import pandas as pd

from ml_pipeline.features.common import FEATURE_COLUMNS, FeatureConfig, attach_direction_label, create_future_labels


def _day_bounds_ms(day: str) -> tuple[int, int]:
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + 86_400_000


def _date_range_bounds_ms(start_day: str, end_day: str) -> tuple[int, int]:
    start = datetime.fromisoformat(start_day).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_day).replace(tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000) + 86_400_000
    if end_ms <= start_ms:
        raise ValueError(f"Invalid date range: {start_day} through {end_day}")
    return start_ms, end_ms


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
        if np.isfinite(out):
            return out
    except Exception:
        pass
    return default


def _safe_div(num: float, den: float) -> float:
    return 0.0 if abs(den) < 1e-12 else num / den


def _apply_levels(book: dict[str, dict[float, float]], side: str, levels: list[list[str]]) -> None:
    target = book[side]
    for level in levels:
        if len(level) < 2:
            continue
        px = _to_float(level[0])
        sz = _to_float(level[1])
        if px <= 0.0:
            continue
        if sz <= 0.0:
            target.pop(px, None)
        else:
            target[px] = sz


def _top_levels(book: dict[str, dict[float, float]], n: int = 5) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = sorted(book["bids"].items(), key=lambda x: x[0], reverse=True)[:n]
    asks = sorted(book["asks"].items(), key=lambda x: x[0])[:n]
    return bids, asks


def _sum_size(levels: list[tuple[float, float]]) -> float:
    return float(sum(sz for _, sz in levels))


def _weighted_depth(levels: list[tuple[float, float]]) -> float:
    return float(sum(sz / float(i + 1) for i, (_, sz) in enumerate(levels)))


def _load_trades(trades_zip: Path, start_ms: int, end_ms: int) -> list[tuple[int, str, float, float, str]]:
    rows: list[tuple[int, str, float, float, str]] = []
    with zipfile.ZipFile(trades_zip) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            return rows
        with zf.open(names[0]) as raw:
            reader = csv.DictReader((line.decode("utf-8") for line in raw))
            for row in reader:
                ts = int(float(row.get("created_time", "0") or 0))
                if ts < start_ms or ts >= end_ms:
                    continue
                inst = row.get("instrument_name", "")
                side = str(row.get("side", "")).strip().lower()
                px = _to_float(row.get("price"))
                sz = _to_float(row.get("size"))
                if not inst or side not in {"buy", "sell"} or px <= 0.0 or sz <= 0.0:
                    continue
                rows.append((ts, inst, px, sz, side))
    rows.sort(key=lambda x: x[0])
    return rows


def _trade_features(
    active: Deque[tuple[int, str, float, float, str]],
    inst_id: str,
    mid: float,
) -> dict[str, float]:
    trade_count = 0
    buy_count = 0
    sell_count = 0
    trade_vol = 0.0
    buy_vol = 0.0
    sell_vol = 0.0
    notional = 0.0

    for _ts, inst, px, sz, side in active:
        if inst != inst_id:
            continue
        trade_count += 1
        trade_vol += sz
        notional += px * sz
        if side == "buy":
            buy_count += 1
            buy_vol += sz
        elif side == "sell":
            sell_count += 1
            sell_vol += sz

    trade_vwap = notional / trade_vol if trade_vol > 0.0 else mid
    return {
        "trade_count": float(trade_count),
        "buy_count": float(buy_count),
        "sell_count": float(sell_count),
        "trade_volume": trade_vol,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "trade_imbalance": _safe_div(buy_vol - sell_vol, buy_vol + sell_vol),
        "trade_vwap": trade_vwap,
        "trade_vwap_dev_from_mid": _safe_div(trade_vwap - mid, mid),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build HFT book/trade training dataset from OKX archives")
    p.add_argument("--books-archive", required=True, type=Path)
    p.add_argument("--trades-zip", required=True, type=Path)
    p.add_argument("--day", default="2026-04-12", help="UTC day to keep when explicit ranges are not provided")
    p.add_argument("--books-start-day", help="UTC first book day to keep, YYYY-MM-DD")
    p.add_argument("--books-end-day", help="UTC last book day to keep, inclusive, YYYY-MM-DD")
    p.add_argument("--trades-start-day", help="UTC first trade day to load, YYYY-MM-DD")
    p.add_argument("--trades-end-day", help="UTC last trade day to load, inclusive, YYYY-MM-DD")
    p.add_argument("--out-csv", required=True, type=Path)
    p.add_argument("--sample-ms", type=int, default=1000)
    p.add_argument("--horizon-ms", type=int, default=1000)
    p.add_argument("--trade-lookback-ms", type=int, default=1000)
    p.add_argument("--eps", type=float, default=0.01)
    p.add_argument("--spread-eps-multiplier", type=float, default=0.3)
    p.add_argument("--max-rows", type=int, default=0, help="Optional cap after sampling; 0 means no cap")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.books_start_day or args.books_end_day:
        if not args.books_start_day or not args.books_end_day:
            raise ValueError("--books-start-day and --books-end-day must be provided together")
        book_start_ms, book_end_ms = _date_range_bounds_ms(args.books_start_day, args.books_end_day)
    else:
        book_start_ms, book_end_ms = _day_bounds_ms(args.day)
    if args.trades_start_day or args.trades_end_day:
        if not args.trades_start_day or not args.trades_end_day:
            raise ValueError("--trades-start-day and --trades-end-day must be provided together")
        trade_start_ms, trade_end_ms = _date_range_bounds_ms(args.trades_start_day, args.trades_end_day)
    else:
        trade_start_ms, trade_end_ms = book_start_ms, book_end_ms
    sample_ms = max(1, int(args.sample_ms))
    horizon_ms = max(1, int(args.horizon_ms))
    lookback_ms = max(1, int(args.trade_lookback_ms))

    trades = _load_trades(args.trades_zip, trade_start_ms, trade_end_ms)
    trade_idx = 0
    active_trades: Deque[tuple[int, str, float, float, str]] = deque()

    book: dict[str, dict[float, float]] = {"bids": {}, "asks": {}}
    rows: list[dict[str, object]] = []
    next_sample_ts = book_start_ms
    prev_mid: float | None = None
    prev_spread: float | None = None
    prev_imb5: float | None = None

    with tarfile.open(args.books_archive, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        if not members:
            raise FileNotFoundError(f"No files found inside {args.books_archive}")
        raw = tf.extractfile(members[0])
        if raw is None:
            raise FileNotFoundError(f"Unable to read {members[0].name}")

        for line in raw:
            payload = json.loads(line)
            ts = int(payload.get("ts", 0) or 0)
            if ts < book_start_ms:
                continue
            if ts >= book_end_ms:
                break

            while trade_idx < len(trades) and trades[trade_idx][0] <= ts:
                active_trades.append(trades[trade_idx])
                trade_idx += 1
            cutoff = ts - lookback_ms
            while active_trades and active_trades[0][0] < cutoff:
                active_trades.popleft()

            action = str(payload.get("action", "") or "").lower()
            if action == "snapshot":
                book["bids"].clear()
                book["asks"].clear()
            _apply_levels(book, "bids", payload.get("bids", []) or [])
            _apply_levels(book, "asks", payload.get("asks", []) or [])

            if ts < next_sample_ts:
                continue
            if args.max_rows > 0 and len(rows) >= args.max_rows:
                break

            bids, asks = _top_levels(book, 5)
            if not bids or not asks:
                continue
            bid_px, bid_sz = bids[0]
            ask_px, ask_sz = asks[0]
            if bid_px <= 0.0 or ask_px <= bid_px:
                continue

            mid = 0.5 * (bid_px + ask_px)
            spread = ask_px - bid_px
            bid_vol_5 = _sum_size(bids)
            ask_vol_5 = _sum_size(asks)
            imbalance_l1 = _safe_div(bid_sz - ask_sz, bid_sz + ask_sz)
            imbalance_l5 = _safe_div(bid_vol_5 - ask_vol_5, bid_vol_5 + ask_vol_5)
            microprice = ((ask_px * bid_sz) + (bid_px * ask_sz)) / (bid_sz + ask_sz) if (bid_sz + ask_sz) > 0 else mid
            prev_mid_price = prev_mid if prev_mid is not None else mid
            prev_spread_price = prev_spread if prev_spread is not None else spread
            prev_imbalance = prev_imb5 if prev_imb5 is not None else imbalance_l5
            tfeat = _trade_features(active_trades, str(payload.get("instId", "")), mid)

            rows.append(
                {
                    "ts": ts,
                    "price": mid,
                    "inst_id": payload.get("instId", ""),
                    "book_action": action,
                    "is_snapshot": 1.0 if action == "snapshot" else 0.0,
                    "is_update": 1.0 if action == "update" else 0.0,
                    "book_ts": ts,
                    "book_recv_ts": ts,
                    "book_seq_id": len(rows) + 1,
                    "best_bid_px": bid_px,
                    "best_ask_px": ask_px,
                    "best_bid_sz": bid_sz,
                    "best_ask_sz": ask_sz,
                    "mid_price": mid,
                    "spread": spread,
                    "rel_spread": _safe_div(spread, mid),
                    "microprice": microprice,
                    "imbalance_l1": imbalance_l1,
                    "imbalance_l5": imbalance_l5,
                    "imbalance": imbalance_l5,
                    "bid_vol_l5": bid_vol_5,
                    "ask_vol_l5": ask_vol_5,
                    "weighted_bid_depth": _weighted_depth(bids),
                    "weighted_ask_depth": _weighted_depth(asks),
                    "prev_mid_price": prev_mid_price,
                    "prev_spread": prev_spread_price,
                    "delta_mid_price": mid - prev_mid_price,
                    "delta_spread": spread - prev_spread_price,
                    "delta_imbalance_l5": imbalance_l5 - prev_imbalance,
                    **tfeat,
                }
            )

            prev_mid = mid
            prev_spread = spread
            prev_imb5 = imbalance_l5
            while next_sample_ts <= ts:
                next_sample_ts += sample_ms

    if not rows:
        raise ValueError("No sampled book rows were produced")

    feat = pd.DataFrame(rows)
    labeled = create_future_labels(feat, FeatureConfig(horizon_ms=horizon_ms))
    labeled = attach_direction_label(labeled, eps=float(args.eps), spread_multiplier=float(args.spread_eps_multiplier))
    keep_cols = list(dict.fromkeys([
        *FEATURE_COLUMNS,
        "target_return",
        "target_exec_return",
        "target_delta",
        "buy_pnl",
        "sell_pnl",
        "best_pnl",
        "label_eps",
        "label",
        "price",
        "target_price",
        "future_bid_px",
        "future_ask_px",
        "target_ts",
        "ts",
        "inst_id",
        "book_action",
        "best_bid_px",
        "best_ask_px",
        "best_bid_sz",
        "best_ask_sz",
        "buy_volume",
        "sell_volume",
        "trade_vwap",
    ]))
    keep_cols = [col for col in keep_cols if col in labeled.columns]
    out = labeled[keep_cols].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False)
    print(f"book_rows_sampled={len(feat)}")
    print(f"trades_loaded={len(trades)}")
    print(f"dataset_rows={len(out)}")
    print(f"label_counts={out['label'].value_counts().to_dict()}")
    print(f"saved={args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
