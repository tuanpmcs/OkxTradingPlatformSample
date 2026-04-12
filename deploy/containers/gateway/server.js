const path = require('node:path');
const express = require('express');
const cors = require('cors');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const PORT = Number(process.env.PORT || 8080);
const PRED_TARGET = String(process.env.PRED_GRPC_TARGET || 'inference-python:50061');
const PROTO_PATH = process.env.PROTO_PATH || path.resolve(__dirname, 'proto', 'market_data.proto');

const pkgDef = protoLoader.loadSync(PROTO_PATH, {
  keepCase: true,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true,
});
const marketstream = grpc.loadPackageDefinition(pkgDef).marketstream;
const predClient = new marketstream.PredictionService(PRED_TARGET, grpc.credentials.createInsecure());

const app = express();
app.use(cors());
app.use(express.json({ limit: '2mb' }));

app.get('/health', (_req, res) => {
  res.json({ ok: true, service: 'web-gateway', predTarget: PRED_TARGET });
});

app.post('/predict', (req, res) => {
  const body = req.body || {};
  const points = Array.isArray(body.points)
    ? body.points
      .map((p) => ({
        ts: Number.isFinite(Number(p?.ts)) ? Number(p.ts) : Date.now(),
        price: Number(p?.price),
        bid_px: Number.isFinite(Number(p?.bidPx)) ? Number(p.bidPx) : 0,
        ask_px: Number.isFinite(Number(p?.askPx)) ? Number(p.askPx) : 0,
        bid_sz: Number.isFinite(Number(p?.bidSz)) ? Number(p.bidSz) : 0,
        ask_sz: Number.isFinite(Number(p?.askSz)) ? Number(p.askSz) : 0,
      }))
      .filter((p) => Number.isFinite(p.price) && p.price > 0)
    : [];

  const grpcReq = {
    symbol: String(body.symbol || ''),
    channel: String(body.channel || ''),
    horizon_sec: Number.isFinite(Number(body.horizonSec)) ? Number(body.horizonSec) : 30,
    strategy_mode: String(body.strategyMode || 'market_making'),
    hold_ms: Number.isFinite(Number(body.holdMs)) ? Number(body.holdMs) : 500,
    mm_adverse_ret_threshold: Number.isFinite(Number(body.mmAdverseRetThreshold))
      ? Number(body.mmAdverseRetThreshold)
      : 0.0006,
    mm_one_sided_imbalance_threshold: Number.isFinite(Number(body.mmOneSidedImbalanceThreshold))
      ? Number(body.mmOneSidedImbalanceThreshold)
      : 0.15,
    min_spread_bps: Number.isFinite(Number(body.minSpreadBps)) ? Number(body.minSpreadBps) : 0.8,
    alpha_imbalance_threshold: Number.isFinite(Number(body.alphaImbalanceThreshold))
      ? Number(body.alphaImbalanceThreshold)
      : 0.2,
    alpha_pred_ret_threshold: Number.isFinite(Number(body.alphaPredRetThreshold))
      ? Number(body.alphaPredRetThreshold)
      : 0.0001,
    max_entry_spread_bps: Number.isFinite(Number(body.maxEntrySpreadBps))
      ? Number(body.maxEntrySpreadBps)
      : 3.0,
    points,
  };

  predClient.Predict(grpcReq, { deadline: Date.now() + 2000 }, (err, response) => {
    if (err) {
      res.status(502).json({ ok: false, error: err.message || String(err) });
      return;
    }
    res.json({ ok: true, prediction: response });
  });
});

app.listen(PORT, () => {
  console.log(`web-gateway listening on :${PORT}, PRED_GRPC_TARGET=${PRED_TARGET}`);
});
