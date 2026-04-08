from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from common import FEATURE_COLUMNS, FeatureConfig, build_features, load_ticks, select_training_rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train linear prediction model")
    p.add_argument("--csv", required=True, help="Input ticks CSV")
    p.add_argument("--model-out", required=True, help="Output model JSON path")
    p.add_argument("--horizon-sec", type=int, default=30, help="Prediction horizon in seconds")
    p.add_argument("--alpha", type=float, default=1.0, help="Ridge alpha")
    p.add_argument("--test-size", type=float, default=0.2, help="Test split fraction")
    p.add_argument("--random-state", type=int, default=42, help="Random seed")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = FeatureConfig(horizon_sec=args.horizon_sec)

    df = load_ticks(args.csv)
    df_feat = build_features(df, cfg)
    ds = select_training_rows(df_feat)
    if len(ds) < 200:
        raise ValueError(f"Not enough rows for training: {len(ds)}")

    X = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["target_return"].to_numpy(dtype=float)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    model = Ridge(alpha=args.alpha, random_state=args.random_state)
    model.fit(X_train_s, y_train)

    pred = model.predict(X_test_s)
    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))

    exported = {
        "name": "PulseLinearV2",
        "horizon_sec": int(args.horizon_sec),
        "features": FEATURE_COLUMNS,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "intercept": float(model.intercept_),
        "weights": model.coef_.tolist(),
        "metrics": {
            "rmse": rmse,
            "mae": mae,
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
        },
    }

    out_path = Path(args.model_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(exported, indent=2), encoding="utf-8")

    print(f"Model saved: {out_path}")
    print(f"RMSE={rmse:.8f} MAE={mae:.8f}")


if __name__ == "__main__":
    main()
