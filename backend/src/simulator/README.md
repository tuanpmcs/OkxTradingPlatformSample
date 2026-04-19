# C++ Simulator Module

This module contains the local paper-trading simulator used by `paper_trader`.

## Components

- `paper_simulator.hpp/.cpp`
  - position state
  - fee/slippage accounting
  - realized/unrealized PnL snapshots
  - max-hold based position exits

## Build

From repo root:

```bash
cmake --build --preset arm64-osx-dynamic-rel --target paper_trader inference_client
```

## Run `paper_trader`

`paper_trader` subscribes to `MarketData` stream (`backend-cpp`), calls PredictionService through the C++ gRPC prediction client, and executes a simple paper strategy:

```bash
./build/arm64-osx-dynamic/release/bin/paper_trader \
  --stream-target 127.0.0.1:50051 \
  --predict-target 127.0.0.1:50061 \
  --symbol BTC-USDT \
  --channel books5 \
  --runtime-sec 60 \
  --report-every 50 \
  --min-points 32 \
  --max-points 256
```

## Run `inference_client`

`inference_client` is a lightweight C++ inference probe. It reads stream ticks and prints model outputs:

```bash
./build/arm64-osx-dynamic/release/bin/inference_client \
  --stream-target 127.0.0.1:50051 \
  --predict-target 127.0.0.1:50061 \
  --symbol BTC-USDT \
  --channel books5
```
