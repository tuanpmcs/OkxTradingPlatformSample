from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import List

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


FEATURES = ["momentum_5", "momentum_20", "volatility_20", "range_20"]


@dataclass
class StrategyConfig:
    mode: str = "market_making"
    hold_ms: int = 500
    mm_adverse_ret_threshold: float = 0.0006
    mm_one_sided_imbalance_threshold: float = 0.15
    min_spread_bps: float = 0.8
    alpha_imbalance_threshold: float = 0.20
    alpha_pred_ret_threshold: float = 0.0001
    max_entry_spread_bps: float = 3.0


@dataclass
class BookSnapshot:
    bid_px: float
    ask_px: float
    bid_sz: float
    ask_sz: float


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


def _safe_float(value: object) -> float:
    try:
        out = float(value)
        if np.isfinite(out):
            return out
    except Exception:
        pass
    return 0.0


def _parse_strategy_cfg(request: pb2.PredictRequest) -> StrategyConfig:
    mode = str(getattr(request, "strategy_mode", "") or "market_making")
    if mode not in {"market_making", "short_term_alpha"}:
        mode = "market_making"
    return StrategyConfig(
        mode=mode,
        hold_ms=max(1, int(getattr(request, "hold_ms", 0) or 500)),
        mm_adverse_ret_threshold=max(
            1e-8, _safe_float(getattr(request, "mm_adverse_ret_threshold", 0.0) or 0.0006)
        ),
        mm_one_sided_imbalance_threshold=max(
            1e-6, _safe_float(getattr(request, "mm_one_sided_imbalance_threshold", 0.0) or 0.15)
        ),
        min_spread_bps=max(1e-6, _safe_float(getattr(request, "min_spread_bps", 0.0) or 0.8)),
        alpha_imbalance_threshold=max(
            1e-6, _safe_float(getattr(request, "alpha_imbalance_threshold", 0.0) or 0.20)
        ),
        alpha_pred_ret_threshold=max(
            1e-8, _safe_float(getattr(request, "alpha_pred_ret_threshold", 0.0) or 0.0001)
        ),
        max_entry_spread_bps=max(
            1e-6, _safe_float(getattr(request, "max_entry_spread_bps", 0.0) or 3.0)
        ),
    )


def _extract_latest_book(points: List[pb2.PricePoint]) -> BookSnapshot | None:
    for p in reversed(points):
        bid_px = _safe_float(getattr(p, "bid_px", 0.0))
        ask_px = _safe_float(getattr(p, "ask_px", 0.0))
        if bid_px > 0 and ask_px > bid_px:
            return BookSnapshot(
                bid_px=bid_px,
                ask_px=ask_px,
                bid_sz=max(0.0, _safe_float(getattr(p, "bid_sz", 0.0))),
                ask_sz=max(0.0, _safe_float(getattr(p, "ask_sz", 0.0))),
            )
    return None


def _spread_bps(book: BookSnapshot) -> float:
    mid = 0.5 * (book.bid_px + book.ask_px)
    if mid <= 0:
        return 0.0
    return ((book.ask_px - book.bid_px) / mid) * 10000.0


def _imbalance(book: BookSnapshot) -> float:
    denom = book.bid_sz + book.ask_sz
    if denom <= 0:
        return 0.0
    return (book.bid_sz - book.ask_sz) / denom


def decide_strategy_action(pred_ret: float, book: BookSnapshot | None, cfg: StrategyConfig) -> tuple[str, str]:
    if book is None:
        return ("HOLD", "Missing bid/ask snapshot")

    spread = _spread_bps(book)
    imb = _imbalance(book)
    abs_ret = abs(pred_ret)

    if cfg.mode == "market_making":
        if spread < cfg.min_spread_bps:
            return ("HOLD", f"spread {spread:.2f}bps < min {cfg.min_spread_bps:.2f}bps")
        if abs_ret >= cfg.mm_adverse_ret_threshold:
            return (
                "HOLD",
                f"adverse filter hit |ret|={abs_ret:.6f} >= {cfg.mm_adverse_ret_threshold:.6f}",
            )
        if imb >= cfg.mm_one_sided_imbalance_threshold:
            return ("SHORT", f"one-sided risk imbalance={imb:.3f}")
        if imb <= -cfg.mm_one_sided_imbalance_threshold:
            return ("LONG", f"one-sided risk imbalance={imb:.3f}")
        if pred_ret > 0:
            return ("LONG", f"balanced quote with positive drift ret={pred_ret:.6f}")
        if pred_ret < 0:
            return ("SHORT", f"balanced quote with negative drift ret={pred_ret:.6f}")
        return ("HOLD", "neutral drift")

    # short_term_alpha
    if spread > cfg.max_entry_spread_bps:
        return ("HOLD", f"spread {spread:.2f}bps > max {cfg.max_entry_spread_bps:.2f}bps")
    if abs(imb) < cfg.alpha_imbalance_threshold:
        return ("HOLD", f"imbalance {abs(imb):.3f} < {cfg.alpha_imbalance_threshold:.3f}")
    if imb > 0 and pred_ret >= cfg.alpha_pred_ret_threshold:
        return ("LONG", f"alpha long imbalance={imb:.3f} ret={pred_ret:.6f}")
    if imb < 0 and pred_ret <= -cfg.alpha_pred_ret_threshold:
        return ("SHORT", f"alpha short imbalance={imb:.3f} ret={pred_ret:.6f}")
    return ("HOLD", "model does not confirm imbalance direction")


def classify_direction(score: float, eps: float) -> tuple[str, float, float, float]:
    e = max(float(eps), 1e-8)
    z = float(score / e)
    logits = np.array([z, 0.0, -z], dtype=float)  # up, neutral, down
    logits = logits - float(np.max(logits))
    ex = np.exp(logits)
    probs = ex / np.sum(ex)
    p_up, p_neutral, p_down = float(probs[0]), float(probs[1]), float(probs[2])

    if score > e:
        label = "up"
    elif score < -e:
        label = "down"
    else:
        label = "neutral"
    return label, p_up, p_neutral, p_down


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
        self.input_dim = 1
        self.ret_mean = 0.0
        self.ret_std = 1.0
        self.label_classes = []
        self.label_eps = 0.0001

        if model_path.endswith(".joblib"):
            bundle = joblib.load(model_path)
            self.mode = str(bundle.get("model_type", "joblib"))
            self.model_obj = bundle["model"]
            self.feature_columns = list(bundle.get("feature_columns", FEATURE_COLUMNS))
            self.name = str(bundle.get("model_name", "PulseTreeV1"))
            self.horizon_sec = int(bundle.get("horizon_sec", 30))
            self.label_classes = list(bundle.get("label_classes", []))
            self.label_eps = float(bundle.get("label_eps", self.label_eps))
        elif model_path.endswith(".pt"):
            import torch
            from lstm_model import build_sequence_model

            artifact = torch.load(model_path, map_location="cpu")
            self.mode = str(artifact.get("model_type", "lstm"))
            self.name = str(artifact.get("model_name", f"Pulse{self.mode.title()}V1"))
            self.horizon_sec = int(artifact.get("horizon_sec", 30))
            self.seq_len = int(artifact.get("seq_len", 60))
            self.input_dim = int(artifact.get("input_dim", 1))
            self.ret_mean = float(artifact.get("ret_mean", 0.0))
            self.ret_std = float(artifact.get("ret_std", 1.0))
            self.lstm = build_sequence_model(
                model_type=self.mode,
                input_dim=self.input_dim,
                hidden_size=int(artifact.get("hidden_size", 64)),
                num_layers=int(artifact.get("num_layers", 2)),
                dropout=float(artifact.get("dropout", 0.1)),
                nhead=int(artifact.get("nhead", 4)),
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
                signal="neutral",
                detail="Need at least 8 points",
            )

        prices = [float(p.price) for p in points]
        last_price = float(prices[-1])
        arr_prices = np.asarray(prices, dtype=float)
        strategy_cfg = _parse_strategy_cfg(request)
        latest_book = _extract_latest_book(points)

        if self.lstm is not None:
            import torch

            if arr_prices.size < self.seq_len + 1:
                return pb2.PredictResponse(
                    model_name=self.name,
                    signal="neutral",
                    detail=f"Need at least {self.seq_len + 1} points for {self.mode}",
                )

            log_returns = np.log(np.maximum(arr_prices[1:], 1e-12) / np.maximum(arr_prices[:-1], 1e-12))
            seq = log_returns[-self.seq_len :].reshape(1, self.seq_len, 1)
            seq = (seq - self.ret_mean) / (self.ret_std if self.ret_std != 0 else 1.0)
            x_t = torch.from_numpy(seq.astype(np.float32))
            with torch.no_grad():
                pred_ret = float(self.lstm(x_t).item())
        else:
            try:
                x = latest_feature_vector_from_prices(arr_prices, self.feature_columns)
                classifier_probs = None
                if self.model_obj is not None:
                    if self.mode == "xgboost_classifier" and hasattr(self.model_obj, "predict_proba"):
                        raw_proba = self.model_obj.predict_proba(x.reshape(1, -1))[0]
                        class_names = self.label_classes or ["down", "neutral", "up"]
                        prob_by_label = {
                            str(class_names[i]): float(raw_proba[i])
                            for i in range(min(len(class_names), len(raw_proba)))
                        }
                        classifier_probs = {
                            "up": prob_by_label.get("up", 0.0),
                            "neutral": prob_by_label.get("neutral", 0.0),
                            "down": prob_by_label.get("down", 0.0),
                        }
                        pred_ret = (classifier_probs["up"] - classifier_probs["down"]) * self.label_eps
                    else:
                        pred_ret = float(self.model_obj.predict(x.reshape(1, -1))[0])
                else:
                    x_s = (x - self.mean) / self.scale
                    pred_ret = float(self.intercept + np.dot(x_s, self.weights))
            except ValueError as feature_err:
                return pb2.PredictResponse(
                    model_name=self.name,
                    signal="neutral",
                    last_price=last_price,
                    predicted_price=last_price,
                    predicted_return=0.0,
                    detail=f"feature extraction failed: {feature_err}",
                )
        pred_ret = float(np.clip(pred_ret, -0.05, 0.05))
        pred_price = last_price * (1.0 + pred_ret)
        strategy_signal, strategy_detail = decide_strategy_action(pred_ret, latest_book, strategy_cfg)
        if "classifier_probs" in locals() and classifier_probs is not None:
            p_up = classifier_probs["up"]
            p_neutral = classifier_probs["neutral"]
            p_down = classifier_probs["down"]
            label = max(classifier_probs, key=classifier_probs.get)
        else:
            label, p_up, p_neutral, p_down = classify_direction(
                score=pred_ret, eps=max(1e-8, strategy_cfg.alpha_pred_ret_threshold)
            )

        payload = {
            "score": pred_ret,
            "probability": {
                "up": p_up,
                "neutral": p_neutral,
                "down": p_down,
            },
            "strategy_action": strategy_signal,
            "strategy_detail": strategy_detail,
            "points": len(points),
            "model_mode": self.mode,
            "strategy_mode": strategy_cfg.mode,
            "hold_ms": strategy_cfg.hold_ms,
        }

        return pb2.PredictResponse(
            model_name=self.name,
            signal=label,
            last_price=last_price,
            predicted_price=pred_price,
            predicted_return=pred_ret,
            detail=json.dumps(payload, separators=(",", ":")),
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
