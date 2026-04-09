# ML Pipeline (Minimal Flow)

This folder is trimmed to a single production path:

1. Collect trades + order book from gRPC
2. Build realtime features
3. Create future-`Δt` labels
4. Train tree model (`train_better_model.py`)
5. Run inference server
6. (Optional) test prediction server

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
  --out-csv ../data/market_stream_btcusdt.csv
```

## 3) Build realtime features

```bash
python build_realtime_features.py \
  --csv ../data/market_stream_btcusdt.csv \
  --symbol BTC-USDT \
  --channels trades,books5 \
  --out-csv ../data/features_btcusdt.csv
```

## 4) Create future-Δt labels

```bash
python create_future_labels.py \
  --features-csv ../data/features_btcusdt.csv \
  --horizon-sec 30 \
  --out-csv ../data/train_dataset_btcusdt_h30.csv
```

## 5) Train model (recommended tree model)

```bash
python train_better_model.py \
  --dataset-csv ../data/train_dataset_btcusdt_h30.csv \
  --model-out ../models/pulse_tree_v1.joblib
```

## 6) Run inference server

```bash
python prediction_server.py \
  --model ../models/pulse_tree_v1.joblib \
  --host 127.0.0.1 \
  --port 50061
```

## 7) (Optional) test prediction server

```bash
python predict_client.py \
  --target 127.0.0.1:50061 \
  --csv ../data/market_stream_btcusdt.csv \
  --symbol BTC-USDT \
  --channel books5 \
  --horizon-sec 30
```

## Notes

- `prediction_server.py` can serve `.joblib` and `.json` model artifacts.
- `../data` and `../models` will be created by scripts when needed.
