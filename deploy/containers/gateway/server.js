const path = require('node:path');
const express = require('express');
const cors = require('cors');

// @grpc/grpc-js does not support "https://" proxy URIs and these services only
// dial internal Docker DNS names. Drop inherited host proxy envs before loading gRPC.
for (const key of [
  'GRPC_PROXY',
  'grpc_proxy',
  'HTTPS_PROXY',
  'https_proxy',
  'HTTP_PROXY',
  'http_proxy',
  'ALL_PROXY',
  'all_proxy',
]) {
  delete process.env[key];
}

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
let isShuttingDown = false;
let shutdownTimer = null;

function log(level, message, extra = {}) {
  const details = Object.entries(extra)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(' ');
  console[level](`[web-gateway] ${message}${details ? ` ${details}` : ''}`);
}

function streamKey(symbol, channel) {
  return `${symbol}::${channel}`;
}

function waitForGrpcReady(client, timeoutMs = 1200) {
  return new Promise((resolve) => {
    client.waitForReady(Date.now() + timeoutMs, (error) => {
      resolve({
        ok: !error,
        error: error ? error.message || String(error) : '',
      });
    });
  });
}

function ensureSubscription(symbol, channel = 'books') {
  if (isShuttingDown) {
    return {
      call: null,
      lastTick: null,
      lastUpdateMs: 0,
      error: 'web-gateway is shutting down',
      listeners: new Set(),
    };
  }
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
    listeners: new Set(),
  };
  subscriptions.set(key, state);

  const call = marketClient.Subscribe({ symbol, channel });
  state.call = call;
  state.error = '';

  call.on('data', (tick) => {
    state.lastTick = tick;
    state.lastUpdateMs = Date.now();
    for (const listener of state.listeners) {
      try {
        listener(tick);
      } catch (_error) {
        // Ignore listener failures; SSE clients are best-effort.
      }
    }
  });

  call.on('error', (err) => {
    state.error = err?.message || String(err);
    state.call = null;
    if (isShuttingDown) {
      return;
    }
    log('error', 'market subscription error', { symbol, channel, error: state.error });
    setTimeout(() => ensureSubscription(symbol, channel), 800);
  });

  call.on('end', () => {
    state.call = null;
    if (isShuttingDown) {
      return;
    }
    log('warn', 'market subscription ended', { symbol, channel });
    setTimeout(() => ensureSubscription(symbol, channel), 800);
  });

  return state;
}

function waitForFirstTick(state, timeoutMs = 900) {
  if (state?.lastTick) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (listener) {
        state.listeners.delete(listener);
      }
      resolve(value);
    };

    const listener = () => finish(true);
    state.listeners.add(listener);
    const timer = setTimeout(() => finish(false), timeoutMs);
  });
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

app.get('/ready', async (_req, res) => {
  const [predReady, marketReady] = await Promise.all([
    waitForGrpcReady(predClient),
    waitForGrpcReady(marketClient),
  ]);
  const ok = predReady.ok && marketReady.ok;
  res.status(ok ? 200 : 503).json({
    ok,
    service: 'web-gateway',
    predTarget: PRED_TARGET,
    marketTarget: MARKET_TARGET,
    predReady,
    marketReady,
  });
});

app.get('/market/latest', async (req, res) => {
  const symbol = String(req.query.symbol || 'BTC-USDT');
  const channel = String(req.query.channel || 'books');
  const state = ensureSubscription(symbol, channel);
  if (!state.lastTick) {
    await waitForFirstTick(state);
  }
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

app.get('/market/stream', (req, res) => {
  const rawSubs = String(req.query.subs || '').trim();
  const subscriptionsRequested = rawSubs
    ? rawSubs
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => {
        const [symbol, channel = 'books'] = item.split(':');
        return {
          symbol: String(symbol || 'BTC-USDT'),
          channel: String(channel || 'books'),
        };
      })
    : [{
      symbol: String(req.query.symbol || 'BTC-USDT'),
      channel: String(req.query.channel || 'books'),
    }];

  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  if (typeof res.flushHeaders === 'function') {
    res.flushHeaders();
  }
  res.write(': connected\n\n');

  const detachFns = [];
  for (const sub of subscriptionsRequested) {
    const state = ensureSubscription(sub.symbol, sub.channel);
    const listener = (tick) => {
      res.write(`event: tick\n`);
      res.write(`data: ${JSON.stringify({
        ok: true,
        symbol: sub.symbol,
        channel: sub.channel,
        tick,
      })}\n\n`);
    };
    state.listeners.add(listener);
    detachFns.push(() => state.listeners.delete(listener));

    if (state.lastTick) {
      listener(state.lastTick);
    }
  }

  const heartbeat = setInterval(() => {
    res.write(`: heartbeat ${Date.now()}\n\n`);
  }, 15000);

  req.on('close', () => {
    clearInterval(heartbeat);
    for (const detach of detachFns) {
      detach();
    }
    res.end();
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

  log('info', 'predict request', {
    symbol: grpcReq.symbol,
    channel: grpcReq.channel,
    modelType: grpcReq.model_type,
    horizonSec: grpcReq.horizon_sec,
    holdMs: grpcReq.hold_ms,
    points: points.length,
    ip: req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '',
    origin: req.headers.origin || '',
    userAgent: req.headers['user-agent'] || '',
  });

  predClient.Predict(grpcReq, { deadline: Date.now() + 2000 }, (err, response) => {
    if (err) {
      log('error', 'predict failed', {
        symbol: grpcReq.symbol,
        channel: grpcReq.channel,
        modelType: grpcReq.model_type,
        points: points.length,
        error: err.message || String(err),
      });
      res.status(502).json({ ok: false, error: err.message || String(err) });
      return;
    }
    log('info', 'predict ok', {
      symbol: grpcReq.symbol,
      channel: grpcReq.channel,
      modelType: grpcReq.model_type,
      points: points.length,
      runtimeModel: response?.model_name || '',
      signal: response?.signal || '',
    });
    res.json({ ok: true, prediction: response });
  });
});

const server = app.listen(PORT, () => {
  log('info', `listening on :${PORT}`, {
    predTarget: PRED_TARGET,
    marketTarget: MARKET_TARGET,
  });
});

function shutdown(signal) {
  if (isShuttingDown) {
    return;
  }
  isShuttingDown = true;

  log('info', 'shutdown requested', {
    signal,
    activeSubscriptions: subscriptions.size,
  });

  for (const state of subscriptions.values()) {
    if (state.call && typeof state.call.cancel === 'function') {
      try {
        state.call.cancel();
      } catch (_error) {
        // Ignore cancellation errors during shutdown.
      }
    }
    state.call = null;
    state.listeners.clear();
  }
  subscriptions.clear();

  if (typeof predClient.close === 'function') {
    predClient.close();
  }
  if (typeof marketClient.close === 'function') {
    marketClient.close();
  }

  shutdownTimer = setTimeout(() => {
    process.exit(0);
  }, 8000);
  if (typeof shutdownTimer.unref === 'function') {
    shutdownTimer.unref();
  }

  server.close(() => {
    if (shutdownTimer) {
      clearTimeout(shutdownTimer);
    }
    process.exit(0);
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
