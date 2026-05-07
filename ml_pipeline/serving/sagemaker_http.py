from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import perf_counter_ns
from typing import Any

import numpy as np

from ml_pipeline.serving.app import PredictionService, log_inference, signal_from_return


class InferenceEngine:
    def __init__(self, model_path: str, model_dir: str = "") -> None:
        self._service = PredictionService(model_path=model_path, model_dir=model_dir)

    @staticmethod
    def _to_points(payload: dict[str, Any]) -> list[dict[str, float]]:
        points_raw = payload.get("points")
        if isinstance(points_raw, list) and points_raw:
            out: list[dict[str, float]] = []
            for idx, point in enumerate(points_raw):
                if not isinstance(point, dict) or "price" not in point:
                    raise ValueError(f"points[{idx}] must be an object with price")
                out.append(
                    {
                        "ts": int(point.get("ts", idx + 1)),
                        "price": float(point["price"]),
                        "bid_px": float(point.get("bid_px", point.get("bidPx", 0.0)) or 0.0),
                        "ask_px": float(point.get("ask_px", point.get("askPx", 0.0)) or 0.0),
                        "bid_sz": float(point.get("bid_sz", point.get("bidSz", 0.0)) or 0.0),
                        "ask_sz": float(point.get("ask_sz", point.get("askSz", 0.0)) or 0.0),
                    }
                )
            return out

        prices_raw = payload.get("prices")
        if isinstance(prices_raw, list) and prices_raw:
            return [{"ts": i + 1, "price": float(px)} for i, px in enumerate(prices_raw)]

        raise ValueError("Payload must include non-empty points or prices")

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_ns = perf_counter_ns()
        points = self._to_points(payload)
        prices = np.fromiter((float(p["price"]) for p in points), dtype=np.float64, count=len(points))

        requested_model_type = str(payload.get("model_type", payload.get("modelType", "")) or "")
        selected_alias, model = self._service._get_model(requested_model_type)
        log_inference(
            "http_predict "
            f"requested={requested_model_type or '<default>'} "
            f"selected={selected_alias} "
            f"model_name={model.name} "
            f"path={model.path.name} "
            f"points={int(prices.size)} "
            f"symbol={payload.get('symbol', '')} "
            f"channel={payload.get('channel', '')}"
        )

        if prices.size < 8:
            last_price = float(prices[-1]) if prices.size > 0 else 0.0
            return {
                "model_name": model.name,
                "signal": "HOLD",
                "last_price": last_price,
                "predicted_price": last_price,
                "predicted_return": 0.0,
                "detail": "Need at least 8 points",
            }

        last_price = float(prices[-1])
        try:
            pred_ret = model.predict_return(prices, points)
        except ValueError as err:
            return {
                "model_name": model.name,
                "signal": "HOLD",
                "last_price": last_price,
                "predicted_price": last_price,
                "predicted_return": 0.0,
                "detail": str(err),
            }

        pred_ret = float(np.clip(pred_ret, -0.05, 0.05))
        pred_price = last_price * (1.0 + pred_ret)
        signal = signal_from_return(pred_ret, model.label_eps)
        detail = json.dumps(
            {
                "mode": model.mode,
                "alias": selected_alias,
                "points": int(prices.size),
                "horizon_sec": int(
                    payload.get("horizon_sec", payload.get("horizonSec", model.horizon_sec)) or model.horizon_sec
                ),
                "infer_us": int((perf_counter_ns() - started_ns) / 1000),
            },
            separators=(",", ":"),
        )

        return {
            "model_name": model.name,
            "signal": signal,
            "last_price": last_price,
            "predicted_price": pred_price,
            "predicted_return": pred_ret,
            "detail": detail,
        }


class SageMakerHandler(BaseHTTPRequestHandler):
    engine: InferenceEngine

    def _send_common_headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_common_headers("application/json", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/ping", "/health"}:
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers("text/plain; charset=utf-8", 0)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/invocations", "/predict"}:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len <= 0:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "empty request body"})
            return

        body = self.rfile.read(content_len)
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            log_inference(
                "http_request "
                f"path={self.path} "
                f"origin={self.headers.get('Origin', '')} "
                f"modelType={payload.get('modelType', payload.get('model_type', ''))} "
                f"symbol={payload.get('symbol', '')} "
                f"channel={payload.get('channel', '')} "
                f"points={len(payload.get('points', [])) if isinstance(payload.get('points'), list) else 0}"
            )
            result = self.engine.predict(payload)
        except Exception as err:  # pragma: no cover
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            return

        self._write_json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SageMaker-compatible HTTP inference server")
    p.add_argument(
        "--model",
        default=os.getenv("MODEL_PATH", "models/pulse_xgboost_v1.joblib"),
        help="Path to model artifact (.json/.joblib/.artifact/.pt)",
    )
    p.add_argument(
        "--model-dir",
        default=os.getenv("MODEL_DIR_PATH", ""),
        help="Optional model directory for fallback model discovery",
    )
    p.add_argument("--host", default=os.getenv("SM_HTTP_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("SM_HTTP_PORT", "8080")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    SageMakerHandler.engine = InferenceEngine(model_path=args.model, model_dir=args.model_dir)
    server = ThreadingHTTPServer((args.host, args.port), SageMakerHandler)
    print(f"SageMaker HTTP inference listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
