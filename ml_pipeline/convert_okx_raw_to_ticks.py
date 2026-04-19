from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


CSV_COLUMNS = [
    "ts",
    "price",
    "event_type",
    "channel",
    "instId",
    "trade_side",
    "trade_size",
    "bidPx",
    "askPx",
    "bidSz",
    "askSz",
    "mid_price_feat",
    "spread_feat",
    "imbalance_feat",
    "trade_count_lookback",
    "trade_vol_lookback",
    "buy_vol_lookback",
    "sell_vol_lookback",
    "raw_json",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert OKX raw trades CSV + L2 orderbook JSONL into unified ticks CSV for training."
    )
    p.add_argument("--trades-csv", required=True, help="Path to trades CSV (e.g. BTC-USDT-trades-*.csv)")
    p.add_argument("--l2-data", required=True, help="Path to L2 orderbook JSONL (.data)")
    p.add_argument("--out-csv", required=True, help="Output unified ticks CSV")
    p.add_argument("--symbol", default="BTC-USDT", help="Instrument symbol filter, default: BTC-USDT")
    p.add_argument(
        "--book-sample-ms",
        type=int,
        default=10,
        help="Minimum milliseconds between written order-book rows (0 = write every update). Default: 10",
    )
    return p.parse_args()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _fmt(value: float) -> str:
    if value == 0.0:
        return ""
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _best_ask(asks: dict[float, float]) -> tuple[float, float]:
    if not asks:
        return 0.0, 0.0
    px = min(asks)
    return px, asks[px]


def _best_bid(bids: dict[float, float]) -> tuple[float, float]:
    if not bids:
        return 0.0, 0.0
    px = max(bids)
    return px, bids[px]


def _book_row(
    ts_ms: int,
    symbol: str,
    bid_px: float,
    ask_px: float,
    bid_sz: float,
    ask_sz: float,
) -> dict[str, str]:
    if bid_px > 0.0 and ask_px > 0.0:
        mid = 0.5 * (bid_px + ask_px)
        spread = ask_px - bid_px
        denom = bid_sz + ask_sz
        imbalance = ((bid_sz - ask_sz) / denom) if denom > 0.0 else 0.0
    else:
        mid = 0.0
        spread = 0.0
        imbalance = 0.0
    return {
        "ts": str(ts_ms),
        "price": _fmt(mid),
        "event_type": "order_book",
        "channel": "books",
        "instId": symbol,
        "trade_side": "",
        "trade_size": "",
        "bidPx": _fmt(bid_px),
        "askPx": _fmt(ask_px),
        "bidSz": _fmt(bid_sz),
        "askSz": _fmt(ask_sz),
        "mid_price_feat": _fmt(mid),
        "spread_feat": _fmt(spread),
        "imbalance_feat": _fmt(imbalance),
        "trade_count_lookback": "",
        "trade_vol_lookback": "",
        "buy_vol_lookback": "",
        "sell_vol_lookback": "",
        "raw_json": "",
    }


def _trade_row(
    ts_ms: int,
    symbol: str,
    side: str,
    trade_price: float,
    trade_size: float,
    bid_px: float,
    ask_px: float,
    bid_sz: float,
    ask_sz: float,
) -> dict[str, str]:
    if bid_px > 0.0 and ask_px > 0.0:
        mid = 0.5 * (bid_px + ask_px)
        spread = ask_px - bid_px
        denom = bid_sz + ask_sz
        imbalance = ((bid_sz - ask_sz) / denom) if denom > 0.0 else 0.0
    else:
        mid = 0.0
        spread = 0.0
        imbalance = 0.0
    return {
        "ts": str(ts_ms),
        "price": _fmt(trade_price),
        "event_type": "trade",
        "channel": "trades",
        "instId": symbol,
        "trade_side": side.lower(),
        "trade_size": _fmt(trade_size),
        "bidPx": _fmt(bid_px),
        "askPx": _fmt(ask_px),
        "bidSz": _fmt(bid_sz),
        "askSz": _fmt(ask_sz),
        "mid_price_feat": _fmt(mid),
        "spread_feat": _fmt(spread),
        "imbalance_feat": _fmt(imbalance),
        "trade_count_lookback": "",
        "trade_vol_lookback": "",
        "buy_vol_lookback": "",
        "sell_vol_lookback": "",
        "raw_json": "",
    }


def convert(args: argparse.Namespace) -> tuple[int, int, int | None, int | None, int | None, int | None]:
    symbol = args.symbol.strip()
    sample_ms = max(0, int(args.book_sample_ms))

    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    last_book_emit_ts = -1

    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trades_written = 0
    books_written = 0
    min_trade_ts: int | None = None
    max_trade_ts: int | None = None
    min_book_ts: int | None = None
    max_book_ts: int | None = None

    with out_path.open("w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        # 1) Parse orderbook file first to build best bid/ask timeline rows.
        with Path(args.l2_data).open("r", encoding="utf-8", errors="replace") as fb:
            for line in fb:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                inst_id = str(payload.get("instId", "")).strip()
                if symbol and inst_id != symbol:
                    continue
                ts_ms = _safe_int(payload.get("ts"), 0)
                if ts_ms <= 0:
                    continue

                for px_raw, sz_raw, *_ in payload.get("bids", []):
                    px = _safe_float(px_raw, 0.0)
                    sz = _safe_float(sz_raw, 0.0)
                    if px <= 0.0:
                        continue
                    if sz <= 0.0:
                        bids.pop(px, None)
                    else:
                        bids[px] = sz

                for px_raw, sz_raw, *_ in payload.get("asks", []):
                    px = _safe_float(px_raw, 0.0)
                    sz = _safe_float(sz_raw, 0.0)
                    if px <= 0.0:
                        continue
                    if sz <= 0.0:
                        asks.pop(px, None)
                    else:
                        asks[px] = sz

                bid_px, bid_sz = _best_bid(bids)
                ask_px, ask_sz = _best_ask(asks)
                if bid_px <= 0.0 or ask_px <= 0.0:
                    continue
                if ask_px <= bid_px:
                    continue

                if sample_ms > 0 and last_book_emit_ts >= 0 and (ts_ms - last_book_emit_ts) < sample_ms:
                    continue

                writer.writerow(_book_row(ts_ms, symbol, bid_px, ask_px, bid_sz, ask_sz))
                books_written += 1
                last_book_emit_ts = ts_ms
                if min_book_ts is None or ts_ms < min_book_ts:
                    min_book_ts = ts_ms
                if max_book_ts is None or ts_ms > max_book_ts:
                    max_book_ts = ts_ms

        # 2) Parse trade CSV and append rows (with blank book values if no state available).
        # Input schema expected:
        # instrument_name,trade_id,side,price,size,created_time
        with Path(args.trades_csv).open("r", newline="", encoding="utf-8", errors="replace") as ft:
            reader = csv.DictReader(ft)
            for row in reader:
                inst_id = str(row.get("instrument_name", "")).strip()
                if symbol and inst_id != symbol:
                    continue
                ts_ms = _safe_int(row.get("created_time"), 0)
                if ts_ms <= 0:
                    continue
                side = str(row.get("side", "")).strip().lower()
                if side not in {"buy", "sell"}:
                    continue
                trade_price = _safe_float(row.get("price"), 0.0)
                trade_size = _safe_float(row.get("size"), 0.0)
                if trade_price <= 0.0 or trade_size <= 0.0:
                    continue

                bid_px, bid_sz = _best_bid(bids)
                ask_px, ask_sz = _best_ask(asks)
                writer.writerow(
                    _trade_row(
                        ts_ms=ts_ms,
                        symbol=symbol,
                        side=side,
                        trade_price=trade_price,
                        trade_size=trade_size,
                        bid_px=bid_px,
                        ask_px=ask_px,
                        bid_sz=bid_sz,
                        ask_sz=ask_sz,
                    )
                )
                trades_written += 1
                if min_trade_ts is None or ts_ms < min_trade_ts:
                    min_trade_ts = ts_ms
                if max_trade_ts is None or ts_ms > max_trade_ts:
                    max_trade_ts = ts_ms

    return trades_written, books_written, min_trade_ts, max_trade_ts, min_book_ts, max_book_ts


def main() -> int:
    args = parse_args()
    trades_written, books_written, min_trade_ts, max_trade_ts, min_book_ts, max_book_ts = convert(args)
    print(
        f"Converted OKX raw files -> {args.out_csv} | "
        f"books rows: {books_written}, trades rows: {trades_written}"
    )
    if (
        min_trade_ts is not None
        and max_trade_ts is not None
        and min_book_ts is not None
        and max_book_ts is not None
        and (max_trade_ts < min_book_ts or max_book_ts < min_trade_ts)
    ):
        print(
            "WARNING: trade and order-book timestamps do not overlap. "
            "Feature trade lookback fields may be mostly zero."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
