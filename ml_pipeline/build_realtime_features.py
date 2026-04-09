from __future__ import annotations

import argparse
from pathlib import Path

from common import build_realtime_features, load_ticks


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build real-time style features from collected ticks")
    p.add_argument("--csv", required=True, help="Input raw ticks CSV")
    p.add_argument("--out-csv", required=True, help="Output feature CSV path")
    p.add_argument("--symbol", default="", help="Optional instId filter")
    p.add_argument(
        "--channels",
        default="",
        help="Optional comma-separated channel filter, e.g. trades,books5",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = load_ticks(args.csv)

    if args.symbol and "instId" in df.columns:
        df = df[df["instId"] == args.symbol]

    if args.channels and "channel" in df.columns:
        allowed = {c.strip() for c in args.channels.split(",") if c.strip()}
        if allowed:
            df = df[df["channel"].isin(allowed)]

    if df.empty:
        raise ValueError("No rows left after filters; cannot build features")

    feat = build_realtime_features(df).sort_values("ts").reset_index(drop=True)
    out = Path(args.out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    feat.to_csv(out, index=False)
    print(f"Saved feature rows: {len(feat)} -> {out}")


if __name__ == "__main__":
    main()
