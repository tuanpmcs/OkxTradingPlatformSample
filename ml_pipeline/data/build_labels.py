from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ml_pipeline.features.common import (
    FEATURE_COLUMNS,
    FeatureConfig,
    attach_direction_label,
    create_future_labels,
)


TS_CANDIDATE_COLUMNS = (
    "ts",
    "book_ts",
    "book_recv_ts",
    "exchange_ts_ms",
    "recv_ts_ms",
)

CXX_FEATURE_COLUMNS_ORDER = [
    "inst_id",
    "book_action",
    "is_snapshot",
    "is_update",
    "book_ts",
    "book_recv_ts",
    "book_seq_id",
    "best_bid_px",
    "best_ask_px",
    "best_bid_sz",
    "best_ask_sz",
    "mid_price",
    "spread",
    "rel_spread",
    "microprice",
    "imbalance_l1",
    "imbalance_l5",
    "bid_vol_l5",
    "ask_vol_l5",
    "weighted_bid_depth",
    "weighted_ask_depth",
    "trade_count",
    "buy_count",
    "sell_count",
    "trade_volume",
    "buy_volume",
    "sell_volume",
    "trade_imbalance",
    "trade_vwap",
    "trade_vwap_dev_from_mid",
    "prev_mid_price",
    "prev_spread",
    "delta_mid_price",
    "delta_spread",
    "delta_imbalance_l5",
]


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _to_numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _normalize_input_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    ts_col = _first_existing_column(out, TS_CANDIDATE_COLUMNS)
    if ts_col is None:
        raise ValueError(f"Unable to find timestamp column. Expected one of: {list(TS_CANDIDATE_COLUMNS)}")
    out["ts"] = pd.to_numeric(out[ts_col], errors="coerce")

    if "price" in out.columns:
        out["price"] = pd.to_numeric(out["price"], errors="coerce")
    elif "mid_price" in out.columns:
        out["price"] = pd.to_numeric(out["mid_price"], errors="coerce")
    elif {"best_bid_px", "best_ask_px"}.issubset(out.columns):
        bid = pd.to_numeric(out["best_bid_px"], errors="coerce")
        ask = pd.to_numeric(out["best_ask_px"], errors="coerce")
        out["price"] = (bid + ask) * 0.5
    else:
        raise ValueError("Unable to build price column. Expected price, mid_price, or best_bid_px/best_ask_px")

    if "mid_price" not in out.columns:
        out["mid_price"] = out["price"]
    else:
        out["mid_price"] = pd.to_numeric(out["mid_price"], errors="coerce")

    if "spread" not in out.columns:
        if {"best_bid_px", "best_ask_px"}.issubset(out.columns):
            out["spread"] = _to_numeric(out["best_ask_px"]) - _to_numeric(out["best_bid_px"])
        else:
            out["spread"] = 0.0
    else:
        out["spread"] = _to_numeric(out["spread"])

    if "imbalance" not in out.columns:
        if "imbalance_l5" in out.columns:
            out["imbalance"] = _to_numeric(out["imbalance_l5"])
        elif "imbalance_l1" in out.columns:
            out["imbalance"] = _to_numeric(out["imbalance_l1"])
        else:
            out["imbalance"] = 0.0
    else:
        out["imbalance"] = _to_numeric(out["imbalance"])

    if "trade_volume" not in out.columns:
        if {"buy_volume", "sell_volume"}.issubset(out.columns):
            out["trade_volume"] = _to_numeric(out["buy_volume"]) + _to_numeric(out["sell_volume"])
        else:
            out["trade_volume"] = 0.0
    else:
        out["trade_volume"] = _to_numeric(out["trade_volume"])

    if "trade_imbalance" not in out.columns:
        if {"buy_volume", "sell_volume"}.issubset(out.columns):
            den = _to_numeric(out["buy_volume"]) + _to_numeric(out["sell_volume"])
            num = _to_numeric(out["buy_volume"]) - _to_numeric(out["sell_volume"])
            out["trade_imbalance"] = np.where(np.abs(den) > 1e-12, num / den, 0.0)
        elif {"buy_count", "sell_count"}.issubset(out.columns):
            den = _to_numeric(out["buy_count"]) + _to_numeric(out["sell_count"])
            num = _to_numeric(out["buy_count"]) - _to_numeric(out["sell_count"])
            out["trade_imbalance"] = np.where(np.abs(den) > 1e-12, num / den, 0.0)
        else:
            out["trade_imbalance"] = 0.0
    else:
        out["trade_imbalance"] = _to_numeric(out["trade_imbalance"])

    if "rel_spread" not in out.columns:
        out["rel_spread"] = np.where(np.abs(out["mid_price"]) > 1e-12, out["spread"] / out["mid_price"], 0.0)
    if "microprice" not in out.columns:
        out["microprice"] = out["mid_price"]
    if "imbalance_l1" not in out.columns:
        out["imbalance_l1"] = out["imbalance"]
    if "imbalance_l5" not in out.columns:
        out["imbalance_l5"] = out["imbalance"]
    if "bid_vol_l5" not in out.columns:
        out["bid_vol_l5"] = _to_numeric(out["best_bid_sz"]) if "best_bid_sz" in out.columns else 0.0
    if "ask_vol_l5" not in out.columns:
        out["ask_vol_l5"] = _to_numeric(out["best_ask_sz"]) if "best_ask_sz" in out.columns else 0.0
    if "weighted_bid_depth" not in out.columns:
        out["weighted_bid_depth"] = out["bid_vol_l5"]
    if "weighted_ask_depth" not in out.columns:
        out["weighted_ask_depth"] = out["ask_vol_l5"]
    for col, default in {
        "trade_count": 0.0,
        "trade_vwap_dev_from_mid": 0.0,
        "delta_mid_price": 0.0,
        "delta_spread": 0.0,
        "delta_imbalance_l5": 0.0,
        "is_snapshot": 0.0,
        "is_update": 1.0,
    }.items():
        if col not in out.columns:
            out[col] = default

    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=["ts", "price", "mid_price"])
    out = out[(out["price"] > 0.0) & (out["mid_price"] > 0.0)]
    return out.sort_values("ts").reset_index(drop=True)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("must be a non-negative float")
    return parsed


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create future-delta labels from a feature CSV")
    p.add_argument("--features-csv", required=True, type=Path)
    p.add_argument("--out-csv", required=True, type=Path)
    p.add_argument("--horizon-sec", type=_positive_int, default=30)
    p.add_argument("--horizon-ms", type=int, default=0)
    p.add_argument("--eps", type=_non_negative_float, default=0.0001)
    p.add_argument("--spread-eps-multiplier", type=_non_negative_float, default=0.3)
    p.add_argument("--drop-neutral", action="store_true")
    p.add_argument("--output-pattern", choices=["feature_label", "full"], default="feature_label")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.features_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {args.features_csv}")

    df = _normalize_input_schema(pd.read_csv(args.features_csv))
    missing = sorted(set(FEATURE_COLUMNS + ["ts", "price"]) - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns after normalization: {missing}")

    labeled = create_future_labels(
        df,
        FeatureConfig(
            horizon_sec=args.horizon_sec,
            horizon_ms=(args.horizon_ms if args.horizon_ms > 0 else None),
        ),
    )
    labeled = attach_direction_label(
        labeled,
        eps=args.eps,
        spread_multiplier=args.spread_eps_multiplier,
    )
    if args.drop_neutral:
        labeled = labeled[labeled["label"] != "neutral"].copy()

    if args.output_pattern == "feature_label":
        ordered = [col for col in CXX_FEATURE_COLUMNS_ORDER if col in labeled.columns]
        output_columns = [*(ordered or FEATURE_COLUMNS), "label"]
    else:
        output_columns = [
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
        ]
        output_columns = [col for col in output_columns if col in labeled.columns]

    missing_output = sorted(set(output_columns) - set(labeled.columns))
    if missing_output:
        raise ValueError(f"Expected output columns missing after labeling: {missing_output}")

    out = labeled[output_columns].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False)

    label_counts = out["label"].value_counts(dropna=False).sort_index().to_dict()
    print(f"Input rows:  {len(df)}")
    print(f"Output rows: {len(out)}")
    print(f"Pattern:     {args.output_pattern}")
    print(f"Label dist:  {label_counts}")
    print(f"Saved to:    {args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
