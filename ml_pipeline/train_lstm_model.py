from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from common import load_ticks
from lstm_model import LSTMRegressor, build_lstm_dataset


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train LSTM model for price return prediction")
    p.add_argument("--csv", required=True, help="Input ticks CSV (ts,price)")
    p.add_argument("--model-out", required=True, help="Output .pt model path")
    p.add_argument("--horizon-sec", type=int, default=30, help="Prediction horizon in seconds")
    p.add_argument("--seq-len", type=int, default=60, help="Lookback sequence length")
    p.add_argument("--epochs", type=int, default=20, help="Training epochs")
    p.add_argument("--batch-size", type=int, default=128, help="Batch size")
    p.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    p.add_argument("--hidden-size", type=int, default=64, help="LSTM hidden size")
    p.add_argument("--num-layers", type=int, default=2, help="LSTM layers")
    p.add_argument("--dropout", type=float, default=0.1, help="LSTM dropout")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    df = load_ticks(args.csv)
    prices = df["price"].to_numpy(dtype=float)
    ts = df["ts"].to_numpy(dtype=np.int64)
    X, y, horizon_steps = build_lstm_dataset(prices, ts, args.seq_len, args.horizon_sec)

    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    ret_mean = float(X_train.mean())
    ret_std = float(X_train.std() + 1e-9)
    X_train = (X_train - ret_mean) / ret_std
    X_test = (X_test - ret_mean) / ret_std

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMRegressor(
        input_dim=1,
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
        dropout=args.dropout,
    ).to(device)

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train)),
        batch_size=args.batch_size,
        shuffle=True,
    )
    test_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_test), torch.from_numpy(y_test)),
        batch_size=args.batch_size,
        shuffle=False,
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    criterion = torch.nn.SmoothL1Loss()

    for epoch in range(args.epochs):
        model.train()
        losses = []
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.item()))
        print(f"epoch={epoch+1} train_loss={np.mean(losses):.8f}")

    model.eval()
    preds = []
    actuals = []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb).cpu().numpy()
            preds.append(pred)
            actuals.append(yb.numpy())
    pred_arr = np.concatenate(preds)
    act_arr = np.concatenate(actuals)
    rmse = float(np.sqrt(np.mean((pred_arr - act_arr) ** 2)))
    mae = float(np.mean(np.abs(pred_arr - act_arr)))

    artifact = {
        "model_type": "lstm",
        "model_name": "PulseLSTMV1",
        "horizon_sec": int(args.horizon_sec),
        "horizon_steps": int(horizon_steps),
        "seq_len": int(args.seq_len),
        "input_dim": 1,
        "hidden_size": int(args.hidden_size),
        "num_layers": int(args.num_layers),
        "dropout": float(args.dropout),
        "ret_mean": ret_mean,
        "ret_std": ret_std,
        "metrics": {
            "rmse": rmse,
            "mae": mae,
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
        },
        "state_dict": model.state_dict(),
    }

    out = Path(args.model_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(artifact, out)
    print(f"Saved LSTM model: {out}")
    print(f"RMSE={rmse:.8f} MAE={mae:.8f}")


if __name__ == "__main__":
    main()
