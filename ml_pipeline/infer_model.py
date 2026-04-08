from __future__ import annotations

import argparse
import json

import numpy as np

from common import FEATURE_COLUMNS, FeatureConfig, build_features, load_ticks


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run inference from exported model JSON")
    p.add_argument("--csv", required=True, help="Input ticks CSV")
    p.add_argument("--model", required=True, help="Model JSON path")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    model = json.loads(open(args.model, "r", encoding="utf-8").read())

    cfg = FeatureConfig(horizon_sec=int(model["horizon_sec"]))
    df = load_ticks(args.csv)
    feat = build_features(df, cfg)
    feat = feat.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS + ["price"])
    if feat.empty:
        raise ValueError("Not enough data for inference")

    row = feat.iloc[-1]
    x = np.array([float(row[c]) for c in FEATURE_COLUMNS], dtype=float)
    mean = np.array(model["scaler_mean"], dtype=float)
    scale = np.array(model["scaler_scale"], dtype=float)
    w = np.array(model["weights"], dtype=float)
    b = float(model["intercept"])

    x_s = (x - mean) / scale
    pred_return = float(b + np.dot(x_s, w))
    pred_return = float(np.clip(pred_return, -0.05, 0.05))
    last_price = float(row["price"])
    pred_price = last_price * (1.0 + pred_return)

    signal = "BUY" if pred_price > last_price else "HOLD"
    result = {
        "signal": signal,
        "last_price": last_price,
        "predicted_price": pred_price,
        "predicted_return": pred_return,
        "horizon_sec": int(model["horizon_sec"]),
        "model_name": model.get("name", "unknown"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
