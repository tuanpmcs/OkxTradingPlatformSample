from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

from common import FEATURE_COLUMNS, FeatureConfig, build_features, load_ticks, select_training_rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train better (tree-based) prediction model")
    p.add_argument("--csv", required=True, help="Input ticks CSV")
    p.add_argument("--model-out", required=True, help="Output model artifact (.joblib)")
    p.add_argument("--horizon-sec", type=int, default=30, help="Prediction horizon in seconds")
    p.add_argument("--test-size", type=float, default=0.2, help="Test split fraction")
    p.add_argument("--random-state", type=int, default=42, help="Random seed")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = FeatureConfig(horizon_sec=args.horizon_sec)
    df = load_ticks(args.csv)
    ds = select_training_rows(build_features(df, cfg))
    if len(ds) < 500:
        raise ValueError(f"Need at least 500 rows, got {len(ds)}")

    X = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["target_return"].to_numpy(dtype=float)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )

    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=500,
        max_depth=6,
        min_samples_leaf=25,
        l2_regularization=0.01,
        random_state=args.random_state,
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)

    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))

    bundle = {
        "model_type": "hgbt",
        "model_name": "PulseTreeV1",
        "horizon_sec": int(args.horizon_sec),
        "feature_columns": FEATURE_COLUMNS,
        "model": model,
        "metrics": {
            "rmse": rmse,
            "mae": mae,
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
        },
    }

    out = Path(args.model_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out)
    print(f"Saved better model: {out}")
    print(f"RMSE={rmse:.8f} MAE={mae:.8f}")


if __name__ == "__main__":
    main()
