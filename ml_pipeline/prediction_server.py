from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent import futures
from pathlib import Path
from typing import List

import grpc
import joblib
import numpy as np
from common import FEATURE_COLUMNS, latest_feature_vector_from_prices
from lstm_model import LSTMRegressor


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

    from grpc_tools import protoc

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


ensure_proto_generated()
sys.path.insert(0, str(GEN_DIR))
import market_data_pb2 as pb2  # type: ignore  # noqa: E402
import market_data_pb2_grpc as pb2_grpc  # type: ignore  # noqa: E402


FEATURES = ["momentum_5", "momentum_20", "volatility_20", "range_20"]


def compute_features(prices: List[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if arr.size < 8:
        raise ValueError("need at least 8 points")

    last = arr[-1]
    p5 = arr[max(0, arr.size - 6)]
    p20 = arr[max(0, arr.size - 8)]
    recent = arr[-min(20, arr.size) :]
    mean20 = float(np.mean(recent))
    std20 = float(np.std(recent))
    max20 = float(np.max(recent))
    min20 = float(np.min(recent))

    def pct(a: float, b: float) -> float:
        if b == 0:
            return 0.0
        return (a - b) / b

    momentum_5 = pct(last, p5)
    momentum_20 = pct(last, p20)
    volatility_20 = (std20 / mean20) if mean20 != 0 else 0.0
    range_20 = ((max20 - min20) / mean20) if mean20 != 0 else 0.0
    return np.array([momentum_5, momentum_20, volatility_20, range_20], dtype=float)


class PredictionService(pb2_grpc.PredictionServiceServicer):
    def __init__(self, model_path: str) -> None:
        self.path = model_path
        self.mode = "json-linear"
        self.model_obj = None
        self.mean = None
        self.scale = None
        self.weights = None
        self.intercept = None
        self.feature_columns = FEATURE_COLUMNS
        self.name = "PulseLinearV2"
        self.lstm = None
        self.seq_len = 0
        self.ret_mean = 0.0
        self.ret_std = 1.0

        if model_path.endswith(".joblib"):
            bundle = joblib.load(model_path)
            self.mode = str(bundle.get("model_type", "joblib"))
            self.model_obj = bundle["model"]
            self.feature_columns = list(bundle.get("feature_columns", FEATURE_COLUMNS))
            self.name = str(bundle.get("model_name", "PulseTreeV1"))
            self.horizon_sec = int(bundle.get("horizon_sec", 30))
        elif model_path.endswith(".pt"):
            import torch

            artifact = torch.load(model_path, map_location="cpu")
            self.mode = str(artifact.get("model_type", "lstm"))
            self.name = str(artifact.get("model_name", "PulseLSTMV1"))
            self.horizon_sec = int(artifact.get("horizon_sec", 30))
            self.seq_len = int(artifact.get("seq_len", 60))
            self.ret_mean = float(artifact.get("ret_mean", 0.0))
            self.ret_std = float(artifact.get("ret_std", 1.0))
            self.lstm = LSTMRegressor(
                input_dim=int(artifact.get("input_dim", 1)),
                hidden_size=int(artifact.get("hidden_size", 64)),
                num_layers=int(artifact.get("num_layers", 2)),
                dropout=float(artifact.get("dropout", 0.1)),
            )
            self.lstm.load_state_dict(artifact["state_dict"])
            self.lstm.eval()
        else:
            self.model = json.loads(Path(model_path).read_text(encoding="utf-8"))
            self.mean = np.array(self.model["scaler_mean"], dtype=float)
            self.scale = np.array(self.model["scaler_scale"], dtype=float)
            self.weights = np.array(self.model["weights"], dtype=float)
            self.intercept = float(self.model["intercept"])
            self.name = str(self.model.get("name", "PulseLinearV2"))
            self.horizon_sec = int(self.model.get("horizon_sec", 30))

    def Predict(self, request: pb2.PredictRequest, context: grpc.ServicerContext) -> pb2.PredictResponse:
        points = list(request.points)
        if len(points) < 8:
            return pb2.PredictResponse(
                model_name=self.name,
                signal="HOLD",
                detail="Need at least 8 points",
            )

        prices = [float(p.price) for p in points]
        last_price = float(prices[-1])
        arr_prices = np.asarray(prices, dtype=float)

        if self.lstm is not None:
            import torch

            if arr_prices.size < self.seq_len + 1:
                return pb2.PredictResponse(
                    model_name=self.name,
                    signal="HOLD",
                    detail=f"Need at least {self.seq_len + 1} points for LSTM",
                )

            log_returns = np.log(np.maximum(arr_prices[1:], 1e-12) / np.maximum(arr_prices[:-1], 1e-12))
            seq = log_returns[-self.seq_len :].reshape(1, self.seq_len, 1)
            seq = (seq - self.ret_mean) / (self.ret_std if self.ret_std != 0 else 1.0)
            x_t = torch.from_numpy(seq.astype(np.float32))
            with torch.no_grad():
                pred_ret = float(self.lstm(x_t).item())
        else:
            x = latest_feature_vector_from_prices(arr_prices, self.feature_columns)
            if self.model_obj is not None:
                pred_ret = float(self.model_obj.predict(x.reshape(1, -1))[0])
            else:
                x_s = (x - self.mean) / self.scale
                pred_ret = float(self.intercept + np.dot(x_s, self.weights))
        pred_ret = float(np.clip(pred_ret, -0.05, 0.05))
        pred_price = last_price * (1.0 + pred_ret)
        signal = "BUY" if pred_price > last_price else "HOLD"

        return pb2.PredictResponse(
            model_name=self.name,
            signal=signal,
            last_price=last_price,
            predicted_price=pred_price,
            predicted_return=pred_ret,
            detail=f"points={len(points)} mode={self.mode}",
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="gRPC prediction server")
    p.add_argument("--model", required=True, help="Path to model artifact (.json/.joblib/.pt)")
    p.add_argument("--host", default=os.getenv("PRED_GRPC_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("PRED_GRPC_PORT", "50061")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb2_grpc.add_PredictionServiceServicer_to_server(PredictionService(args.model), server)
    bind = f"{args.host}:{args.port}"
    server.add_insecure_port(bind)
    server.start()
    print(f"PredictionService listening on {bind}")
    server.wait_for_termination()


if __name__ == "__main__":
    main()
