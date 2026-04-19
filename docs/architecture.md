# Architecture

## Decision boundaries

- Training pipeline: Python (`ml_pipeline/`)
- Online feature + strategy + simulation: C++ (`backend/`)
- Cloud services: artifact, orchestration, deployment (`deploy/`)
- Sub-ms decision loop must not depend on cloud endpoint latency.

## Levels

1. Research: C++ capture + Python training/inference local
2. Semi-production: C++ online features + local inference service + cloud for artifacts/logs
3. HFT: fully local colocated decision stack; cloud for offline analytics/training/storage only

## Runtime path

```text
OKX WS -> C++ ingest -> feature builder -> inference call -> strategy/risk -> simulator/execution
```

## Training path

```text
C++ stream/books/trades -> feature snapshots -> labels -> model train/eval/export -> model registry/artifact
```
