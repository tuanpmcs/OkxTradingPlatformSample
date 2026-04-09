from __future__ import annotations

import argparse
import csv
import sys
import time
from queue import Empty, Queue
from pathlib import Path
from threading import Event, Thread

import grpc
from grpc_tools import protoc


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PROTO_DIR = REPO_ROOT / "proto"
GEN_DIR = SCRIPT_DIR / "_generated"


def ensure_proto_generated() -> None:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    out_pb2 = GEN_DIR / "market_data_pb2.py"
    out_grpc = GEN_DIR / "market_data_pb2_grpc.py"
    if out_pb2.exists() and out_grpc.exists():
        return

    rc = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={GEN_DIR}",
            f"--grpc_python_out={GEN_DIR}",
            str(PROTO_DIR / "market_data.proto"),
        ]
    )
    if rc != 0:
        raise RuntimeError(f"protoc failed with code {rc}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect trades + order book data from MarketData gRPC stream")
    p.add_argument("--target", default="127.0.0.1:50051", help="MarketData gRPC target")
    p.add_argument("--symbol", default="BTC-USDT", help="Symbol")
    p.add_argument("--trade-channel", default="trades", help="Trade channel")
    p.add_argument("--book-channel", default="books5", help="Order book channel")
    p.add_argument("--duration-sec", type=int, default=300, help="Collect duration in seconds")
    p.add_argument("--out-csv", required=True, help="Output CSV path")
    return p.parse_args()


def _parse_float(raw: str | None) -> float:
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _build_row(tick: object, fallback_channel: str, event_type: str, fallback_symbol: str) -> list[str]:
    ts = int(tick.ts) if tick.ts else int(time.time() * 1000)
    fields = tick.fields if getattr(tick, "fields", None) else {}
    channel = fields.get("channel", fallback_channel)
    inst = fields.get("instId", fallback_symbol)
    price = float(tick.price) if tick.price else 0.0
    bid_px = _parse_float(fields.get("bidPx"))
    ask_px = _parse_float(fields.get("askPx"))
    bid_sz = _parse_float(fields.get("bidSz"))
    ask_sz = _parse_float(fields.get("askSz"))

    mid_price = 0.0
    spread = 0.0
    if bid_px > 0 and ask_px > 0:
        mid_price = 0.5 * (bid_px + ask_px)
        spread = ask_px - bid_px

    if price <= 0:
        if mid_price > 0:
            price = mid_price
        elif bid_px > 0:
            price = bid_px
        elif ask_px > 0:
            price = ask_px

    if price <= 0:
        return []

    return [
        str(ts),
        f"{price:.8f}",
        event_type,
        channel,
        inst,
        f"{bid_px:.8f}" if bid_px > 0 else "",
        f"{ask_px:.8f}" if ask_px > 0 else "",
        f"{bid_sz:.8f}" if bid_sz > 0 else "",
        f"{ask_sz:.8f}" if ask_sz > 0 else "",
        f"{spread:.8f}" if spread > 0 else "",
        f"{mid_price:.8f}" if mid_price > 0 else "",
        getattr(tick, "source", "") or "unknown",
    ]


def _start_stream_worker(
    target: str,
    symbol: str,
    channel_name: str,
    event_type: str,
    out_queue: Queue[list[str]],
    stop_evt: Event,
    pb2: object,
    pb2_grpc: object,
) -> Thread:
    def run() -> None:
        channel = grpc.insecure_channel(target)
        stub = pb2_grpc.MarketDataStub(channel)
        req = pb2.SubscribeRequest(symbol=symbol, channel=channel_name)
        try:
            for tick in stub.Subscribe(req):
                if stop_evt.is_set():
                    break
                row = _build_row(tick, fallback_channel=channel_name, event_type=event_type, fallback_symbol=symbol)
                if row:
                    out_queue.put(row)
        except grpc.RpcError:
            # Stream can close during shutdown; keep collector robust.
            pass

    t = Thread(target=run, daemon=True)
    t.start()
    return t


def main() -> None:
    ensure_proto_generated()
    sys.path.insert(0, str(GEN_DIR))
    import market_data_pb2 as pb2  # type: ignore
    import market_data_pb2_grpc as pb2_grpc  # type: ignore

    args = parse_args()
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + max(1, args.duration_sec)
    rows = 0
    trade_rows = 0
    book_rows = 0
    row_queue: Queue[list[str]] = Queue()
    stop_evt = Event()

    _start_stream_worker(
        target=args.target,
        symbol=args.symbol,
        channel_name=args.trade_channel,
        event_type="trade",
        out_queue=row_queue,
        stop_evt=stop_evt,
        pb2=pb2,
        pb2_grpc=pb2_grpc,
    )
    _start_stream_worker(
        target=args.target,
        symbol=args.symbol,
        channel_name=args.book_channel,
        event_type="order_book",
        out_queue=row_queue,
        stop_evt=stop_evt,
        pb2=pb2,
        pb2_grpc=pb2_grpc,
    )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ts",
                "price",
                "event_type",
                "channel",
                "instId",
                "bidPx",
                "askPx",
                "bidSz",
                "askSz",
                "spread",
                "mid_price",
                "source",
            ]
        )

        while time.time() < deadline:
            try:
                row = row_queue.get(timeout=0.5)
            except Empty:
                continue
            writer.writerow(row)
            rows += 1
            if row[2] == "trade":
                trade_rows += 1
            elif row[2] == "order_book":
                book_rows += 1

    stop_evt.set()
    print(
        f"Collected rows={rows} trade_rows={trade_rows} book_rows={book_rows} to {out_path}"
    )


if __name__ == "__main__":
    main()
