from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


class LSTMRegressor(nn.Module):
    def __init__(self, input_dim: int = 1, hidden_size: int = 64, num_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        pred = self.head(last)
        return pred.squeeze(-1)


def build_lstm_dataset(prices: np.ndarray, ts: np.ndarray, seq_len: int, horizon_sec: int) -> tuple[np.ndarray, np.ndarray, int]:
    if prices.size < seq_len + 20:
        raise ValueError("not enough price points for LSTM dataset")

    diffs = np.diff(ts.astype(np.int64))
    positive = diffs[diffs > 0]
    median_dt_ms = int(np.median(positive)) if positive.size > 0 else 1000
    horizon_steps = max(1, int(round((horizon_sec * 1000) / median_dt_ms)))

    log_returns = np.log(np.maximum(prices[1:], 1e-12) / np.maximum(prices[:-1], 1e-12))
    n_prices = prices.size

    X = []
    y = []
    for j in range(seq_len, n_prices - horizon_steps):
        seq = log_returns[j - seq_len : j]
        target_ret = (prices[j + horizon_steps] / prices[j]) - 1.0
        X.append(seq.reshape(seq_len, 1))
        y.append(target_ret)

    if len(X) < 200:
        raise ValueError(f"not enough training windows: {len(X)}")

    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32), horizon_steps

