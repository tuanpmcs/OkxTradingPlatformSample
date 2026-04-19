from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import grpc
from grpc_tools import protoc


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PROTO_DIR = REPO_ROOT / "backend" / "proto"
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
    p = argparse.ArgumentParser(description="Test PredictionService/Predict")
    p.add_argument("--target", default="127.0.0.1:50061", help="Prediction gRPC target")
    p.add_argument("--csv", required=True, help="Input CSV with ts,price")
    p.add_argument("--symbol", default="BTC-USDT", help="Symbol")
    p.add_argument("--channel", default="tickers", help="Channel")
    p.add_argument("--horizon-sec", type=int, default=30, help="Horizon")
    p.add_argument("--points", type=int, default=120, help="Last N points")
    return p.parse_args()


def main() -> None:
    ensure_proto_generated()
    sys.path.insert(0, str(GEN_DIR))
    import market_data_pb2 as pb2  # type: ignore
    import market_data_pb2_grpc as pb2_grpc  # type: ignore

    args = parse_args()
    rows = []
    with open(args.csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(float(row["ts"]))
                price = float(row["price"])
            except Exception:
                continue
            if price > 0:
                rows.append((ts, price))

    if len(rows) < 8:
        raise ValueError("Need at least 8 valid rows in CSV")
    rows = rows[-max(8, args.points) :]

    req = pb2.PredictRequest(
        symbol=args.symbol,
        channel=args.channel,
        horizon_sec=args.horizon_sec,
        points=[pb2.PricePoint(ts=ts, price=price) for ts, price in rows],
    )

    channel = grpc.insecure_channel(args.target)
    stub = pb2_grpc.PredictionServiceStub(channel)
    resp = stub.Predict(req, timeout=2.0)
    print(
        {
            "model_name": resp.model_name,
            "signal": resp.signal,
            "last_price": resp.last_price,
            "predicted_price": resp.predicted_price,
            "predicted_return": resp.predicted_return,
            "detail": resp.detail,
        }
    )


if __name__ == "__main__":
    main()
