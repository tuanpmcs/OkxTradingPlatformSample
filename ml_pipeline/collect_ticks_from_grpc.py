from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

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
    p = argparse.ArgumentParser(description="Collect tick data from MarketData gRPC stream")
    p.add_argument("--target", default="127.0.0.1:50051", help="MarketData gRPC target")
    p.add_argument("--symbol", default="BTC-USDT", help="Symbol")
    p.add_argument("--channel", default="tickers", help="Channel")
    p.add_argument("--duration-sec", type=int, default=300, help="Collect duration in seconds")
    p.add_argument("--out-csv", required=True, help="Output CSV path")
    return p.parse_args()


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
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts", "price", "channel", "instId", "source"])

        channel = grpc.insecure_channel(args.target)
        stub = pb2_grpc.MarketDataStub(channel)
        req = pb2.SubscribeRequest(symbol=args.symbol, channel=args.channel)

        for tick in stub.Subscribe(req):
            ts = int(tick.ts) if tick.ts else int(time.time() * 1000)
            price = float(tick.price)
            if price <= 0:
                continue
            ch = tick.fields.get("channel", args.channel) if tick.fields else args.channel
            inst = tick.fields.get("instId", args.symbol) if tick.fields else args.symbol
            writer.writerow([ts, f"{price:.8f}", ch, inst, tick.source or "unknown"])
            rows += 1
            if time.time() >= deadline:
                break

    print(f"Collected {rows} rows to {out_path}")


if __name__ == "__main__":
    main()
