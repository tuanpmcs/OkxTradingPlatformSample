from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ml_pipeline.features.common import FEATURE_COLUMNS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate a trained model with executable bid/ask PnL metrics")
    p.add_argument("--dataset-csv", required=True, help="Labeled feature dataset from ml_pipeline.data.build_labels")
    p.add_argument("--model", required=True, help="Model artifact (.joblib/.artifact)")
    p.add_argument("--out-json", help="Optional JSON metrics output path")
    p.add_argument("--pred-out-csv", help="Optional prediction CSV output path")
    p.add_argument("--pred-threshold", type=float, default=0.0, help="Minimum absolute predicted return to trade")
    p.add_argument("--fee-per-trade", type=float, default=0.0, help="Flat PnL cost charged on non-flat predictions")
    return p.parse_args()


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err * err)))
    dir_acc = float(np.mean(np.sign(y_true) == np.sign(y_pred))) if len(y_true) else 0.0
    corr = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else 0.0
    if not np.isfinite(corr):
        corr = 0.0
    return {
        "mae": mae,
        "rmse": rmse,
        "directional_accuracy": dir_acc,
        "corr": corr,
    }


def _max_drawdown(cumulative: np.ndarray) -> float:
    if cumulative.size == 0:
        return 0.0
    peak = np.maximum.accumulate(cumulative)
    dd = peak - cumulative
    return float(np.max(dd))


def _trading_metrics(ds: pd.DataFrame, pred: np.ndarray, threshold: float, fee_per_trade: float) -> tuple[pd.DataFrame, dict[str, float]]:
    out = ds.copy()
    out["pred_return"] = pred
    out["pred_signal"] = np.where(pred > threshold, "up", np.where(pred < -threshold, "down", "neutral"))

    if {"buy_pnl", "sell_pnl"}.issubset(out.columns):
        buy_pnl = pd.to_numeric(out["buy_pnl"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        sell_pnl = pd.to_numeric(out["sell_pnl"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        trade_pnl = np.where(out["pred_signal"] == "up", buy_pnl, np.where(out["pred_signal"] == "down", sell_pnl, 0.0))
    elif "target_return" in out.columns:
        target = pd.to_numeric(out["target_return"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        price = pd.to_numeric(out.get("price", 1.0), errors="coerce").fillna(1.0).to_numpy(dtype=float)
        trade_pnl = np.where(out["pred_signal"] == "up", target * price, np.where(out["pred_signal"] == "down", -target * price, 0.0))
    else:
        raise ValueError("Dataset must include buy_pnl/sell_pnl or target_return for trading evaluation")

    traded = out["pred_signal"].to_numpy() != "neutral"
    trade_pnl = trade_pnl - np.where(traded, float(fee_per_trade), 0.0)
    out["strategy_pnl"] = trade_pnl
    out["strategy_cum_pnl"] = np.cumsum(trade_pnl)

    realized = trade_pnl[traded]
    metrics = {
        "rows": int(len(out)),
        "trades": int(np.sum(traded)),
        "coverage": float(np.mean(traded)) if len(out) else 0.0,
        "total_pnl": float(np.sum(trade_pnl)),
        "avg_pnl_per_row": float(np.mean(trade_pnl)) if len(out) else 0.0,
        "avg_pnl_per_trade": float(np.mean(realized)) if realized.size else 0.0,
        "win_rate": float(np.mean(realized > 0.0)) if realized.size else 0.0,
        "max_drawdown": _max_drawdown(out["strategy_cum_pnl"].to_numpy(dtype=float)),
    }

    if "label" in out.columns:
        label = out["label"].astype(str).str.lower().to_numpy()
        metrics["signal_label_accuracy"] = float(np.mean(out["pred_signal"].to_numpy() == label)) if len(out) else 0.0

    return out, metrics


def _load_model(path: str) -> tuple[Any, list[str], str, Any]:
    artifact = joblib.load(path)
    if isinstance(artifact, dict) and "model" in artifact:
        features = list(artifact.get("feature_columns") or artifact.get("features") or FEATURE_COLUMNS)
        return (
            artifact["model"],
            features,
            str(artifact.get("model_name", artifact.get("model_type", Path(path).stem))),
            artifact.get("return_calibrator"),
        )
    return artifact, FEATURE_COLUMNS, Path(path).stem, None


def _predict(model: Any, x: np.ndarray, label_eps: float = 0.0001) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)
        if proba.ndim == 2 and proba.shape[1] >= 3:
            return (proba[:, -1] - proba[:, 0]) * label_eps
    return np.asarray(model.predict(x), dtype=float)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    ds = pd.read_csv(args.dataset_csv)
    model, features, model_name, return_calibrator = _load_model(args.model)

    missing = sorted(set(features) - set(ds.columns))
    if missing:
        raise ValueError(f"Dataset missing model feature columns: {missing}")

    target_col = "target_exec_return" if "target_exec_return" in ds.columns else "target_return"
    if target_col not in ds.columns:
        raise ValueError("Dataset must contain target_exec_return or target_return")

    clean = ds.replace([np.inf, -np.inf], np.nan).dropna(subset=features + [target_col]).reset_index(drop=True)
    if clean.empty:
        raise ValueError("No valid rows after dropping missing features/target")

    x = clean[features].to_numpy(dtype=float)
    y = clean[target_col].to_numpy(dtype=float)
    pred = _predict(model, x)
    if return_calibrator is not None:
        pred = np.asarray(return_calibrator.predict(pred), dtype=float)

    pred_df, pnl_metrics = _trading_metrics(clean, pred, float(args.pred_threshold), float(args.fee_per_trade))
    metrics: dict[str, Any] = {
        "model_name": model_name,
        "dataset_csv": args.dataset_csv,
        "model_path": args.model,
        "target_col": target_col,
        "feature_count": len(features),
        "features": features,
        "regression": _regression_metrics(y, pred),
        "trading": pnl_metrics,
    }

    if args.pred_out_csv:
        pred_out = Path(args.pred_out_csv)
        pred_out.parent.mkdir(parents=True, exist_ok=True)
        pred_df.to_csv(pred_out, index=False)
        metrics["pred_out_csv"] = str(pred_out)

    if args.out_json:
        out_json = Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")

    return metrics


def main() -> int:
    metrics = evaluate(parse_args())
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
