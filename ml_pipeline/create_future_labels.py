from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
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

PRICE_CANDIDATE_COLUMNS = (
    "price",
    "mid_price",
    "microprice",
    "best_bid_px",
    "best_ask_px",
)

CXX_FEATURE_COLUMNS_ORDER = [
    "inst_id",
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
    out = pd.to_numeric(series, errors="coerce")
    return out.fillna(default)


def _normalize_input_schema(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    out = df.copy()
    mapping: dict[str, str] = {}

    ts_col = _first_existing_column(out, TS_CANDIDATE_COLUMNS)
    if ts_col is None:
        raise ValueError(
            "Unable to find a timestamp column. "
            f"Expected one of: {list(TS_CANDIDATE_COLUMNS)}"
        )
    out["ts"] = _to_numeric(out[ts_col], default=np.nan)
    mapping["ts"] = ts_col

    if "price" in out.columns:
        out["price"] = _to_numeric(out["price"], default=np.nan)
        mapping["price"] = "price"
    elif "mid_price" in out.columns:
        out["price"] = _to_numeric(out["mid_price"], default=np.nan)
        mapping["price"] = "mid_price"
    elif "best_bid_px" in out.columns and "best_ask_px" in out.columns:
        bid = _to_numeric(out["best_bid_px"], default=np.nan)
        ask = _to_numeric(out["best_ask_px"], default=np.nan)
        out["price"] = (bid + ask) * 0.5
        mapping["price"] = "(best_bid_px + best_ask_px)/2"
    else:
        price_col = _first_existing_column(out, PRICE_CANDIDATE_COLUMNS)
        if price_col is None:
            raise ValueError(
                "Unable to build 'price' column. "
                f"Expected one of: {list(PRICE_CANDIDATE_COLUMNS)}"
            )
        out["price"] = _to_numeric(out[price_col], default=np.nan)
        mapping["price"] = price_col

    if "mid_price" not in out.columns:
        out["mid_price"] = out["price"]
        mapping["mid_price"] = "price"
    else:
        out["mid_price"] = _to_numeric(out["mid_price"], default=np.nan)
        mapping["mid_price"] = "mid_price"

    if "spread" not in out.columns:
        if "best_bid_px" in out.columns and "best_ask_px" in out.columns:
            out["spread"] = _to_numeric(out["best_ask_px"], default=0.0) - _to_numeric(out["best_bid_px"], default=0.0)
            mapping["spread"] = "best_ask_px-best_bid_px"
        else:
            out["spread"] = 0.0
            mapping["spread"] = "constant_0"
    else:
        out["spread"] = _to_numeric(out["spread"], default=0.0)
        mapping["spread"] = "spread"

    if "imbalance" not in out.columns:
        if "imbalance_l5" in out.columns:
            out["imbalance"] = _to_numeric(out["imbalance_l5"], default=0.0)
            mapping["imbalance"] = "imbalance_l5"
        elif "imbalance_l1" in out.columns:
            out["imbalance"] = _to_numeric(out["imbalance_l1"], default=0.0)
            mapping["imbalance"] = "imbalance_l1"
        else:
            out["imbalance"] = 0.0
            mapping["imbalance"] = "constant_0"
    else:
        out["imbalance"] = _to_numeric(out["imbalance"], default=0.0)
        mapping["imbalance"] = "imbalance"

    if "trade_volume" not in out.columns:
        if "buy_volume" in out.columns and "sell_volume" in out.columns:
            out["trade_volume"] = _to_numeric(out["buy_volume"], default=0.0) + _to_numeric(out["sell_volume"], default=0.0)
            mapping["trade_volume"] = "buy_volume+sell_volume"
        else:
            out["trade_volume"] = 0.0
            mapping["trade_volume"] = "constant_0"
    else:
        out["trade_volume"] = _to_numeric(out["trade_volume"], default=0.0)
        mapping["trade_volume"] = "trade_volume"

    if "trade_imbalance" not in out.columns:
        if "buy_volume" in out.columns and "sell_volume" in out.columns:
            out["trade_imbalance"] = _to_numeric(out["buy_volume"], default=0.0) - _to_numeric(out["sell_volume"], default=0.0)
            mapping["trade_imbalance"] = "buy_volume-sell_volume"
        elif "buy_count" in out.columns and "sell_count" in out.columns:
            out["trade_imbalance"] = _to_numeric(out["buy_count"], default=0.0) - _to_numeric(out["sell_count"], default=0.0)
            mapping["trade_imbalance"] = "buy_count-sell_count"
        else:
            out["trade_imbalance"] = 0.0
            mapping["trade_imbalance"] = "constant_0"
    else:
        out["trade_imbalance"] = _to_numeric(out["trade_imbalance"], default=0.0)
        mapping["trade_imbalance"] = "trade_imbalance"

    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=["ts", "price", "mid_price"])
    out = out[out["price"] > 0.0]
    out = out[out["mid_price"] > 0.0]
    out = out.sort_values("ts").reset_index(drop=True)

    return out, mapping


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative float")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create future-delta labels from a feature CSV."
    )
    parser.add_argument(
        "--features-csv",
        required=True,
        type=Path,
        help="Path to the input feature CSV file.",
    )
    parser.add_argument(
        "--out-csv",
        required=True,
        type=Path,
        help="Path to the output labeled CSV file.",
    )
    parser.add_argument(
        "--horizon-sec",
        type=positive_int,
        default=30,
        help="Prediction horizon in seconds. Default: 30",
    )
    parser.add_argument(
        "--horizon-ms",
        type=positive_int,
        default=0,
        help="Prediction horizon in milliseconds. Overrides --horizon-sec when > 0.",
    )
    parser.add_argument(
        "--eps",
        type=non_negative_float,
        default=0.02,
        help="Fallback neutral threshold when spread is unavailable. Default: 0.02",
    )
    parser.add_argument(
        "--spread-eps-multiplier",
        type=non_negative_float,
        default=0.3,
        help="Use eps = multiplier * spread for mid-price direction labels. Default: 0.3",
    )
    parser.add_argument(
        "--drop-neutral",
        action="store_true",
        help="Drop rows where label is neutral.",
    )
    parser.add_argument(
        "--output-pattern",
        choices=["feature_label", "full"],
        default="feature_label",
        help=(
            "Output schema pattern. "
            "feature_label => [FEATURE_COLUMNS + label] (default), "
            "full => include targets/timestamps/debug columns."
        ),
    )
    return parser.parse_args()


def validate_input_dataframe(df: pd.DataFrame) -> None:
    required_columns = {"ts", "price", *FEATURE_COLUMNS}
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}. "
            f"Available columns: {list(df.columns)}"
        )

    if df.empty:
        raise ValueError("Input CSV is empty.")

    if not pd.api.types.is_numeric_dtype(df["ts"]):
        raise ValueError("Column 'ts' must be numeric.")

    if not pd.api.types.is_numeric_dtype(df["price"]):
        raise ValueError("Column 'price' must be numeric.")


def clean_output_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = (
        df.replace([np.inf, -np.inf], np.nan)
        .dropna()
        .reset_index(drop=True)
    )
    return cleaned


def main() -> None:
    args = parse_args()

    if not args.features_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {args.features_csv}")

    raw_df = pd.read_csv(args.features_csv)
    df, input_mapping = _normalize_input_schema(raw_df)
    validate_input_dataframe(df)

    labeled_df = create_future_labels(
        df,
        FeatureConfig(
            horizon_sec=args.horizon_sec,
            horizon_ms=(args.horizon_ms if args.horizon_ms > 0 else None),
        ),
    )
    labeled_df = attach_direction_label(
        labeled_df,
        eps=args.eps,
        spread_multiplier=args.spread_eps_multiplier,
    )

    if args.drop_neutral:
        labeled_df = labeled_df[labeled_df["label"] != "neutral"].copy()

    if args.output_pattern == "feature_label":
        ordered_feature_columns = [
            col for col in CXX_FEATURE_COLUMNS_ORDER if col in labeled_df.columns
        ]
        if not ordered_feature_columns:
            reserved = {
                "target_return",
                "target_delta",
                "label_eps",
                "target_price",
                "target_ts",
                "ts",
            }
            ordered_feature_columns = [
                col for col in labeled_df.columns if col not in reserved and col != "label"
            ]

        output_columns = [*ordered_feature_columns, "label"]
    else:
        output_columns = [
            *FEATURE_COLUMNS,
            "target_return",
            "target_delta",
            "label_eps",
            "label",
            "price",
            "target_price",
            "target_ts",
            "ts",
        ]

    missing_output_columns = sorted(set(output_columns) - set(labeled_df.columns))
    if missing_output_columns:
        raise ValueError(
            f"Expected output columns missing after labeling: {missing_output_columns}"
        )

    output_df = clean_output_dataframe(labeled_df[output_columns])

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(args.out_csv, index=False)

    label_counts = (
        output_df["label"].value_counts(dropna=False).sort_index().to_dict()
        if "label" in output_df.columns
        else {}
    )

    print(f"Input rows:  {len(df)}")
    print(f"Raw rows:    {len(raw_df)}")
    print(f"Output rows: {len(output_df)}")
    print(f"Pattern:     {args.output_pattern}")
    if args.horizon_ms > 0:
        print(f"Horizon:     {args.horizon_ms} ms")
    else:
        print(f"Horizon:     {args.horizon_sec} sec")
    print(f"Epsilon:     {args.spread_eps_multiplier} * spread (fallback {args.eps})")
    print(f"Input map:   {input_mapping}")
    print(f"Label dist:  {label_counts}")
    print(f"Saved to:    {args.out_csv}")


if __name__ == "__main__":
    main()
