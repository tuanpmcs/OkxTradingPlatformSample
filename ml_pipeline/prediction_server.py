from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent import futures
from pathlib import Path
from time import perf_counter_ns

# Keep inference runtime memory/CPU predictable inside containers.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import grpc
import joblib
import numpy as np
from common import FEATURE_COLUMNS, latest_feature_vector_from_prices


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PROTO_DIR = REPO_ROOT / "proto"
GEN_DIR = SCRIPT_DIR / "_generated"


def ensure_proto_generated() -> None:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    out_pb2 = GEN_DIR / "market_data_pb2.py"
    out_grpc = GEN_DIR / "market_data_pb2_grpc.py"
    proto_file = PROTO_DIR / "market_data.proto"
    if (
        out_pb2.exists()
        and out_grpc.exists()
        and out_pb2.stat().st_mtime >= proto_file.stat().st_mtime
        and out_grpc.stat().st_mtime >= proto_file.stat().st_mtime
    ):
        return

    from grpc_tools import protoc

    rc = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={GEN_DIR}",
            f"--grpc_python_out={GEN_DIR}",
            str(proto_file),
        ]
    )
    if rc != 0:
        raise RuntimeError(f"protoc failed with code {rc}")


ensure_proto_generated()
sys.path.insert(0, str(GEN_DIR))
import market_data_pb2 as pb2  # type: ignore  # noqa: E402
import market_data_pb2_grpc as pb2_grpc  # type: ignore  # noqa: E402


def signal_from_return(pred_ret: float, eps: float) -> str:
    threshold = max(float(eps), 1e-8)
    if pred_ret > threshold:
        return "LONG"
    if pred_ret < -threshold:
        return "SHORT"
    return "HOLD"


class PredictionService(pb2_grpc.PredictionServiceServicer):
    class LoadedModel:
        def __init__(self, model_path: Path) -> None:
            self.path = model_path
            self.mode = "json-linear"
            self.model_obj = None
            self.mean = None
            self.scale = None
            self.weights = None
            self.intercept = None

            self.feature_columns = FEATURE_COLUMNS
            self.name = "PulseLinearV2"
            self.horizon_sec = 30
            self.label_eps = 0.0001

            self.sequence_model = None
            self.seq_len = 0
            self.input_dim = 1
            self.ret_mean = 0.0
            self.ret_std = 1.0
            self.label_classes = []

            model_path_str = str(model_path)
            if model_path_str.endswith(".joblib") or model_path_str.endswith(".artifact"):
                bundle = joblib.load(model_path_str)
                self.mode = str(bundle.get("model_type", "joblib"))
                self.model_obj = bundle["model"]
                self.feature_columns = list(bundle.get("feature_columns", FEATURE_COLUMNS))
                self.name = str(bundle.get("model_name", "PulseTreeV1"))
                self.horizon_sec = int(bundle.get("horizon_sec", 30))
                self.label_eps = float(bundle.get("label_eps", self.label_eps))
                self.label_classes = list(bundle.get("label_classes", []))
            elif model_path_str.endswith(".pt"):
                import torch
                from lstm_model import build_sequence_model

                torch.set_num_threads(1)
                if hasattr(torch, "set_num_interop_threads"):
                    torch.set_num_interop_threads(1)

                artifact = torch.load(model_path_str, map_location="cpu")
                self.mode = str(artifact.get("model_type", "lstm"))
                self.name = str(artifact.get("model_name", f"Pulse{self.mode.title()}V1"))
                self.horizon_sec = int(artifact.get("horizon_sec", 30))
                self.seq_len = int(artifact.get("seq_len", 60))
                self.input_dim = int(artifact.get("input_dim", 1))
                self.ret_mean = float(artifact.get("ret_mean", 0.0))
                self.ret_std = float(artifact.get("ret_std", 1.0))
                self.label_eps = float(artifact.get("label_eps", self.label_eps))

                self.sequence_model = build_sequence_model(
                    model_type=self.mode,
                    input_dim=self.input_dim,
                    hidden_size=int(artifact.get("hidden_size", 64)),
                    num_layers=int(artifact.get("num_layers", 2)),
                    dropout=float(artifact.get("dropout", 0.1)),
                    nhead=int(artifact.get("nhead", 4)),
                )
                self.sequence_model.load_state_dict(artifact["state_dict"])
                self.sequence_model.eval()
            else:
                model = json.loads(model_path.read_text(encoding="utf-8"))
                self.mean = np.array(model["scaler_mean"], dtype=float)
                self.scale = np.array(model["scaler_scale"], dtype=float)
                self.weights = np.array(model["weights"], dtype=float)
                self.intercept = float(model["intercept"])
                self.name = str(model.get("name", "PulseLinearV2"))
                self.horizon_sec = int(model.get("horizon_sec", 30))
                self.mode = "json-linear"

        def predict_return(self, arr_prices: np.ndarray) -> float:
            if self.sequence_model is not None:
                import torch

                if arr_prices.size < self.seq_len + 1:
                    raise ValueError(f"Need at least {self.seq_len + 1} points for {self.mode}")

                log_returns = np.log(np.maximum(arr_prices[1:], 1e-12) / np.maximum(arr_prices[:-1], 1e-12))
                seq = log_returns[-self.seq_len :].reshape(1, self.seq_len, 1)
                seq = (seq - self.ret_mean) / (self.ret_std if self.ret_std != 0 else 1.0)
                x_t = torch.from_numpy(seq.astype(np.float32))
                with torch.inference_mode():
                    return float(self.sequence_model(x_t).item())

            x = latest_feature_vector_from_prices(arr_prices, self.feature_columns)
            if self.model_obj is not None:
                if self.mode == "xgboost_classifier" and hasattr(self.model_obj, "predict_proba"):
                    raw_proba = self.model_obj.predict_proba(x.reshape(1, -1))[0]
                    class_names = self.label_classes or ["down", "neutral", "up"]
                    prob_by_label = {
                        str(class_names[i]): float(raw_proba[i])
                        for i in range(min(len(class_names), len(raw_proba)))
                    }
                    up = prob_by_label.get("up", 0.0)
                    down = prob_by_label.get("down", 0.0)
                    return (up - down) * self.label_eps
                return float(self.model_obj.predict(x.reshape(1, -1))[0])

            x_s = (x - self.mean) / self.scale
            return float(self.intercept + np.dot(x_s, self.weights))

    def __init__(self, model_path: str, model_dir: str = "") -> None:
        self._lock = threading.RLock()
        self._model_dir = Path(model_dir) if model_dir else Path(model_path).resolve().parent
        self._model_alias_to_path = self._discover_models(self._model_dir)

        default_path = Path(model_path).resolve()
        if not default_path.exists():
            default_path = resolve_model_path(model_path, model_dir).resolve()
        self._default_alias = self._alias_from_path(default_path) or "default"
        self._model_alias_to_path[self._default_alias] = default_path
        self._loaded_models: dict[str, PredictionService.LoadedModel] = {}
        self._loaded_mtime_ns: dict[str, int] = {}
        self._cached_key = None
        self._cached_response = None
        self._load_model(self._default_alias, default_path)

    @staticmethod
    def _alias_from_path(path: Path) -> str:
        name = path.name.lower()
        if "xgboost" in name:
            return "xgboost"
        if "lstm" in name:
            return "lstm"
        if "cnn" in name:
            return "cnn"
        if "transformer" in name:
            return "transformer"
        if name.endswith(".artifact") or name.endswith(".joblib"):
            return "xgboost"
        return path.stem.lower()

    @staticmethod
    def _discover_models(model_dir: Path) -> dict[str, Path]:
        aliases: dict[str, Path] = {}
        candidates = [
            ("xgboost", model_dir / "pulse_xgboost_v1.joblib"),
            ("xgboost", model_dir / "pulse_best_model.artifact"),
            ("lstm", model_dir / "pulse_lstm_v1.pt"),
            ("cnn", model_dir / "pulse_cnn_v1.pt"),
            ("transformer", model_dir / "pulse_transformer_v1.pt"),
        ]
        for alias, path in candidates:
            if path.exists() and path.is_file():
                aliases[alias] = path.resolve()
        for pattern in ("*.joblib", "*.artifact", "*.json", "*.pt"):
            for path in model_dir.glob(pattern):
                if not path.is_file():
                    continue
                alias = PredictionService._alias_from_path(path)
                aliases.setdefault(alias, path.resolve())
        return aliases

    def _resolve_alias(self, requested_model_type: str) -> str:
        value = (requested_model_type or "").strip().lower()
        if not value:
            return self._default_alias
        alias_map = {
            "xgb": "xgboost",
            "tree": "xgboost",
            "xgboost": "xgboost",
            "lstm": "lstm",
            "cnn": "cnn",
            "transformer": "transformer",
        }
        alias = alias_map.get(value, value)
        if alias in self._model_alias_to_path:
            return alias
        return self._default_alias

    def _load_model(self, alias: str, path: Path) -> "PredictionService.LoadedModel":
        loaded = PredictionService.LoadedModel(path)
        self._loaded_models[alias] = loaded
        self._loaded_mtime_ns[alias] = path.stat().st_mtime_ns
        self._cached_key = None
        self._cached_response = None
        return loaded

    def _get_model(self, requested_model_type: str) -> tuple[str, "PredictionService.LoadedModel"]:
        with self._lock:
            self._model_alias_to_path.update(self._discover_models(self._model_dir))
            alias = self._resolve_alias(requested_model_type)
            path = self._model_alias_to_path.get(alias) or self._model_alias_to_path[self._default_alias]
            current = self._loaded_models.get(alias)
            current_mtime = self._loaded_mtime_ns.get(alias, -1)
            file_mtime = path.stat().st_mtime_ns
            if current is None or current_mtime != file_mtime:
                current = self._load_model(alias, path)
            return alias, current

    @staticmethod
    def _request_cache_key(request: pb2.PredictRequest, points: list[pb2.PricePoint]) -> tuple:
        if not points:
            return ("", "", 0, 0.0, 0)
        last = points[-1]
        return (
            str(getattr(request, "symbol", "") or ""),
            str(getattr(request, "channel", "") or ""),
            int(getattr(last, "ts", 0) or 0),
            float(getattr(last, "price", 0.0) or 0.0),
            len(points),
        )

    def Predict(self, request: pb2.PredictRequest, context: grpc.ServicerContext) -> pb2.PredictResponse:
        started_ns = perf_counter_ns()
        selected_alias, model = self._get_model(getattr(request, "model_type", ""))
        points = list(request.points)
        if len(points) < 8:
            return pb2.PredictResponse(
                model_name=model.name,
                signal="HOLD",
                detail="Need at least 8 points",
            )

        cache_key = (selected_alias, *self._request_cache_key(request, points))
        if self._cached_key == cache_key and self._cached_response is not None:
            return pb2.PredictResponse(**self._cached_response)

        arr_prices = np.fromiter((float(p.price) for p in points), dtype=np.float64, count=len(points))
        last_price = float(arr_prices[-1])

        try:
            pred_ret = model.predict_return(arr_prices)
        except ValueError as err:
            return pb2.PredictResponse(
                model_name=model.name,
                signal="HOLD",
                last_price=last_price,
                predicted_price=last_price,
                predicted_return=0.0,
                detail=str(err),
            )

        pred_ret = float(np.clip(pred_ret, -0.05, 0.05))
        pred_price = last_price * (1.0 + pred_ret)
        signal = signal_from_return(pred_ret, model.label_eps)

        detail = json.dumps(
            {
                "mode": self.mode,
                "alias": selected_alias,
                "points": len(points),
                "horizon_sec": int(getattr(request, "horizon_sec", 0) or model.horizon_sec),
                "infer_us": int((perf_counter_ns() - started_ns) / 1000),
            },
            separators=(",", ":"),
        )
        response_payload = {
            "model_name": model.name,
            "signal": signal,
            "last_price": last_price,
            "predicted_price": pred_price,
            "predicted_return": pred_ret,
            "detail": detail,
        }
        self._cached_key = cache_key
        self._cached_response = response_payload
        return pb2.PredictResponse(
            model_name=model.name,
            signal=signal,
            last_price=last_price,
            predicted_price=pred_price,
            predicted_return=pred_ret,
            detail=detail,
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="gRPC inference-only prediction server")
    p.add_argument("--model", required=True, help="Path to model artifact (.json/.joblib/.artifact/.pt)")
    p.add_argument(
        "--model-dir",
        default=os.getenv("MODEL_DIR_PATH", ""),
        help="Optional model directory to auto-fallback when --model is missing",
    )
    p.add_argument("--host", default=os.getenv("PRED_GRPC_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("PRED_GRPC_PORT", "50061")))
    return p.parse_args()


def resolve_model_path(model_path: str, model_dir: str) -> Path:
    requested = Path(model_path)
    if requested.exists() and requested.is_file():
        return requested

    search_dir = Path(model_dir) if model_dir else requested.parent
    if not search_dir.exists() or not search_dir.is_dir():
        raise FileNotFoundError(f"Model not found: {requested}")

    preferred_names = [
        "pulse_xgboost_v1.joblib",
        "pulse_best_model.artifact",
        "pulse_lstm_v1.pt",
    ]
    for name in preferred_names:
        candidate = search_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate

    all_candidates: list[Path] = []
    for pattern in ("*.joblib", "*.artifact", "*.json", "*.pt"):
        all_candidates.extend(search_dir.glob(pattern))
    all_candidates = [p for p in all_candidates if p.is_file()]
    if not all_candidates:
        raise FileNotFoundError(f"No model artifact found in {search_dir}")

    all_candidates.sort(key=lambda p: p.stat().st_size)
    return all_candidates[0]


def main() -> None:
    args = parse_args()
    model_path = resolve_model_path(args.model, args.model_dir)
    print(f"Loading default model: {model_path}", flush=True)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    pb2_grpc.add_PredictionServiceServicer_to_server(
        PredictionService(str(model_path), args.model_dir),
        server,
    )

    bind = f"{args.host}:{args.port}"
    server.add_insecure_port(bind)
    server.start()
    print(f"PredictionService listening on {bind}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
