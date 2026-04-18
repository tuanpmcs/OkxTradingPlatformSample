# ML Pipeline (Minimal Flow)

This folder supports the Python training and inference side of the compact architecture.

Runtime:

```text
OKX WS
  -> C++ runtime backend
      -> parse trades/books5
      -> maintain rolling state
      -> build feature
      -> call Python/SageMaker inference
      -> receive prediction
      -> simulator / frontend
```

Training:

```text
OKX WS / historical data
  -> C++ collector backend
      -> parse trades/books5
      -> maintain rolling state
      -> build feature
      -> future label
      -> dataset export
  -> Python training
```

Local script flow:

1. Collect trades + order book from gRPC or consume C++ CSV export
2. Build realtime features
3. Create future-`Δt` labels
4. Train XGBoost/CNN/LSTM/Transformer models (`train_model.py`)
5. Run inference server
6. (Optional) test prediction server

## Pipeline Mapping

| Stage | Input | Output | Tool |
| --- | --- | --- | --- |
| Market | Order book / Trades | Raw data | OKX WebSocket |
| Data | Raw stream | Structured dataset | Python / C++ |
| Feature | Raw data | Feature vector | NumPy / Pandas |
| Label | Feature + future price | `y` (`up/down/neutral`) | Python |
| Model | `X`, `y` | Prediction model | XGBoost / PyTorch CNN / LSTM / Transformer |
| System | Model + stream | Trading signal | C++ + gRPC |

## Feature Engineering

| Feature | Formula | Meaning |
| --- | --- | --- |
| `mid_price` | `(bid + ask) / 2` | Fair price |
| `spread` | `ask - bid` | Liquidity |
| `imbalance` | `(bid_vol - ask_vol) / (bid_vol + ask_vol)` | Buy vs sell pressure |
| `trade_volume` | `sum(size)` (rolling) | Activity |
| `trade_imbalance` | `buy_vol - sell_vol` (rolling) | Aggressive flow |

## Label Rules

| Condition | Label |
| --- | --- |
| `future_mid - current_mid > eps` | `up` |
| `future_mid - current_mid < -eps` | `down` |
| otherwise | `neutral` |

## Prerequisites

- C++ backend stream server running on `127.0.0.1:50051`
- Python 3.9+ installed

## 1) Setup

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample/ml_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Collect trades + order book from C++ gRPC stream

```bash
python collect_ticks_from_grpc.py \
  --target 127.0.0.1:50051 \
  --symbol BTC-USDT \
  --trade-channel trades \
  --book-channel books5 \
  --duration-sec 300 \
  --out-csv ../data/books_trades_btcusdt.csv
```

## 3) Build realtime features

```bash
python build_realtime_features.py \
  --csv ../data/books_trades_btcusdt.csv \
  --symbol BTC-USDT \
  --channels trades,books5 \
  --out-csv ../data/features_btcusdt.csv
```

If the channel filter does not match collected rows, the script logs available symbols/channels and falls back to all collected rows. If the CSV only has a header, collect for longer and confirm the stream is producing books/trades ticks.

## 4) Create future-Δt labels

```bash
python create_future_labels.py \
  --features-csv ../data/features_btcusdt.csv \
  --horizon-sec 30 \
  --eps 0.0001 \
  --out-csv ../data/train_dataset_btcusdt_h30.csv
```

## 5) Train and compare models

```bash
python train_model.py \
  --dataset-csv ../data/train_dataset_btcusdt_h30.csv \
  --model-out-dir ../models \
  --model-types xgboost,cnn,lstm,transformer
```

For notebook-based evaluation, open:

`notebooks/model_comparison.ipynb`

It trains XGBoost, CNN, LSTM, and Transformer on the same split, saves model artifacts, and writes:

`../data/model_comparison_metrics.csv`

## 6) Run inference server

```bash
python prediction_server.py \
  --model ../models/pulse_lstm_v1.pt \
  --host 127.0.0.1 \
  --port 50061
```

## 7) (Optional) test prediction server

```bash
python predict_client.py \
  --target 127.0.0.1:50061 \
  --csv ../data/books_trades_btcusdt.csv \
  --symbol BTC-USDT \
  --channel books5 \
  --horizon-sec 30
```

## Notes

- `prediction_server.py` can serve `.pt`, `.joblib`, and `.json` model artifacts. Runtime defaults to the LSTM artifact; point `MODEL_PATH` at XGBoost, CNN, or Transformer artifacts to switch architectures.
- `../data` and `../models` will be created by scripts when needed.
