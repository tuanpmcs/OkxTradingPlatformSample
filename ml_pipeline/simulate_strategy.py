from __future__ import annotations

import argparse
import json

import numpy as np

from common import FEATURE_COLUMNS, FeatureConfig, build_features, load_ticks


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulate BUY->SELL strategy from model")
    p.add_argument("--csv", required=True, help="Input ticks CSV")
    p.add_argument("--model", required=True, help="Model JSON path")
    p.add_argument("--capital", type=float, default=5000.0, help="Capital per trade")
    p.add_argument("--hold-sec", type=int, default=30, help="Hold duration in seconds")
    p.add_argument("--threshold", type=float, default=0.0002, help="Min predicted return to BUY")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    model = json.loads(open(args.model, "r", encoding="utf-8").read())
    cfg = FeatureConfig(horizon_sec=args.hold_sec)

    df = load_ticks(args.csv)
    feat = build_features(df, cfg)
    feat = feat.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS + ["price", "target_price"])
    if feat.empty:
        raise ValueError("Not enough rows for simulation")

    mean = np.array(model["scaler_mean"], dtype=float)
    scale = np.array(model["scaler_scale"], dtype=float)
    w = np.array(model["weights"], dtype=float)
    b = float(model["intercept"])

    trade_pnls = []
    for _, row in feat.iterrows():
        x = np.array([float(row[c]) for c in FEATURE_COLUMNS], dtype=float)
        x_s = (x - mean) / scale
        pred_ret = float(b + np.dot(x_s, w))
        pred_ret = float(np.clip(pred_ret, -0.05, 0.05))
        if pred_ret <= args.threshold:
            continue

        entry = float(row["price"])
        exit_px = float(row["target_price"])
        qty = float(args.capital / entry)
        pnl = (exit_px - entry) * qty
        trade_pnls.append(pnl)

    if not trade_pnls:
        print(json.dumps({"trades": 0, "message": "No BUY trades generated"}, indent=2))
        return

    arr = np.array(trade_pnls, dtype=float)
    result = {
        "trades": int(len(arr)),
        "win_rate": float((arr > 0).mean()),
        "avg_pnl": float(arr.mean()),
        "median_pnl": float(np.median(arr)),
        "total_pnl": float(arr.sum()),
        "max_draw_trade": float(arr.min()),
        "max_gain_trade": float(arr.max()),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
