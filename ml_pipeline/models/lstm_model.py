from __future__ import annotations

import torch
from torch import nn


class LSTMRegressor(nn.Module):
    def __init__(
        self,
        input_dim: int = 1,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        lstm_dropout = dropout if num_layers > 1 else 0.0
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=lstm_dropout,
            batch_first=True,
        )
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_size),
            nn.Linear(hidden_size, max(1, hidden_size // 2)),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(max(1, hidden_size // 2), 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class CNNRegressor(nn.Module):
    def __init__(
        self,
        input_dim: int = 1,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        in_channels = input_dim
        for i in range(max(1, num_layers)):
            dilation = 2**i
            layers.extend(
                [
                    nn.Conv1d(
                        in_channels,
                        hidden_size,
                        kernel_size=3,
                        padding=dilation,
                        dilation=dilation,
                    ),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                ]
            )
            in_channels = hidden_size
        self.net = nn.Sequential(*layers)
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_size),
            nn.Linear(hidden_size, max(1, hidden_size // 2)),
            nn.ReLU(),
            nn.Linear(max(1, hidden_size // 2), 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)
        out = self.net(x).transpose(1, 2)
        return self.head(out[:, -1, :]).squeeze(-1)


class TransformerRegressor(nn.Module):
    def __init__(
        self,
        input_dim: int = 1,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
        nhead: int = 4,
    ) -> None:
        super().__init__()
        self.proj = nn.Linear(input_dim, hidden_size)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_size,
            nhead=nhead,
            dim_feedforward=hidden_size * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=max(1, num_layers))
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_size),
            nn.Linear(hidden_size, max(1, hidden_size // 2)),
            nn.GELU(),
            nn.Linear(max(1, hidden_size // 2), 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.encoder(self.proj(x))
        return self.head(out[:, -1, :]).squeeze(-1)


def build_sequence_model(
    model_type: str,
    input_dim: int,
    hidden_size: int,
    num_layers: int,
    dropout: float,
    nhead: int = 4,
) -> nn.Module:
    model_type = model_type.lower()
    if model_type == "lstm":
        return LSTMRegressor(input_dim, hidden_size, num_layers, dropout)
    if model_type == "cnn":
        return CNNRegressor(input_dim, hidden_size, num_layers, dropout)
    if model_type == "transformer":
        return TransformerRegressor(input_dim, hidden_size, num_layers, dropout, nhead=nhead)
    raise ValueError(f"Unsupported sequence model_type: {model_type}")

