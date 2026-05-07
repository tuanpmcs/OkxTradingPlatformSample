from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.dummy import DummyRegressor

from ml_pipeline.features.common import FEATURE_COLUMNS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create a deterministic smoke-test model artifact")
    p.add_argument("--model-out", default="models/pulse_xgboost_v1.joblib")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.model_out)
    out.parent.mkdir(parents=True, exist_ok=True)

    x = np.zeros((8, len(FEATURE_COLUMNS)), dtype=float)
    y = np.zeros(8, dtype=float)
    model = DummyRegressor(strategy="constant", constant=0.0)
    model.fit(x, y)

    joblib.dump(
        {
            "model_type": "xgboost_regressor",
            "model_name": "PulseBootstrapSmokeModel",
            "horizon_sec": 30,
            "feature_columns": FEATURE_COLUMNS,
            "label_classes": [],
            "label_eps": 0.0001,
            "model": model,
            "metrics": {"note": "smoke-test artifact; replace with a trained model before production trading"},
        },
        out,
    )
    print(f"Saved bootstrap smoke model: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

