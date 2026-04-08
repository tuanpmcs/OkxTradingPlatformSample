# Python Prediction Pipeline

Reliable workflow for price prediction + buy/sell simulation.

## What this gives you

1. `train_model.py`
Trains a linear model from historical stream data and exports a portable JSON model.

1b. `train_better_model.py`
Trains a stronger tree-based model and exports `.joblib`.

1c. `train_lstm_model.py`
Trains an LSTM sequence model and exports `.pt`.

2. `infer_model.py`
Loads exported model JSON and predicts next price from recent ticks.

3. `simulate_strategy.py`
Runs buy->sell simulation with fixed holding horizon and reports PnL stats.

4. `prediction_server.py`
Serves model inference over gRPC (`PredictionService/Predict`).

5. `collect_ticks_from_grpc.py`
Collects real market ticks from C++ `MarketData` gRPC stream into CSV.

6. `predict_client.py`
Smoke-tests `PredictionService/Predict` without frontend.

## Data format

Input CSV should include at least:

- `ts` (unix ms)
- `price` (float)

Optional:

- `channel`
- `instId`

## Setup

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample/ml_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Train

```bash
python train_model.py \
  --csv ../data/ticks.csv \
  --model-out ../models/pulse_linear_v2.json \
  --horizon-sec 30
```

## Train better model (recommended)

```bash
python train_better_model.py \
  --csv ../data/ticks_btcusdt_tickers.csv \
  --model-out ../models/pulse_tree_v1.joblib \
  --horizon-sec 30
```

## Train LSTM model (sequence)

```bash
python train_lstm_model.py \
  --csv ../data/ticks_btcusdt_tickers.csv \
  --model-out ../models/pulse_lstm_v1.pt \
  --horizon-sec 30 \
  --seq-len 60 \
  --epochs 20
```

## Collect real ticks from C++ gRPC stream

```bash
python collect_ticks_from_grpc.py \
  --target 127.0.0.1:50051 \
  --symbol BTC-USDT \
  --channel tickers \
  --duration-sec 300 \
  --out-csv ../data/ticks_btcusdt_tickers.csv
```

## Predict

```bash
python infer_model.py \
  --csv ../data/ticks.csv \
  --model ../models/pulse_linear_v2.json
```

## Simulate

```bash
python simulate_strategy.py \
  --csv ../data/ticks.csv \
  --model ../models/pulse_linear_v2.json \
  --capital 5000 \
  --hold-sec 30
```

## Run gRPC inference server

```bash
python prediction_server.py \
  --model ../models/pulse_lstm_v1.pt \
  --host 127.0.0.1 \
  --port 50061
```

## Test prediction server directly

```bash
python predict_client.py \
  --target 127.0.0.1:50061 \
  --csv ../data/ticks_btcusdt_tickers.csv \
  --symbol BTC-USDT \
  --channel tickers \
  --horizon-sec 30
```

## End-to-end quick run

1. Run C++ stream server (`127.0.0.1:50051`)
2. Collect ticks to CSV (`collect_ticks_from_grpc.py`)
3. Train better model (`train_better_model.py`)
4. Start prediction gRPC server (`prediction_server.py`)
5. Verify prediction (`predict_client.py`)
6. Start desktop app with `PRED_GRPC_TARGET=127.0.0.1:50061 npm start`

## Integration notes

- Frontend can load the exported JSON and replace hardcoded `PREBUILT_MODEL`.
- C++ backend can call `infer_model.py` or read the JSON model directly.
- Keep train/infer feature logic identical to avoid training-serving skew.
