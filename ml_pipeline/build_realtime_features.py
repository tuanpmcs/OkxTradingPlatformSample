from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from common import FeatureConfig, build_realtime_features, load_ticks


class GracefulStop(Exception):
    pass


_STOP_REQUESTED = False


def _handle_stop(signum, _frame) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    raise GracefulStop(f"received signal {signum}")


def _check_stop() -> None:
    if _STOP_REQUESTED:
        raise GracefulStop("stop requested")


def _sample_values(df, column: str, limit: int = 8) -> str:
    if column not in df.columns:
        return "<missing>"
    values = [str(x) for x in df[column].dropna().astype(str).unique()[:limit]]
    return ", ".join(values) if values else "<none>"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build real-time style features from collected ticks")
    p.add_argument("--csv", required=True, help="Input raw ticks CSV")
    p.add_argument("--out-csv", required=True, help="Output feature CSV path")
    p.add_argument("--symbol", default="", help="Optional instId filter")
    p.add_argument(
        "--channels",
        default="trades,books",
        help="Optional comma-separated channel filter, e.g. trades,books",
    )
    p.add_argument(
        "--book-channel",
        default="books",
        help="Order-book channel used for feature row sampling. Default: books",
    )
    p.add_argument(
        "--trade-channel",
        default="trades",
        help="Trade channel used for lookback aggregation. Default: trades",
    )
    p.add_argument(
        "--trade-lookback-ms",
        type=int,
        default=1000,
        help="Trade aggregation lookback in milliseconds. Default: 1000",
    )
    return p.parse_args()


def run() -> None:
    args = parse_args()
    out = Path(args.out_csv)
    tmp_out = out.with_name(f".{out.name}.tmp")

    _check_stop()
    raw_df = load_ticks(args.csv)
    print(
        "Loaded raw rows: "
        f"{len(raw_df)} | symbols: {_sample_values(raw_df, 'instId')} | "
        f"channels: {_sample_values(raw_df, 'channel')}",
        flush=True,
    )

    if raw_df.empty:
        raise ValueError(
            f"No rows found in {args.csv}; collector produced only a header or no usable ticks. "
            "Increase COLLECT_DURATION_SEC and verify the collector is subscribed to books/trades."
        )

    df = raw_df

    if args.symbol and "instId" in df.columns:
        _check_stop()
        df = df[df["instId"] == args.symbol]

    if args.channels and "channel" in df.columns:
        _check_stop()
        allowed = {c.strip() for c in args.channels.split(",") if c.strip()}
        if allowed:
            df = df[df["channel"].isin(allowed)]

    if df.empty:
        print(
            "Filters removed all rows; falling back to all collected rows. "
            f"requested symbol={args.symbol or '<any>'}, channels={args.channels or '<any>'}",
            flush=True,
        )
        df = raw_df

    if df.empty:
        raise ValueError("No usable rows available; cannot build features")

    _check_stop()
    cfg = FeatureConfig(
        trade_lookback_ms=max(1, int(args.trade_lookback_ms)),
        book_channel=args.book_channel,
        trade_channel=args.trade_channel,
    )
    feat = build_realtime_features(df, cfg).sort_values("ts").reset_index(drop=True)
    if feat.empty:
        raise ValueError(
            "No feature rows were produced. Verify books updates exist and symbol/channel filters match input CSV."
        )
    _check_stop()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        feat.to_csv(tmp_out, index=False)
        tmp_out.replace(out)
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise
    print(f"Saved feature rows: {len(feat)} -> {out}")


def main() -> int:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    try:
        run()
    except GracefulStop as exc:
        print(f"feature-builder stopping gracefully: {exc}", file=sys.stderr)
        return 0
    except ValueError as exc:
        print(f"feature-builder failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
