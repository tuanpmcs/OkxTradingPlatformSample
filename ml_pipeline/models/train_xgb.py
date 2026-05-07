from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

from ml_pipeline.features.common import (
    FEATURE_COLUMNS,
    FeatureConfig,
    attach_direction_label,
    build_features,
    load_ticks,
)


MODEL_TYPES = ("xgboost", "lightgbm", "lstm", "cnn", "transformer")
SEQUENCE_MODEL_TYPES = ("lstm", "cnn", "transformer")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train XGBoost/LightGBM/LSTM/CNN/Transformer price-return models")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Input raw ticks CSV")
    src.add_argument("--dataset-csv", help="Input labeled dataset CSV")
    p.add_argument("--model-out", help="Output model artifact when training a single model")
    p.add_argument("--model-out-dir", help="Output directory when training multiple models")
    p.add_argument("--model-types", default="xgboost,lstm,cnn,transformer")
    p.add_argument("--horizon-sec", type=int, default=30)
    p.add_argument("--label-eps", type=float, default=0.0001)
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--seq-len", type=int, default=60)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--hidden-size", type=int, default=64)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--metrics-out-csv")
    p.add_argument("--best-model-out")
    p.add_argument("--min-rows", type=int, default=500)
    p.add_argument("--task", choices=["auto", "regression", "classification"], default="auto")
    return p.parse_args()


def _parse_model_types(raw: str) -> list[str]:
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    bad = sorted(set(values) - set(MODEL_TYPES))
    if bad:
        raise ValueError(f"Unsupported model type(s): {bad}; expected {list(MODEL_TYPES)}")
    if not values:
        raise ValueError("No model types selected")
    return values


def _normalize_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "mid_price" not in out.columns and "price" in out.columns:
        out["mid_price"] = pd.to_numeric(out["price"], errors="coerce")
    if "spread" not in out.columns and {"best_ask_px", "best_bid_px"}.issubset(out.columns):
        out["spread"] = pd.to_numeric(out["best_ask_px"], errors="coerce") - pd.to_numeric(
            out["best_bid_px"], errors="coerce"
        )
    if "imbalance" not in out.columns:
        if "imbalance_l5" in out.columns:
            out["imbalance"] = pd.to_numeric(out["imbalance_l5"], errors="coerce")
        elif "imbalance_l1" in out.columns:
            out["imbalance"] = pd.to_numeric(out["imbalance_l1"], errors="coerce")
    if "trade_volume" not in out.columns and {"buy_volume", "sell_volume"}.issubset(out.columns):
        out["trade_volume"] = pd.to_numeric(out["buy_volume"], errors="coerce") + pd.to_numeric(
            out["sell_volume"], errors="coerce"
        )
    if "trade_imbalance" not in out.columns and {"buy_volume", "sell_volume"}.issubset(out.columns):
        den = pd.to_numeric(out["buy_volume"], errors="coerce") + pd.to_numeric(out["sell_volume"], errors="coerce")
        num = pd.to_numeric(out["buy_volume"], errors="coerce") - pd.to_numeric(out["sell_volume"], errors="coerce")
        out["trade_imbalance"] = np.where(np.abs(den) > 1e-12, num / den, 0.0)
    if "rel_spread" not in out.columns and {"spread", "mid_price"}.issubset(out.columns):
        mid = pd.to_numeric(out["mid_price"], errors="coerce")
        spread = pd.to_numeric(out["spread"], errors="coerce")
        out["rel_spread"] = np.where(np.abs(mid) > 1e-12, spread / mid, 0.0)
    if "microprice" not in out.columns and "mid_price" in out.columns:
        out["microprice"] = pd.to_numeric(out["mid_price"], errors="coerce")
    if "imbalance_l1" not in out.columns and "imbalance" in out.columns:
        out["imbalance_l1"] = pd.to_numeric(out["imbalance"], errors="coerce")
    if "imbalance_l5" not in out.columns and "imbalance" in out.columns:
        out["imbalance_l5"] = pd.to_numeric(out["imbalance"], errors="coerce")
    if "bid_vol_l5" not in out.columns and "best_bid_sz" in out.columns:
        out["bid_vol_l5"] = pd.to_numeric(out["best_bid_sz"], errors="coerce")
    if "ask_vol_l5" not in out.columns and "best_ask_sz" in out.columns:
        out["ask_vol_l5"] = pd.to_numeric(out["best_ask_sz"], errors="coerce")
    if "weighted_bid_depth" not in out.columns and "bid_vol_l5" in out.columns:
        out["weighted_bid_depth"] = pd.to_numeric(out["bid_vol_l5"], errors="coerce")
    if "weighted_ask_depth" not in out.columns and "ask_vol_l5" in out.columns:
        out["weighted_ask_depth"] = pd.to_numeric(out["ask_vol_l5"], errors="coerce")
    defaults = {
        "trade_count": 0.0,
        "trade_volume": 0.0,
        "trade_imbalance": 0.0,
        "trade_vwap_dev_from_mid": 0.0,
        "delta_mid_price": 0.0,
        "delta_spread": 0.0,
        "delta_imbalance_l5": 0.0,
        "is_snapshot": 0.0,
        "is_update": 1.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


def _load_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    if args.dataset_csv:
        ds = _normalize_feature_columns(pd.read_csv(args.dataset_csv))
        regression_target = "target_exec_return" if "target_exec_return" in ds.columns else "target_return"
        if regression_target in ds.columns:
            required = set(FEATURE_COLUMNS + [regression_target, "price", "target_price", "target_ts", "ts"])
            missing = sorted(required - set(ds.columns))
            if missing:
                raise ValueError(f"dataset CSV missing required columns: {missing}")
            cleaned = ds.replace([np.inf, -np.inf], np.nan).dropna(
                subset=FEATURE_COLUMNS + [regression_target, "price", "target_price", "target_ts", "ts"]
            )
            cleaned["target_return"] = cleaned[regression_target]
            return cleaned.reset_index(drop=True), "regression"
        if "label" in ds.columns:
            required = set(FEATURE_COLUMNS + ["label"])
            missing = sorted(required - set(ds.columns))
            if missing:
                raise ValueError(f"feature+label dataset missing required columns: {missing}")
            cleaned = ds.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS + ["label"]).reset_index(drop=True)
            cleaned["label"] = cleaned["label"].astype(str).str.strip().str.lower()
            return cleaned, "classification"
        raise ValueError("dataset CSV must contain either target_return or label")

    cfg = FeatureConfig(horizon_sec=args.horizon_sec)
    labeled = attach_direction_label(build_features(load_ticks(args.csv), cfg), eps=args.label_eps)
    if "target_exec_return" in labeled.columns:
        labeled["target_return"] = labeled["target_exec_return"]
    cols = FEATURE_COLUMNS + ["target_return", "label", "price", "target_price", "target_ts", "ts"]
    return labeled[cols].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True), "regression"


def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
    }


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    denom = np.maximum(np.abs(y_true), 1e-8)
    mape = float(np.mean(np.abs((y_true - y_pred) / denom)))
    dir_acc = float(np.mean(np.sign(y_true) == np.sign(y_pred)))
    corr = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else 0.0
    if not np.isfinite(corr):
        corr = 0.0
    return {"mae": mae, "rmse": rmse, "mape": mape, "directional_accuracy": dir_acc, "corr": corr}


def _make_sequence_dataset(ds: pd.DataFrame, seq_len: int) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    prices = ds["price"].to_numpy(dtype=float)
    target_returns = ds["target_return"].to_numpy(dtype=float)
    if len(prices) < seq_len + 2:
        raise ValueError(f"Need at least {seq_len + 2} rows for sequence training, got {len(prices)}")

    log_returns = np.log(np.maximum(prices[1:], 1e-12) / np.maximum(prices[:-1], 1e-12))
    samples: list[np.ndarray] = []
    targets: list[float] = []
    for row_idx in range(seq_len, len(ds)):
        seq = log_returns[row_idx - seq_len : row_idx]
        if len(seq) == seq_len and np.isfinite(seq).all() and np.isfinite(target_returns[row_idx]):
            samples.append(seq.reshape(seq_len, 1))
            targets.append(float(target_returns[row_idx]))
    if not samples:
        raise ValueError("No valid sequence samples could be built")

    x = np.asarray(samples, dtype=np.float32)
    y = np.asarray(targets, dtype=np.float32)
    ret_mean = float(x.mean())
    ret_std = float(x.std() or 1.0)
    return (x - ret_mean) / ret_std, y, {"ret_mean": ret_mean, "ret_std": ret_std}


def _resolve_output_path(args: argparse.Namespace, model_type: str, count: int) -> Path:
    if count == 1 and args.model_out:
        return Path(args.model_out)
    out_dir = Path(args.model_out_dir or (Path(args.model_out).parent if args.model_out else "models"))
    suffix = ".joblib" if model_type in {"xgboost", "lightgbm"} else ".pt"
    return out_dir / f"pulse_{model_type}_v1{suffix}"


def _extract_label_metadata(ds: pd.DataFrame, default_eps: float) -> dict[str, Any]:
    label_classes = sorted(ds["label"].dropna().astype(str).unique().tolist()) if "label" in ds.columns else []
    label_eps = float(default_eps)
    if "label_eps" in ds.columns:
        eps = pd.to_numeric(ds["label_eps"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if not eps.empty:
            label_eps = float(np.median(eps.to_numpy(dtype=float)))
    return {"label_classes": label_classes, "label_eps": label_eps}


def _return_threshold_metadata(ds: pd.DataFrame, default_eps: float) -> float:
    if "label_eps" in ds.columns and "mid_price" in ds.columns:
        eps = pd.to_numeric(ds["label_eps"], errors="coerce")
        mid = pd.to_numeric(ds["mid_price"], errors="coerce")
        ret_eps = (eps / mid).replace([np.inf, -np.inf], np.nan).dropna()
        ret_eps = ret_eps[ret_eps >= 0.0]
        if not ret_eps.empty:
            return float(np.median(ret_eps.to_numpy(dtype=float)))
    return float(default_eps)


def _train_xgboost_model(ds: pd.DataFrame, args: argparse.Namespace) -> tuple[Any, dict[str, float]]:
    from xgboost import XGBRegressor
    from sklearn.isotonic import IsotonicRegression

    x = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["target_return"].to_numpy(dtype=float)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
    calib_rows = max(1, int(len(x_train) * 0.2))
    fit_rows = max(1, len(x_train) - calib_rows)
    x_fit, y_fit = x_train[:fit_rows], y_train[:fit_rows]
    x_calib, y_calib = x_train[fit_rows:], y_train[fit_rows:]
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        min_child_weight=20,
        reg_lambda=1.0,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=args.random_state,
        n_jobs=1,
    )
    model.fit(x_fit, y_fit)
    calibrator = None
    if len(x_calib) >= 100:
        calib_pred = model.predict(x_calib)
        if float(np.std(calib_pred)) > 1e-12:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(calib_pred, y_calib)
    pred = model.predict(x_test)
    if calibrator is not None:
        pred = calibrator.predict(pred)
    metrics = _metrics(y_test, pred)
    metrics.update({"train_rows": int(len(x_train)), "fit_rows": int(len(x_fit)), "calib_rows": int(len(x_calib)), "test_rows": int(len(x_test))})
    return {"model": model, "return_calibrator": calibrator}, metrics


def _train_lightgbm_model(ds: pd.DataFrame, args: argparse.Namespace) -> tuple[Any, dict[str, float]]:
    from lightgbm import LGBMRegressor
    from sklearn.isotonic import IsotonicRegression

    x = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["target_return"].to_numpy(dtype=float)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
    calib_rows = max(1, int(len(x_train) * 0.2))
    fit_rows = max(1, len(x_train) - calib_rows)
    x_fit, y_fit = x_train[:fit_rows], y_train[:fit_rows]
    x_calib, y_calib = x_train[fit_rows:], y_train[fit_rows:]
    model = LGBMRegressor(
        objective="regression",
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=31,
        min_child_samples=80,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        random_state=args.random_state,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(x_fit, y_fit)
    calibrator = None
    if len(x_calib) >= 100:
        calib_pred = model.predict(x_calib)
        if float(np.std(calib_pred)) > 1e-12:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(calib_pred, y_calib)
    pred = model.predict(x_test)
    if calibrator is not None:
        pred = calibrator.predict(pred)
    metrics = _metrics(y_test, pred)
    metrics.update({"train_rows": int(len(x_train)), "fit_rows": int(len(x_fit)), "calib_rows": int(len(x_calib)), "test_rows": int(len(x_test))})
    return {"model": model, "return_calibrator": calibrator}, metrics


def _train_xgboost_classifier(ds: pd.DataFrame, args: argparse.Namespace) -> tuple[Any, dict[str, float], list[str]]:
    from xgboost import XGBClassifier

    ordered_labels = [label for label in ("down", "neutral", "up") if label in set(ds["label"].tolist())]
    if not ordered_labels:
        ordered_labels = sorted(ds["label"].astype(str).unique().tolist())
    label_to_id = {label: idx for idx, label in enumerate(ordered_labels)}

    x = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["label"].map(label_to_id).to_numpy(dtype=int)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
    model = XGBClassifier(
        objective="multi:softprob",
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        min_child_weight=20,
        reg_lambda=1.0,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=args.random_state,
        n_jobs=1,
        num_class=len(ordered_labels),
    )
    model.fit(x_train, y_train)
    pred = model.predict(x_test)
    metrics = _classification_metrics(y_test, pred)
    metrics.update({"train_rows": int(len(x_train)), "test_rows": int(len(x_test))})
    return model, metrics, ordered_labels


def _train_lightgbm_classifier(ds: pd.DataFrame, args: argparse.Namespace) -> tuple[Any, dict[str, float], list[str]]:
    from lightgbm import LGBMClassifier

    ordered_labels = [label for label in ("down", "neutral", "up") if label in set(ds["label"].tolist())]
    if not ordered_labels:
        ordered_labels = sorted(ds["label"].astype(str).unique().tolist())
    label_to_id = {label: idx for idx, label in enumerate(ordered_labels)}

    x = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["label"].map(label_to_id).to_numpy(dtype=int)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
    model = LGBMClassifier(
        objective="multiclass",
        num_class=len(ordered_labels),
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=31,
        min_child_samples=80,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        class_weight="balanced",
        random_state=args.random_state,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(x_train, y_train)
    pred = model.predict(x_test)
    metrics = _classification_metrics(y_test, pred)
    metrics.update({"train_rows": int(len(x_train)), "test_rows": int(len(x_test))})
    return model, metrics, ordered_labels


def _train_sequence_model(
    model_type: str,
    x_train: np.ndarray,
    x_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    args: argparse.Namespace,
) -> tuple[Any, dict[str, float]]:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from ml_pipeline.models.lstm_model import build_sequence_model

    torch.manual_seed(int(args.random_state))
    model = build_sequence_model(
        model_type=model_type,
        input_dim=int(x_train.shape[-1]),
        hidden_size=int(args.hidden_size),
        num_layers=int(args.num_layers),
        dropout=float(args.dropout),
        nhead=4,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(args.learning_rate), weight_decay=1e-4)
    loss_fn = nn.SmoothL1Loss()
    loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
        batch_size=int(args.batch_size),
        shuffle=True,
    )

    model.train()
    for epoch in range(1, int(args.epochs) + 1):
        losses: list[float] = []
        for xb, yb in loader:
            optimizer.zero_grad(set_to_none=True)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            losses.append(float(loss.item()))
        if epoch == 1 or epoch == int(args.epochs) or epoch % 5 == 0:
            print(f"{model_type} epoch={epoch} train_loss={np.mean(losses):.8f}")

    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(x_test)).numpy()
    metrics = _metrics(y_test, pred)
    metrics.update({"train_rows": int(len(x_train)), "test_rows": int(len(x_test))})
    return model, metrics


def main() -> int:
    args = parse_args()
    model_types = _parse_model_types(args.model_types)
    ds, inferred_task = _load_dataset(args)
    task = inferred_task if args.task == "auto" else args.task
    if task != inferred_task:
        raise ValueError(f"Requested task={task} but dataset implies task={inferred_task}")

    min_rows = max(int(args.min_rows), int(args.seq_len) + 2)
    if len(ds) < min_rows:
        raise ValueError(f"Need at least {min_rows} rows, got {len(ds)}")

    label_meta = _extract_label_metadata(ds, default_eps=float(args.label_eps))
    return_label_eps = _return_threshold_metadata(ds, default_eps=float(args.label_eps))
    if task == "classification":
        skipped = [m for m in model_types if m not in {"xgboost", "lightgbm"}]
        if skipped:
            print(f"Skipping unsupported model types for classification task: {skipped}")
        model_types = [m for m in model_types if m in {"xgboost", "lightgbm"}]
        if not model_types:
            raise ValueError("Classification task currently supports only xgboost and lightgbm")

    sequence_cache: tuple[np.ndarray, np.ndarray, dict[str, float]] | None = None
    trained_runs: list[dict[str, Any]] = []
    for model_type in model_types:
        out = _resolve_output_path(args, model_type, len(model_types))
        out.parent.mkdir(parents=True, exist_ok=True)

        if model_type in {"xgboost", "lightgbm"}:
            if task == "classification":
                if model_type == "xgboost":
                    model, metrics, class_names = _train_xgboost_classifier(ds, args)
                    artifact_type = "xgboost_classifier"
                    artifact_name = "PulseXGBoostClassifierV1"
                else:
                    model, metrics, class_names = _train_lightgbm_classifier(ds, args)
                    artifact_type = "lightgbm_classifier"
                    artifact_name = "PulseLightGBMClassifierV1"
                artifact = {
                    "model_type": artifact_type,
                    "model_name": artifact_name,
                    "horizon_sec": int(args.horizon_sec),
                    "feature_columns": FEATURE_COLUMNS,
                    "label_classes": class_names,
                    "label_eps": return_label_eps,
                    "model": model,
                    "metrics": metrics,
                }
            else:
                if model_type == "xgboost":
                    model_bundle, metrics = _train_xgboost_model(ds, args)
                    artifact_type = "xgboost_regressor"
                    artifact_name = "PulseXGBoostV1"
                else:
                    model_bundle, metrics = _train_lightgbm_model(ds, args)
                    artifact_type = "lightgbm_regressor"
                    artifact_name = "PulseLightGBMV1"
                artifact = {
                    "model_type": artifact_type,
                    "model_name": artifact_name,
                    "horizon_sec": int(args.horizon_sec),
                    "feature_columns": FEATURE_COLUMNS,
                    "label_classes": label_meta["label_classes"],
                    "label_eps": return_label_eps,
                    "model": model_bundle["model"],
                    "return_calibrator": model_bundle["return_calibrator"],
                    "prediction_target": "signed_executable_return",
                    "metrics": metrics,
                }
            joblib.dump(artifact, out)
        else:
            import torch

            if sequence_cache is None:
                sequence_cache = _make_sequence_dataset(ds, seq_len=int(args.seq_len))
            x, y, norm = sequence_cache
            x_train, x_test, y_train, y_test = train_test_split(
                x, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
            )
            model, metrics = _train_sequence_model(model_type, x_train, x_test, y_train, y_test, args)
            artifact = {
                "model_type": model_type,
                "model_name": f"Pulse{model_type.upper()}V1",
                "horizon_sec": int(args.horizon_sec),
                "label_classes": label_meta["label_classes"],
                "label_eps": return_label_eps,
                "seq_len": int(args.seq_len),
                "input_dim": int(x.shape[-1]),
                "hidden_size": int(args.hidden_size),
                "num_layers": int(args.num_layers),
                "dropout": float(args.dropout),
                "nhead": 4,
                "ret_mean": norm["ret_mean"],
                "ret_std": norm["ret_std"],
                "state_dict": model.state_dict(),
                "metrics": metrics,
            }
            torch.save(artifact, out)

        trained_runs.append({"model": model_type, "artifact_path": str(out), **metrics})
        print(f"Saved {model_type.upper()} model: {out}")

    summary_df = pd.DataFrame(trained_runs)
    summary_df = (
        summary_df.sort_values(["accuracy", "macro_f1"], ascending=False)
        if task == "classification"
        else summary_df.sort_values("rmse")
    ).reset_index(drop=True)
    if args.metrics_out_csv:
        metrics_out = Path(args.metrics_out_csv)
        metrics_out.parent.mkdir(parents=True, exist_ok=True)
        summary_df.to_csv(metrics_out, index=False)
        print(f"Saved metrics summary: {metrics_out}")

    best = summary_df.iloc[0]
    print(f"Best model: {best['model']} -> {best['artifact_path']}")
    if args.best_model_out:
        best_model_out = Path(args.best_model_out)
        best_model_out.parent.mkdir(parents=True, exist_ok=True)
        best_artifact = Path(str(best["artifact_path"]))
        if best_artifact.resolve() != best_model_out.resolve():
            shutil.copy2(best_artifact, best_model_out)
            print(f"Copied best artifact: {best_model_out}")
        else:
            print(f"Best artifact already at requested path: {best_model_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
