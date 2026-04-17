from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import FEATURE_COLUMNS, FeatureConfig, attach_direction_label, create_future_labels


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create future-delta labels from feature CSV")
    p.add_argument("--features-csv", required=True, help="Input feature CSV path")
    p.add_argument("--out-csv", required=True, help="Output labeled CSV path")
    p.add_argument("--horizon-sec", type=int, default=30, help="Label horizon in seconds")
    p.add_argument("--eps", type=float, default=0.0001, help="Neutral threshold for up/down label")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.features_csv)
    required = {"ts", "price"} | set(FEATURE_COLUMNS)
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")

    labeled = create_future_labels(df, FeatureConfig(horizon_sec=args.horizon_sec))
    labeled = attach_direction_label(labeled, eps=args.eps)
    keep = FEATURE_COLUMNS + ["target_return", "label", "price", "target_price", "target_ts", "ts"]
    out_df = (
        labeled[keep]
        .replace([float("inf"), float("-inf")], pd.NA)
        .dropna()
        .reset_index(drop=True)
    )

    out = Path(args.out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False)
    print(f"Saved labeled rows: {len(out_df)} -> {out}")


if __name__ == "__main__":
    main()
