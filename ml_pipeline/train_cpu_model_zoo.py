from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge, SGDClassifier, SGDRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

from common import FEATURE_COLUMNS


CPU_MODEL_TYPES = (
    "xgboost",
    "lightgbm",
    "catboost",
    "lstm",
    "cnn",
    "transformer_lite",
    "ridge",
    "logistic",
    "sgd_regressor",
    "sgd_classifier",
    "hybrid_gate",
)

SEQUENCE_TYPES = ("lstm", "cnn", "transformer_lite")

PREFERRED_FEATURES = [
    "mid_price",
    "spread",
    "imbalance_l5",
    "imbalance",
    "trade_volume",
    "trade_imbalance",
    "microprice",
    "rel_spread",
    "delta_mid_price",
    "delta_spread",
    "delta_imbalance_l5",
    "trade_vwap_dev_from_mid",
    "weighted_bid_depth",
    "weighted_ask_depth",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train CPU-friendly model zoo for short-horizon trading.")
    p.add_argument("--dataset-csv", required=True, help="Input labeled dataset CSV")
    p.add_argument("--out-dir", required=True, help="Output model directory")
    p.add_argument("--metrics-out-csv", required=True, help="Output metrics CSV")
    p.add_argument("--pred-out-csv", help="Optional output prediction CSV for backtest")
    p.add_argument(
        "--model-types",
        default="xgboost,lightgbm,catboost,lstm,cnn,transformer_lite,ridge,logistic,sgd_regressor,sgd_classifier,hybrid_gate",
        help=f"Comma-separated model list: {','.join(CPU_MODEL_TYPES)}",
    )
    p.add_argument("--task", choices=["auto", "regression", "classification"], default="auto")
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--min-rows", type=int, default=3000)
    p.add_argument("--seq-len", type=int, default=64)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--hidden-size", type=int, default=48)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--learning-rate", type=float, default=1e-3)
    p.add_argument("--max-seq-samples", type=int, default=120000, help="Cap sequence samples for CPU speed")
    p.add_argument("--hybrid-gate-threshold", type=float, default=0.00005, help="Absolute gate threshold")
    return p.parse_args()


def _parse_model_types(raw: str) -> list[str]:
    values = [v.strip().lower() for v in raw.split(",") if v.strip()]
    bad = sorted(set(values) - set(CPU_MODEL_TYPES))
    if bad:
        raise ValueError(f"Unsupported model type(s): {bad}; allowed={list(CPU_MODEL_TYPES)}")
    if not values:
        raise ValueError("No model types selected")
    return values


def _normalize_dataset(df: pd.DataFrame) -> pd.DataFrame:
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
    return out


def _resolve_task(df: pd.DataFrame, task: str) -> str:
    if task != "auto":
        return task
    if "label" in df.columns:
        return "classification"
    if "target_return" in df.columns:
        return "regression"
    raise ValueError("Dataset must have either 'target_return' (regression) or 'label' (classification)")


def _pick_features(df: pd.DataFrame) -> list[str]:
    cols = [c for c in PREFERRED_FEATURES if c in df.columns]
    if len(cols) >= 4:
        return cols
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    if len(cols) >= 4:
        return cols
    raise ValueError("Not enough usable feature columns")


def _reg_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    dir_acc = float(np.mean(np.sign(y_true) == np.sign(y_pred)))
    corr = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else 0.0
    if not np.isfinite(corr):
        corr = 0.0
    return {"mae": mae, "rmse": rmse, "directional_accuracy": dir_acc, "corr": corr}


def _clf_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
    }


def _make_splits(ds: pd.DataFrame, features: list[str], task: str, args: argparse.Namespace) -> tuple[np.ndarray, ...]:
    X = ds[features].to_numpy(dtype=float)
    if task == "regression":
        y = ds["target_return"].to_numpy(dtype=float)
    else:
        labels = ds["label"].astype(str).str.strip().str.lower()
        classes = sorted(labels.unique().tolist())
        mapper = {k: i for i, k in enumerate(classes)}
        y = labels.map(mapper).to_numpy(dtype=int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
    return X_train, X_test, y_train, y_test


def _make_sequence_split(
    X: np.ndarray,
    y: np.ndarray,
    seq_len: int,
    max_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(X) <= seq_len:
        raise ValueError(f"Need more than seq_len={seq_len} rows for sequence training")
    X_seq = []
    y_seq = []
    for i in range(seq_len, len(X)):
        X_seq.append(X[i - seq_len : i])
        y_seq.append(y[i])
    X_arr = np.asarray(X_seq, dtype=np.float32)
    y_arr = np.asarray(y_seq, dtype=np.float32 if y.dtype.kind == "f" else np.int64)
    if len(X_arr) > max_samples:
        X_arr = X_arr[-max_samples:]
        y_arr = y_arr[-max_samples:]
    return X_arr, y_arr


def _train_sequence_regressor(
    model_type: str,
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], np.ndarray, dict[str, float]]:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from lstm_model import build_sequence_model

    normalized_model = "transformer" if model_type == "transformer_lite" else model_type
    model = build_sequence_model(
        normalized_model,
        input_dim=X_train.shape[2],
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
        dropout=args.dropout,
        nhead=2,
    )
    device = torch.device("cpu")
    model.to(device)

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train.astype(np.float32))),
        batch_size=args.batch_size,
        shuffle=True,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.MSELoss()
    model.train()
    for _ in range(max(1, int(args.epochs))):
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(X_test).to(device)).cpu().numpy()
    metrics = _reg_metrics(y_test, pred)
    artifact = {
        "kind": "torch_sequence_regressor",
        "model_type": model_type,
        "state_dict": model.state_dict(),
        "input_dim": int(X_train.shape[2]),
        "seq_len": int(X_train.shape[1]),
        "hidden_size": int(args.hidden_size),
        "num_layers": int(args.num_layers),
        "dropout": float(args.dropout),
        "nhead": 2,
    }
    return artifact, pred, metrics


def _safe_import_xgboost() -> Any | None:
    try:
        import xgboost as xgb

        return xgb
    except Exception:
        return None


def _safe_import_lightgbm() -> Any | None:
    try:
        import lightgbm as lgb

        return lgb
    except Exception:
        return None


def _safe_import_catboost() -> Any | None:
    try:
        import catboost as cb

        return cb
    except Exception:
        return None


def _train_hybrid_gate_regression(
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], np.ndarray, dict[str, float]]:
    gate = SGDRegressor(random_state=args.random_state, max_iter=2000, tol=1e-4)
    gate.fit(X_train, y_train)
    gate_pred_train = gate.predict(X_train)
    gate_pred_test = gate.predict(X_test)

    Xs_train, ys_train = _make_sequence_split(X_train, y_train, args.seq_len, args.max_seq_samples)
    Xs_test, ys_test = _make_sequence_split(X_test, y_test, min(args.seq_len, max(8, args.seq_len // 2)), args.max_seq_samples)
    seq_artifact, seq_pred, _ = _train_sequence_regressor("cnn", Xs_train, Xs_test, ys_train, ys_test, args)

    # Align sequence predictions to tail of X_test.
    aligned_seq = np.zeros_like(gate_pred_test)
    aligned_seq[-len(seq_pred) :] = seq_pred
    gate_abs = np.abs(gate_pred_test)
    th = float(args.hybrid_gate_threshold)
    # Gate first, then only execute when deep confirmation has same sign.
    confirm = np.sign(aligned_seq) == np.sign(gate_pred_test)
    pred = np.where((gate_abs >= th) & confirm, gate_pred_test, 0.0)

    metrics = _reg_metrics(y_test, pred)
    artifact = {
        "kind": "hybrid_gate_regression",
        "gate_model": gate,
        "confirm_model": seq_artifact,
        "gate_threshold": th,
        "seq_tail_len": int(len(seq_pred)),
    }
    return artifact, pred, metrics


def run(args: argparse.Namespace) -> None:
    model_types = _parse_model_types(args.model_types)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ds = _normalize_dataset(pd.read_csv(args.dataset_csv))
    task = _resolve_task(ds, args.task)
    features = _pick_features(ds)

    if task == "regression":
        ds = ds.replace([np.inf, -np.inf], np.nan).dropna(subset=features + ["target_return", "price", "ts"]).reset_index(drop=True)
    else:
        ds = ds.replace([np.inf, -np.inf], np.nan).dropna(subset=features + ["label", "price", "ts"]).reset_index(drop=True)

    if len(ds) < int(args.min_rows):
        raise ValueError(f"Need at least {args.min_rows} rows, got {len(ds)}")

    X_train, X_test, y_train, y_test = _make_splits(ds, features, task, args)
    test_df = ds.iloc[len(ds) - len(X_test) :].copy().reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    pred_store: dict[str, np.ndarray] = {}

    for model_type in model_types:
        print(f"Training {model_type} ({task}) ...", flush=True)

        artifact_path = out_dir / f"cpu_{model_type}.joblib"
        pred: np.ndarray | None = None
        metrics: dict[str, float] = {}
        artifact: Any = None

        if model_type == "ridge":
            if task != "regression":
                print("  skip ridge for classification", flush=True)
                continue
            model = Ridge(alpha=1.0, random_state=args.random_state)
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            metrics = _reg_metrics(y_test, pred)
            artifact = model

        elif model_type == "logistic":
            if task != "classification":
                print("  skip logistic for regression", flush=True)
                continue
            model = LogisticRegression(max_iter=2000, n_jobs=1)
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            metrics = _clf_metrics(y_test, pred)
            artifact = model

        elif model_type == "sgd_regressor":
            if task != "regression":
                print("  skip sgd_regressor for classification", flush=True)
                continue
            model = SGDRegressor(random_state=args.random_state, max_iter=2000, tol=1e-4)
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            metrics = _reg_metrics(y_test, pred)
            artifact = model

        elif model_type == "sgd_classifier":
            if task != "classification":
                print("  skip sgd_classifier for regression", flush=True)
                continue
            model = SGDClassifier(random_state=args.random_state, max_iter=2000, tol=1e-4)
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            metrics = _clf_metrics(y_test, pred)
            artifact = model

        elif model_type in {"xgboost", "lightgbm", "catboost"}:
            if model_type == "xgboost":
                xgb = _safe_import_xgboost()
                if xgb is None:
                    print("  skip xgboost (module not installed)", flush=True)
                    continue
                if task == "regression":
                    model = xgb.XGBRegressor(
                        objective="reg:squarederror",
                        n_estimators=300,
                        learning_rate=0.05,
                        max_depth=5,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        n_jobs=1,
                        random_state=args.random_state,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _reg_metrics(y_test, pred)
                else:
                    model = xgb.XGBClassifier(
                        objective="multi:softprob",
                        n_estimators=300,
                        learning_rate=0.05,
                        max_depth=5,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        n_jobs=1,
                        random_state=args.random_state,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _clf_metrics(y_test, pred)
                artifact = model

            elif model_type == "lightgbm":
                lgb = _safe_import_lightgbm()
                if lgb is None:
                    print("  skip lightgbm (module not installed)", flush=True)
                    continue
                if task == "regression":
                    model = lgb.LGBMRegressor(
                        n_estimators=400,
                        learning_rate=0.05,
                        num_leaves=64,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        random_state=args.random_state,
                        n_jobs=1,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _reg_metrics(y_test, pred)
                else:
                    model = lgb.LGBMClassifier(
                        n_estimators=400,
                        learning_rate=0.05,
                        num_leaves=64,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        random_state=args.random_state,
                        n_jobs=1,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _clf_metrics(y_test, pred)
                artifact = model

            else:
                cb = _safe_import_catboost()
                if cb is None:
                    print("  skip catboost (module not installed)", flush=True)
                    continue
                if task == "regression":
                    model = cb.CatBoostRegressor(
                        iterations=500,
                        depth=6,
                        learning_rate=0.05,
                        loss_function="RMSE",
                        verbose=False,
                        random_seed=args.random_state,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _reg_metrics(y_test, pred)
                else:
                    model = cb.CatBoostClassifier(
                        iterations=500,
                        depth=6,
                        learning_rate=0.05,
                        loss_function="MultiClass",
                        verbose=False,
                        random_seed=args.random_state,
                    )
                    model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    metrics = _clf_metrics(y_test, pred)
                artifact = model

        elif model_type in SEQUENCE_TYPES:
            if task != "regression":
                print(f"  skip {model_type} for classification in this script", flush=True)
                continue
            Xs_train, ys_train = _make_sequence_split(X_train, y_train, args.seq_len, args.max_seq_samples)
            Xs_test, ys_test = _make_sequence_split(X_test, y_test, args.seq_len, args.max_seq_samples)
            artifact, pred, metrics = _train_sequence_regressor(model_type, Xs_train, Xs_test, ys_train, ys_test, args)
            # pad predictions to full test length
            pred_full = np.zeros(len(X_test), dtype=float)
            pred_full[-len(pred) :] = pred
            pred = pred_full
            artifact_path = out_dir / f"cpu_{model_type}.pt"
            import torch

            torch.save(artifact, artifact_path)
            row = {"model": model_type, "artifact_path": str(artifact_path), **metrics}
            row["train_rows"] = int(len(Xs_train))
            row["test_rows"] = int(len(Xs_test))
            rows.append(row)
            pred_store[model_type] = pred
            print(f"  saved {artifact_path}", flush=True)
            continue

        elif model_type == "hybrid_gate":
            if task != "regression":
                print("  skip hybrid_gate for classification", flush=True)
                continue
            artifact, pred, metrics = _train_hybrid_gate_regression(X_train, X_test, y_train, y_test, args)
            import torch

            artifact_path = out_dir / "cpu_hybrid_gate.pt"
            torch.save(artifact, artifact_path)
            row = {"model": model_type, "artifact_path": str(artifact_path), **metrics}
            row["train_rows"] = int(len(X_train))
            row["test_rows"] = int(len(X_test))
            rows.append(row)
            pred_store[model_type] = pred
            print(f"  saved {artifact_path}", flush=True)
            continue

        else:
            print(f"  skip unknown model {model_type}", flush=True)
            continue

        if artifact is None or pred is None:
            continue

        joblib.dump({"model": artifact, "features": features, "task": task}, artifact_path)
        row = {"model": model_type, "artifact_path": str(artifact_path), **metrics}
        row["train_rows"] = int(len(X_train))
        row["test_rows"] = int(len(X_test))
        rows.append(row)
        pred_store[model_type] = np.asarray(pred)
        print(f"  saved {artifact_path}", flush=True)

    if not rows:
        raise RuntimeError("No models were trained. Check model-types and installed dependencies.")

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(args.metrics_out_csv, index=False)
    print(f"Saved metrics: {args.metrics_out_csv}", flush=True)

    if args.pred_out_csv:
        pred_df = test_df[[c for c in ["ts", "price", "target_price", "target_return", "label"] if c in test_df.columns]].copy()
        for k, v in pred_store.items():
            arr = np.asarray(v)
            if len(arr) != len(pred_df):
                padded = np.full(len(pred_df), np.nan)
                padded[-len(arr) :] = arr
                arr = padded
            pred_df[f"pred_{k}"] = arr
        Path(args.pred_out_csv).parent.mkdir(parents=True, exist_ok=True)
        pred_df.to_csv(args.pred_out_csv, index=False)
        print(f"Saved predictions: {args.pred_out_csv}", flush=True)

    if "rmse" in metrics_df.columns:
        best = metrics_df.sort_values("rmse").iloc[0]
        print(f"Best by RMSE: {best['model']} rmse={best['rmse']:.8f}", flush=True)
    elif "accuracy" in metrics_df.columns:
        best = metrics_df.sort_values("accuracy", ascending=False).iloc[0]
        print(f"Best by accuracy: {best['model']} acc={best['accuracy']:.4f}", flush=True)


def main() -> int:
    args = parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
