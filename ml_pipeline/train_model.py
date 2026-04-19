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

from common import FEATURE_COLUMNS, FeatureConfig, attach_direction_label, build_features, load_ticks

MODEL_TYPES = ("xgboost", "lstm", "cnn")
SEQUENCE_MODEL_TYPES = ("lstm", "cnn")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train XGBoost/LSTM/CNN price-return models")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Input raw ticks CSV")
    src.add_argument("--dataset-csv", help="Input labeled dataset CSV")
    p.add_argument("--model-out", help="Output model artifact when training a single model")
    p.add_argument("--model-out-dir", help="Output directory when training multiple models")
    p.add_argument(
        "--model-types",
        default="xgboost,lstm,cnn",
        help="Comma-separated models to train: xgboost,lstm,cnn",
    )
    p.add_argument("--horizon-sec", type=int, default=30, help="Prediction horizon in seconds")
    p.add_argument("--label-eps", type=float, default=0.0001, help="Kept for dataset compatibility")
    p.add_argument("--test-size", type=float, default=0.2, help="Validation split fraction")
    p.add_argument("--random-state", type=int, default=42, help="Random seed")
    p.add_argument("--seq-len", type=int, default=60, help="Number of log-return steps per sample")
    p.add_argument("--epochs", type=int, default=12, help="Training epochs per model")
    p.add_argument("--batch-size", type=int, default=128, help="Batch size")
    p.add_argument("--hidden-size", type=int, default=64, help="Hidden/channel size")
    p.add_argument("--num-layers", type=int, default=2, help="LSTM/CNN layer count")
    p.add_argument("--dropout", type=float, default=0.1, help="Dropout probability")
    p.add_argument("--learning-rate", type=float, default=0.001, help="AdamW learning rate")
    p.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda", "mps"],
        default="auto",
        help="Torch device for sequence models",
    )
    p.add_argument(
        "--early-stop-patience",
        type=int,
        default=3,
        help="Stop sequence training if validation loss does not improve for N epochs (0 disables)",
    )
    p.add_argument(
        "--early-stop-min-delta",
        type=float,
        default=1e-6,
        help="Minimum validation loss improvement to reset patience",
    )
    p.add_argument(
        "--metrics-out-csv",
        help="Optional output CSV path for per-model training metrics",
    )
    p.add_argument(
        "--best-model-out",
        help="Optional output path to copy the best model artifact (lowest RMSE)",
    )
    p.add_argument("--min-rows", type=int, default=500, help="Minimum required dataset rows")
    p.add_argument(
        "--task",
        choices=["auto", "regression", "classification"],
        default="auto",
        help="Training task. auto infers from dataset columns.",
    )
    return p.parse_args()


def _parse_model_types(raw: str) -> list[str]:
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    bad = sorted(set(values) - set(MODEL_TYPES))
    if bad:
        raise ValueError(f"Unsupported model type(s): {bad}; expected {list(MODEL_TYPES)}")
    if not values:
        raise ValueError("No model types selected")
    return values


def _load_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    def normalize_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "mid_price" not in out.columns and "price" in out.columns:
            out["mid_price"] = pd.to_numeric(out["price"], errors="coerce")
        if "spread" not in out.columns:
            if "best_ask_px" in out.columns and "best_bid_px" in out.columns:
                out["spread"] = (
                    pd.to_numeric(out["best_ask_px"], errors="coerce")
                    - pd.to_numeric(out["best_bid_px"], errors="coerce")
                )
        if "imbalance" not in out.columns:
            if "imbalance_l5" in out.columns:
                out["imbalance"] = pd.to_numeric(out["imbalance_l5"], errors="coerce")
            elif "imbalance_l1" in out.columns:
                out["imbalance"] = pd.to_numeric(out["imbalance_l1"], errors="coerce")
        if "trade_volume" not in out.columns:
            if "buy_volume" in out.columns and "sell_volume" in out.columns:
                out["trade_volume"] = (
                    pd.to_numeric(out["buy_volume"], errors="coerce")
                    + pd.to_numeric(out["sell_volume"], errors="coerce")
                )
        if "trade_imbalance" not in out.columns:
            if "buy_volume" in out.columns and "sell_volume" in out.columns:
                out["trade_imbalance"] = (
                    pd.to_numeric(out["buy_volume"], errors="coerce")
                    - pd.to_numeric(out["sell_volume"], errors="coerce")
                )

        return out

    if args.dataset_csv:
        ds = normalize_feature_columns(pd.read_csv(args.dataset_csv))
        if "target_return" in ds.columns:
            required = set(FEATURE_COLUMNS + ["target_return", "price", "target_price", "target_ts", "ts"])
            missing = sorted(required - set(ds.columns))
            if missing:
                raise ValueError(f"dataset CSV missing required columns: {missing}")
            cleaned = ds.replace([np.inf, -np.inf], np.nan).dropna(
                subset=FEATURE_COLUMNS + ["target_return", "price", "target_price", "target_ts", "ts"]
            )
            return cleaned, "regression"

        if "label" in ds.columns:
            required = set(FEATURE_COLUMNS + ["label"])
            missing = sorted(required - set(ds.columns))
            if missing:
                raise ValueError(f"feature+label dataset missing required columns: {missing}")
            cleaned = ds.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS + ["label"]).reset_index(drop=True)
            cleaned["label"] = cleaned["label"].astype(str).str.strip().str.lower()
            return cleaned, "classification"

        raise ValueError(
            "dataset CSV must contain either 'target_return' (regression) or 'label' (classification)"
        )

    cfg = FeatureConfig(horizon_sec=args.horizon_sec)
    df = load_ticks(args.csv)
    labeled = attach_direction_label(build_features(df, cfg), eps=args.label_eps)
    cols = FEATURE_COLUMNS + ["target_return", "label", "price", "target_price", "target_ts", "ts"]
    return labeled[cols].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True), "regression"


def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    acc = float(accuracy_score(y_true, y_pred))
    f1 = float(f1_score(y_true, y_pred, average="macro"))
    return {"accuracy": acc, "macro_f1": f1}


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

    X = np.asarray(samples, dtype=np.float32)
    y = np.asarray(targets, dtype=np.float32)
    ret_mean = float(X.mean())
    ret_std = float(X.std() or 1.0)
    X = (X - ret_mean) / ret_std
    return X, y, {"ret_mean": ret_mean, "ret_std": ret_std}


def _resolve_output_path(args: argparse.Namespace, model_type: str, count: int) -> Path:
    if count == 1 and args.model_out:
        return Path(args.model_out)
    out_dir = Path(args.model_out_dir or (Path(args.model_out).parent if args.model_out else "models"))
    suffix = ".joblib" if model_type == "xgboost" else ".pt"
    return out_dir / f"pulse_{model_type}_v1{suffix}"


def _extract_label_metadata(ds: pd.DataFrame, default_eps: float) -> dict[str, Any]:
    label_classes: list[str] = []
    if "label" in ds.columns:
        counts = ds["label"].dropna().astype(str).value_counts().to_dict()
        if counts:
            label_classes = sorted(counts.keys())

    label_eps = float(default_eps)
    if "label_eps" in ds.columns:
        eps_values = pd.to_numeric(ds["label_eps"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if not eps_values.empty:
            label_eps = float(np.median(eps_values.to_numpy(dtype=float)))

    return {
        "label_classes": label_classes,
        "label_eps": label_eps,
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


def _train_xgboost_model(
    ds: pd.DataFrame,
    args: argparse.Namespace,
) -> tuple[Any, dict[str, float]]:
    from xgboost import XGBRegressor

    X = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["target_return"].to_numpy(dtype=float)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
    )
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
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    metrics = _metrics(y_test, pred)
    metrics.update({"train_rows": int(len(X_train)), "test_rows": int(len(X_test))})
    return model, metrics


def _train_xgboost_classifier(
    ds: pd.DataFrame,
    args: argparse.Namespace,
) -> tuple[Any, dict[str, float], list[str]]:
    from xgboost import XGBClassifier

    ordered_labels = [label for label in ("down", "neutral", "up") if label in set(ds["label"].tolist())]
    if not ordered_labels:
        ordered_labels = sorted(ds["label"].astype(str).unique().tolist())
    label_to_id = {label: idx for idx, label in enumerate(ordered_labels)}

    X = ds[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = ds["label"].map(label_to_id).to_numpy(dtype=int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
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
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    metrics = _classification_metrics(y_test, pred)
    metrics.update({"train_rows": int(len(X_train)), "test_rows": int(len(X_test))})
    return model, metrics, ordered_labels


def _train_one_model(
    model_type: str,
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    args: argparse.Namespace,
) -> tuple[Any, dict[str, float]]:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from lstm_model import build_sequence_model

    torch.manual_seed(int(args.random_state))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(args.random_state))

    if args.device == "auto":
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        if args.device == "cuda" and not torch.cuda.is_available():
            raise ValueError("Requested --device cuda but CUDA is not available")
        if args.device == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise ValueError("Requested --device mps but MPS is not available")
        device = torch.device(args.device)

    print(f"{model_type} device={device}", flush=True)
    model = build_sequence_model(
        model_type=model_type,
        input_dim=int(X_train.shape[-1]),
        hidden_size=int(args.hidden_size),
        num_layers=int(args.num_layers),
        dropout=float(args.dropout),
        nhead=4,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(args.learning_rate), weight_decay=1e-4)
    loss_fn = nn.SmoothL1Loss()
    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    valid_ds = TensorDataset(torch.from_numpy(X_test), torch.from_numpy(y_test))
    loader = DataLoader(
        train_ds,
        batch_size=int(args.batch_size),
        shuffle=True,
    )
    valid_loader = DataLoader(
        valid_ds,
        batch_size=int(args.batch_size),
        shuffle=False,
    )

    best_val = float("inf")
    best_state = None
    patience = max(0, int(args.early_stop_patience))
    no_improve_epochs = 0

    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        losses: list[float] = []
        for xb, yb in loader:
            xb = xb.to(device=device, dtype=torch.float32, non_blocking=True)
            yb = yb.to(device=device, dtype=torch.float32, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            losses.append(float(loss.item()))

        model.eval()
        val_losses: list[float] = []
        with torch.no_grad():
            for xb, yb in valid_loader:
                xb = xb.to(device=device, dtype=torch.float32, non_blocking=True)
                yb = yb.to(device=device, dtype=torch.float32, non_blocking=True)
                pred = model(xb)
                val_losses.append(float(loss_fn(pred, yb).item()))

        train_loss = float(np.mean(losses)) if losses else float("nan")
        val_loss = float(np.mean(val_losses)) if val_losses else float("nan")
        print(
            f"{model_type} epoch={epoch}/{int(args.epochs)} train_loss={train_loss:.8f} val_loss={val_loss:.8f}",
            flush=True,
        )

        improve = best_val - val_loss
        if np.isfinite(val_loss) and improve > float(args.early_stop_min_delta):
            best_val = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            no_improve_epochs = 0
        else:
            no_improve_epochs += 1
            if patience > 0 and no_improve_epochs >= patience:
                print(
                    f"{model_type} early stopping at epoch={epoch} (best_val={best_val:.8f})",
                    flush=True,
                )
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(X_test).to(device=device, dtype=torch.float32)).detach().cpu().numpy()
    metrics = _metrics(y_test, pred)
    metrics.update({"train_rows": int(len(X_train)), "test_rows": int(len(X_test))})
    return model, metrics


def main() -> None:
    args = parse_args()
    model_types = _parse_model_types(args.model_types)
    ds, inferred_task = _load_dataset(args)
    ds = ds.reset_index(drop=True)

    if args.task == "auto":
        task = inferred_task
    else:
        task = args.task
        if task != inferred_task:
            raise ValueError(f"Requested task={task} but dataset implies task={inferred_task}")

    min_rows = max(int(args.min_rows), int(args.seq_len) + 2)
    if len(ds) < min_rows:
        raise ValueError(f"Need at least {min_rows} rows, got {len(ds)}")
    print(
        f"Loaded rows={len(ds)} task={task} models={','.join(model_types)} seq_len={int(args.seq_len)} epochs={int(args.epochs)}",
        flush=True,
    )

    label_meta = _extract_label_metadata(ds, default_eps=float(args.label_eps))

    if task == "classification":
        skipped = [m for m in model_types if m != "xgboost"]
        if skipped:
            print(f"Skipping unsupported model types for classification task: {skipped}")
        model_types = [m for m in model_types if m == "xgboost"]
        if not model_types:
            raise ValueError("Classification task currently supports only xgboost in this pipeline")

    sequence_cache: tuple[np.ndarray, np.ndarray, dict[str, float]] | None = None
    trained_runs: list[dict[str, Any]] = []
    for model_type in model_types:
        print(f"Training model={model_type}...", flush=True)
        out = _resolve_output_path(args, model_type, len(model_types))
        out.parent.mkdir(parents=True, exist_ok=True)

        if model_type == "xgboost":
            if task == "classification":
                model, metrics, class_names = _train_xgboost_classifier(ds, args)
                artifact = {
                    "model_type": "xgboost_classifier",
                    "model_name": "PulseXGBoostClassifierV1",
                    "horizon_sec": int(args.horizon_sec),
                    "feature_columns": FEATURE_COLUMNS,
                    "label_classes": class_names,
                    "label_eps": label_meta["label_eps"],
                    "model": model,
                    "metrics": metrics,
                }
            else:
                model, metrics = _train_xgboost_model(ds, args)
                artifact = {
                    "model_type": "xgboost_regressor",
                    "model_name": "PulseXGBoostV1",
                    "horizon_sec": int(args.horizon_sec),
                    "feature_columns": FEATURE_COLUMNS,
                    "label_classes": label_meta["label_classes"],
                    "label_eps": label_meta["label_eps"],
                    "model": model,
                    "metrics": metrics,
                }
            joblib.dump(artifact, out)
        else:
            import torch

            if sequence_cache is None:
                sequence_cache = _make_sequence_dataset(ds, seq_len=int(args.seq_len))
            X, y, norm = sequence_cache
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=args.test_size, random_state=args.random_state, shuffle=False
            )
            model, metrics = _train_one_model(model_type, X_train, X_test, y_train, y_test, args)
            artifact = {
                "model_type": model_type,
                "model_name": f"Pulse{model_type.upper()}V1",
                "horizon_sec": int(args.horizon_sec),
                "label_classes": label_meta["label_classes"],
                "label_eps": label_meta["label_eps"],
                "seq_len": int(args.seq_len),
                "input_dim": int(X.shape[-1]),
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

        trained_runs.append(
            {
                "model": model_type,
                "artifact_path": str(out),
                **metrics,
            }
        )

        print(f"Saved {model_type.upper()} model: {out}")
        if task == "classification":
            print(f"{model_type} accuracy={metrics['accuracy']:.6f} macro_f1={metrics['macro_f1']:.6f}")
        else:
            print(f"{model_type} mae={metrics['mae']:.8f} rmse={metrics['rmse']:.8f}")
            print(
                f"{model_type} dir_acc={metrics['directional_accuracy']:.4f} "
                f"corr={metrics['corr']:.4f} mape={metrics['mape']:.4f}"
            )

    if trained_runs:
        if task == "classification":
            summary_df = pd.DataFrame(trained_runs).sort_values(["accuracy", "macro_f1"], ascending=False).reset_index(drop=True)
        else:
            summary_df = pd.DataFrame(trained_runs).sort_values("rmse").reset_index(drop=True)

        if args.metrics_out_csv:
            metrics_out = Path(args.metrics_out_csv)
            metrics_out.parent.mkdir(parents=True, exist_ok=True)
            summary_df.to_csv(metrics_out, index=False)
            print(f"Saved metrics summary: {metrics_out}")

        best = summary_df.iloc[0]
        if task == "classification":
            print(
                "Best model by accuracy: "
                f"{best['model']} (accuracy={float(best['accuracy']):.6f}, macro_f1={float(best['macro_f1']):.6f})"
            )
        else:
            print(
                "Best model by RMSE: "
                f"{best['model']} (rmse={float(best['rmse']):.8f}, dir_acc={float(best['directional_accuracy']):.4f})"
            )

        if args.best_model_out:
            best_model_out = Path(args.best_model_out)
            best_model_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best["artifact_path"], best_model_out)
            print(f"Copied best artifact: {best_model_out}")


if __name__ == "__main__":
    main()
