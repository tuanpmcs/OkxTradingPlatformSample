const path = require('node:path');
const express = require('express');
const cors = require('cors');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const PORT = Number(process.env.PORT || 8080);
const PRED_TARGET = String(process.env.PRED_GRPC_TARGET || 'backend-cpp:50051');
const MARKET_TARGET = String(process.env.MARKET_GRPC_TARGET || PRED_TARGET);
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
const marketClient = new marketstream.MarketData(MARKET_TARGET, grpc.credentials.createInsecure());
const subscriptions = new Map();

function streamKey(symbol, channel) {
  return `${symbol}::${channel}`;
}

function ensureSubscription(symbol, channel = 'books') {
  const key = streamKey(symbol, channel);
  const existing = subscriptions.get(key);
  if (existing?.call) {
    return existing;
  }

  const state = existing || {
    call: null,
    lastTick: null,
    lastUpdateMs: 0,
    error: '',
  };
  subscriptions.set(key, state);

  const call = marketClient.Subscribe({ symbol, channel });
  state.call = call;
  state.error = '';

  call.on('data', (tick) => {
    state.lastTick = tick;
    state.lastUpdateMs = Date.now();
  });

  call.on('error', (err) => {
    state.error = err?.message || String(err);
    state.call = null;
    setTimeout(() => ensureSubscription(symbol, channel), 800);
  });

  call.on('end', () => {
    state.call = null;
    setTimeout(() => ensureSubscription(symbol, channel), 800);
  });

  return state;
}

const app = express();
app.use(cors());
app.use(express.json({ limit: '2mb' }));

app.get('/health', (_req, res) => {
  res.json({
    ok: true,
    service: 'web-gateway',
    predTarget: PRED_TARGET,
    marketTarget: MARKET_TARGET,
  });
});

app.get('/market/latest', (req, res) => {
  const symbol = String(req.query.symbol || 'BTC-USDT');
  const channel = String(req.query.channel || 'books');
  const state = ensureSubscription(symbol, channel);
  const ageMs = state.lastUpdateMs > 0 ? Date.now() - state.lastUpdateMs : -1;

  res.json({
    ok: !!state.lastTick,
    symbol,
    channel,
    ageMs,
    error: state.error || '',
    tick: state.lastTick || null,
  });
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
    model_type: String(body.modelType || 'xgboost'),
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
