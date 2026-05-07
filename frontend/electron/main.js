const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const WebSocket = require('ws');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const protoCandidates = [
  path.join(process.resourcesPath, 'proto', 'market_data.proto'),
  path.join(__dirname, '..', 'proto', 'market_data.proto'),
  path.join(__dirname, '..', '..', 'backend', 'proto', 'market_data.proto')
];
const PROTO_PATH = protoCandidates.find((candidate) => fs.existsSync(candidate));
if (!PROTO_PATH) {
  throw new Error('market_data.proto not found in frontend/proto or backend/proto');
}

const protoDefinition = protoLoader.loadSync(PROTO_PATH, {
  keepCase: true,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true
});
const marketstream = grpc.loadPackageDefinition(protoDefinition).marketstream;

let mainWindow;
let socket;
let grpcClient;
let currentGrpcStreamTarget = '';
let grpcStreams = [];
let reconnectTimer;
let simulateTimer;
let marketPollTimer;
let marketSseAbortController;
let lastPrice;
let flushTimer;
let currentPredictionGrpcTarget = '';
const pointBuffer = [];
// Lower IPC batching delay for faster UI reaction.
const POINT_FLUSH_MS = 8;
let isIntentionalGrpcStop = false;
let streamEpoch = 0;
let currentPredictionHttpTarget = '';

function logPredictionEvent(message, extra = {}) {
  const details = Object.entries(extra)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(' ');
  console.log(`[desktop] ${message}${details ? ` ${details}` : ''}`);
}

function isGrpcClientCancelled(error) {
  if (!error) {
    return false;
  }
  if (error.code === grpc.status.CANCELLED) {
    return true;
  }
  const message = String(error.message || '');
  return message.includes('CANCELLED: Cancelled on client');
}

function sendStatus(payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send('stream:status', payload);
}

function sendData(payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send('stream:data', payload);
}

function flushPoints() {
  flushTimer = null;
  if (!mainWindow || mainWindow.isDestroyed() || pointBuffer.length === 0) {
    return;
  }

  const batch = pointBuffer.splice(0, pointBuffer.length);
  mainWindow.webContents.send('stream:data-batch', batch);
}

function queuePoint(payload) {
  pointBuffer.push(payload);
  if (pointBuffer.length > 5000) {
    pointBuffer.splice(0, pointBuffer.length - 3000);
  }

  if (!flushTimer) {
    flushTimer = setTimeout(flushPoints, POINT_FLUSH_MS);
  }
}

function queuePoints(payloads) {
  if (!Array.isArray(payloads) || payloads.length === 0) {
    return;
  }
  for (const payload of payloads) {
    queuePoint(payload);
  }
}

function cleanupStream() {
  streamEpoch += 1;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (simulateTimer) {
    clearInterval(simulateTimer);
    simulateTimer = null;
  }
  if (marketPollTimer) {
    clearInterval(marketPollTimer);
    marketPollTimer = null;
  }
  if (marketSseAbortController) {
    try {
      marketSseAbortController.abort();
    } catch (_error) {
      // Ignore abort errors during shutdown.
    }
    marketSseAbortController = null;
  }
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  pointBuffer.length = 0;
  if (socket) {
    socket.removeAllListeners();
    socket.terminate();
    socket = null;
  }
  if (grpcStreams.length > 0) {
    isIntentionalGrpcStop = true;
    const streamsToCancel = grpcStreams;
    grpcStreams = [];
    for (const stream of streamsToCancel) {
      stream.removeAllListeners('data');
      stream.removeAllListeners('metadata');
      stream.once('error', () => {});
      stream.once('end', () => {});
      stream.cancel();
      setImmediate(() => {
        stream.removeAllListeners();
      });
    }
  }
  if (grpcClient) {
    try {
      grpcClient.close();
    } catch (_error) {
      // Ignore close errors during shutdown.
    }
  }
  grpcClient = null;
}

function scheduleReconnect(startFn, delayMs = 2000) {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    startFn();
  }, delayMs);
}

function extractPrice(parsed) {
  if (!parsed || !Array.isArray(parsed.data) || parsed.data.length === 0) {
    return null;
  }

  const first = parsed.data[0] || {};
  const candidates = [first.last, first.lastPr, first.px, first.price, first.markPx];

  for (const value of candidates) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) {
      return n;
    }
  }

  return null;
}

function extractDisplayFields(parsed) {
  if (!parsed || !Array.isArray(parsed.data) || parsed.data.length === 0) {
    return {};
  }

  const arg = parsed.arg || {};
  const first = parsed.data[0] || {};
  const bids = Array.isArray(first.bids) && first.bids.length > 0 ? first.bids[0] : null;
  const asks = Array.isArray(first.asks) && first.asks.length > 0 ? first.asks[0] : null;

  return {
    channel: arg.channel ?? null,
    instId: arg.instId ?? first.instId ?? null,
    bidPx: first.bidPx ?? first.bid ?? (Array.isArray(bids) ? bids[0] : null),
    askPx: first.askPx ?? first.ask ?? (Array.isArray(asks) ? asks[0] : null),
    bidSz: first.bidSz ?? (Array.isArray(bids) ? bids[1] : null),
    askSz: first.askSz ?? (Array.isArray(asks) ? asks[1] : null),
    lastPx: first.last ?? first.px ?? first.lastPr ?? null,
    lastSz: first.lastSz ?? first.sz ?? null,
    side: first.side ?? null,
    seqId: first.seqId ?? null,
    ts: first.ts ?? parsed.ts ?? null,
    vol24h: first.vol24h ?? first.volCcy24h ?? null,
    high24h: first.high24h ?? null,
    low24h: first.low24h ?? null,
    tradeId: first.tradeId ?? null
  };
}

function publishPoint(price, source) {
  const now = Date.now();
  const change = Number.isFinite(lastPrice) ? price - lastPrice : 0;
  lastPrice = price;

  queuePoint({
    ts: now,
    price,
    change,
    source
  });
}

function startSimulatedStream(symbol, channel = 'books') {
  cleanupStream();
  sendStatus({
    state: 'connecting',
    detail: `Starting simulated stream for ${channel}:${symbol}`
  });

  const simTickMsRaw = Number(process.env.SIM_TICK_MS || 20);
  const simBurstRaw = Number(process.env.SIM_BURST || 2);
  const simTickMs = Math.max(5, Number.isFinite(simTickMsRaw) ? Math.floor(simTickMsRaw) : 20);
  const simBurst = Math.max(1, Number.isFinite(simBurstRaw) ? Math.floor(simBurstRaw) : 2);
  const simRate = Math.floor((1000 / simTickMs) * simBurst);

  let current = Number.isFinite(lastPrice) ? lastPrice : 65000;
  let vol24h = 1200000;
  let velocity = 0;
  let regimeDrift = 0;
  let tickCounter = 0;
  simulateTimer = setInterval(() => {
    for (let i = 0; i < simBurst; i += 1) {
      tickCounter += 1;
      if (tickCounter % 250 === 0) {
        regimeDrift = (Math.random() - 0.5) * 0.9;
      }

      const meanAnchor = 65000;
      const reversion = (meanAnchor - current) * 0.00006;
      const noise = (Math.random() - 0.5) * 3.4;
      velocity = velocity * 0.92 + regimeDrift + reversion + noise;
      current = Math.max(1, current + velocity);
      vol24h = Math.max(1, vol24h + Math.abs(noise) * 2.4 + Math.random() * 3.2);

      const spread = 0.12 + Math.min(1.2, Math.abs(velocity) * 0.025);
      const bid = current - spread * 0.5;
      const ask = current + spread * 0.5;
      const bidSz = 1.2 + Math.max(0, regimeDrift * 0.8) + Math.random() * 2.2;
      const askSz = 1.2 + Math.max(0, -regimeDrift * 0.8) + Math.random() * 2.2;

      const now = Date.now();
      const change = Number.isFinite(lastPrice) ? current - lastPrice : 0;
      lastPrice = current;
      queuePoint({
        ts: now,
        price: current,
        change,
        source: 'simulated',
        fields: {
          channel,
          instId: symbol,
          bidPx: bid.toFixed(2),
          askPx: ask.toFixed(2),
          bidSz: bidSz.toFixed(4),
          askSz: askSz.toFixed(4),
          vol24h: vol24h.toFixed(2),
          high24h: (current + 220).toFixed(2),
          low24h: (current - 220).toFixed(2)
        }
      });
    }
  }, simTickMs);

  sendStatus({
    state: 'connected',
    detail: `Simulated stream active (${channel}:${symbol}) ~${simRate} msg/s`
  });
}

function normalizeSubscriptions(config) {
  const rawSubs = Array.isArray(config?.subscriptions) ? config.subscriptions : [];
  const dedup = new Map();

  for (const sub of rawSubs) {
    const symbol = String(sub?.symbol || '').trim();
    const channel = String(sub?.channel || '').trim();
    if (!symbol || !channel) {
      continue;
    }
    dedup.set(`${channel}:${symbol}`, { symbol, channel });
  }

  if (dedup.size === 0) {
    const symbol = String(config?.symbol || 'BTC-USDT').trim() || 'BTC-USDT';
    const channel = String(config?.channel || 'books').trim() || 'books';
    dedup.set(`${channel}:${symbol}`, { symbol, channel });
  }

  return [...dedup.values()];
}

function startWebSocketStream(config) {
  cleanupStream();
  const currentEpoch = streamEpoch;

  const wsUrl = config.url;
  const subscriptions = normalizeSubscriptions(config);
  const subText = subscriptions.map((sub) => `${sub.channel}:${sub.symbol}`).join(', ');

  sendStatus({
    state: 'connecting',
    detail: `Connecting websocket ${wsUrl}`
  });

  socket = new WebSocket(wsUrl);

  socket.on('open', () => {
    const args = subscriptions.map((sub) => ({ channel: sub.channel, instId: sub.symbol }));
    const subscribe = { op: 'subscribe', args };
    socket.send(JSON.stringify(subscribe));
    sendStatus({
      state: 'connected',
      detail: `Subscribed to ${subText}`
    });
  });

  socket.on('message', (raw) => {
    try {
      const parsed = JSON.parse(raw.toString());
      const price = extractPrice(parsed);
      if (!Number.isFinite(price)) {
        return;
      }
      const now = Date.now();
      const change = Number.isFinite(lastPrice) ? price - lastPrice : 0;
      lastPrice = price;
      queuePoint({
        ts: now,
        price,
        change,
        source: 'okx-ws',
        fields: extractDisplayFields(parsed)
      });
    } catch (error) {
      sendStatus({
        state: 'warning',
        detail: `Parse warning: ${error.message}`
      });
    }
  });

  socket.on('close', () => {
    if (currentEpoch !== streamEpoch) {
      return;
    }
    sendStatus({
      state: 'disconnected',
      detail: 'Websocket closed, reconnecting in 2s...'
    });
    scheduleReconnect(() => startWebSocketStream(config), 2000);
  });

  socket.on('error', (error) => {
    sendStatus({
      state: 'error',
      detail: `Websocket error: ${error.message}`
    });
  });
}

function normalizeGrpcTarget(url) {
  const raw = (url || '127.0.0.1:50051').trim();
  return raw.replace(/^grpc:\/\//, '');
}

function normalizePredictionHttpUrl(target) {
  const raw = String(
    target
    || currentPredictionHttpTarget
    || process.env.PRED_HTTP_TARGET
    || process.env.INFERENCE_HTTP_URL
    || 'http://127.0.0.1:8081/predict'
  ).trim();
  if (raw.endsWith('/predict') || raw.endsWith('/invocations')) {
    return raw;
  }
  return `${raw.replace(/\/$/, '')}/predict`;
}

function normalizePredictionGrpcTarget(target) {
  const raw = String(
    target
    || currentPredictionGrpcTarget
    || process.env.PRED_GRPC_TARGET
    || process.env.INFERENCE_GRPC_TARGET
    || process.env.PYTHON_INFERENCE_GRPC_TARGET
    || 'grpc://127.0.0.1:50061'
  ).trim();
  return raw.replace(/^grpc:\/\//, '');
}

function deriveGrpcPredictionTargetFromStream(streamUrl) {
  const target = normalizeGrpcTarget(streamUrl);
  const parts = target.split(':');
  if (parts.length < 2) {
    return target;
  }
  parts[parts.length - 1] = '50061';
  return parts.join(':');
}

function normalizeGatewayBaseUrl(target) {
  const raw = String(target || '').trim();
  return raw.replace(/\/$/, '');
}

function normalizeMarketLatestUrl(target) {
  const base = normalizeGatewayBaseUrl(target);
  if (!base) {
    return '';
  }
  if (base.endsWith('/market/latest')) {
    return base;
  }
  return `${base}/market/latest`;
}

function normalizeMarketStreamUrl(target, subscriptions) {
  const base = normalizeGatewayBaseUrl(target);
  if (!base) {
    return '';
  }
  const url = new URL(`${base}/market/stream`);
  const subs = Array.isArray(subscriptions) ? subscriptions : [];
  const encodedSubs = subs
    .map((subscription) => {
      const symbol = String(subscription?.symbol || 'BTC-USDT').trim();
      const channel = String(subscription?.channel || 'books').trim();
      return `${symbol}:${channel}`;
    })
    .filter(Boolean)
    .join(',');
  if (encodedSubs) {
    url.searchParams.set('subs', encodedSubs);
  }
  return url.toString();
}

async function fetchGatewayLatest(baseUrl, subscription) {
  const latestUrl = new URL(normalizeMarketLatestUrl(baseUrl));
  latestUrl.searchParams.set('symbol', String(subscription?.symbol || 'BTC-USDT'));
  latestUrl.searchParams.set('channel', String(subscription?.channel || 'books'));

  const response = await fetch(latestUrl, {
    headers: {
      accept: 'application/json'
    }
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(json?.error || `HTTP ${response.status}`);
  }
  return json;
}

function translateGatewayTickToPoint(payload, fallbackSource = 'gateway-http') {
  const tick = payload?.tick;
  const fields = tick?.fields || {};
  const numericPrice = Number(tick?.price);
  if (!Number.isFinite(numericPrice) || numericPrice <= 0) {
    return null;
  }

  const ts = Number(tick?.ts);
  const now = Number.isFinite(ts) ? ts : Date.now();
  const change = Number.isFinite(lastPrice) ? numericPrice - lastPrice : 0;
  lastPrice = numericPrice;

  return {
    ts: now,
    price: numericPrice,
    change,
    source: tick?.source || fallbackSource,
    fields: {
      channel: fields.channel || payload?.channel || null,
      instId: fields.instId || payload?.symbol || null,
      bidPx: fields.bidPx,
      askPx: fields.askPx,
      bidSz: fields.bidSz,
      askSz: fields.askSz,
      vol24h: fields.vol24h,
      high24h: fields.high24h,
      low24h: fields.low24h,
      side: fields.side,
      seqId: fields.seqId,
      lastPx: fields.lastPx,
      lastSz: fields.lastSz
    },
    changedFields: Array.isArray(tick?.changed_fields) ? tick.changed_fields : []
  };
}

function startGatewayHttpStream(config) {
  cleanupStream();
  const currentEpoch = streamEpoch;
  const subscriptions = normalizeSubscriptions(config);
  const baseUrl = normalizeGatewayBaseUrl(config?.url);
  currentPredictionHttpTarget = `${baseUrl}/predict`;

  sendStatus({
    state: 'connecting',
    detail: `Connecting deployed gateway ${baseUrl}`
  });

  const pollOnce = async () => {
    if (currentEpoch !== streamEpoch) {
      return;
    }
    try {
      const results = await Promise.all(
        subscriptions.map((subscription) => fetchGatewayLatest(baseUrl, subscription))
      );
      const points = results
        .map((result) => translateGatewayTickToPoint(result))
        .filter(Boolean);

      if (points.length > 0) {
        queuePoints(points);
        sendStatus({
          state: 'connected',
          detail: `Gateway polling ${subscriptions.length} subscription${subscriptions.length === 1 ? '' : 's'}`
        });
      } else {
        sendStatus({
          state: 'warning',
          detail: 'Gateway connected, waiting for fresh market ticks...'
        });
      }
    } catch (error) {
      sendStatus({
        state: 'error',
        detail: `Gateway poll error: ${error.message}`
      });
    }
  };

  void pollOnce();
  marketPollTimer = setInterval(() => {
    void pollOnce();
  }, 250);
}

async function startGatewaySseStream(config) {
  cleanupStream();
  const currentEpoch = streamEpoch;
  const subscriptions = normalizeSubscriptions(config);
  const baseUrl = normalizeGatewayBaseUrl(config?.url);
  const streamUrl = normalizeMarketStreamUrl(baseUrl, subscriptions);
  currentPredictionHttpTarget = `${baseUrl}/predict`;

  sendStatus({
    state: 'connecting',
    detail: `Connecting deployed stream ${baseUrl}`
  });

  const controller = new AbortController();
  marketSseAbortController = controller;

  const pushTick = (payload) => {
    const point = translateGatewayTickToPoint(payload, 'gateway-sse');
    if (!point) {
      return;
    }
    queuePoint(point);
  };

  const scheduleSseReconnect = (detail) => {
    if (currentEpoch !== streamEpoch) {
      return;
    }
    sendStatus({
      state: 'disconnected',
      detail
    });
    scheduleReconnect(() => {
      void startGatewaySseStream(config);
    }, 800);
  };

  try {
    const response = await fetch(streamUrl, {
      headers: {
        accept: 'text/event-stream'
      },
      signal: controller.signal
    });

    if (!response.ok || !response.body) {
      throw new Error(`SSE HTTP ${response.status}`);
    }

    sendStatus({
      state: 'connected',
      detail: `Gateway SSE ${subscriptions.length} subscription${subscriptions.length === 1 ? '' : 's'}`
    });

    const decoder = new TextDecoder();
    let buffer = '';

    const handleEventBlock = (block) => {
      const lines = block.split('\n');
      const dataLines = [];
      let eventName = '';
      for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        if (!line || line.startsWith(':')) {
          continue;
        }
        if (line.startsWith('event:')) {
          eventName = line.slice('event:'.length).trim();
          continue;
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice('data:'.length).trim());
        }
      }
      if ((eventName === 'tick' || !eventName) && dataLines.length > 0) {
        try {
          pushTick(JSON.parse(dataLines.join('\n')));
        } catch (error) {
          sendStatus({
            state: 'warning',
            detail: `Gateway SSE parse warning: ${error.message}`
          });
        }
      }
    };

    for await (const chunk of response.body) {
      if (currentEpoch !== streamEpoch || controller.signal.aborted) {
        return;
      }
      buffer += decoder.decode(chunk, { stream: true });
      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex >= 0) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        handleEventBlock(block);
        separatorIndex = buffer.indexOf('\n\n');
      }
    }

    if (currentEpoch === streamEpoch && !controller.signal.aborted) {
      scheduleSseReconnect('Gateway SSE ended, reconnecting...');
    }
  } catch (error) {
    if (controller.signal.aborted || currentEpoch !== streamEpoch) {
      return;
    }
    sendStatus({
      state: 'warning',
      detail: `Gateway SSE unavailable (${error.message}), falling back to polling`
    });
    startGatewayHttpStream(config);
  }
}

async function inferPredictionHttp(payload) {
  const url = normalizePredictionHttpUrl(payload?.predictionUrl || payload?.predictionTarget);
  const request = {
    symbol: String(payload?.symbol || ''),
    channel: String(payload?.channel || ''),
    horizonSec: Number.isFinite(Number(payload?.horizonSec)) ? Number(payload.horizonSec) : 30,
    strategyMode: String(payload?.strategyMode || 'market_making'),
    holdMs: Number.isFinite(Number(payload?.holdMs)) ? Number(payload.holdMs) : 500,
    mmAdverseRetThreshold: Number.isFinite(Number(payload?.mmAdverseRetThreshold))
      ? Number(payload.mmAdverseRetThreshold)
      : 0.0006,
    mmOneSidedImbalanceThreshold: Number.isFinite(Number(payload?.mmOneSidedImbalanceThreshold))
      ? Number(payload.mmOneSidedImbalanceThreshold)
      : 0.15,
    minSpreadBps: Number.isFinite(Number(payload?.minSpreadBps))
      ? Number(payload.minSpreadBps)
      : 0.8,
    alphaImbalanceThreshold: Number.isFinite(Number(payload?.alphaImbalanceThreshold))
      ? Number(payload.alphaImbalanceThreshold)
      : 0.2,
    alphaPredRetThreshold: Number.isFinite(Number(payload?.alphaPredRetThreshold))
      ? Number(payload.alphaPredRetThreshold)
      : 0.0001,
    maxEntrySpreadBps: Number.isFinite(Number(payload?.maxEntrySpreadBps))
      ? Number(payload.maxEntrySpreadBps)
      : 3.0,
    modelType: String(payload?.modelType || 'lightgbm'),
    points: Array.isArray(payload?.points)
      ? payload.points
        .map((p) => ({
          ts: Number.isFinite(Number(p?.ts)) ? Number(p.ts) : Date.now(),
          price: Number(p?.price),
          bidPx: Number.isFinite(Number(p?.bidPx)) ? Number(p.bidPx) : 0,
          askPx: Number.isFinite(Number(p?.askPx)) ? Number(p.askPx) : 0,
          bidSz: Number.isFinite(Number(p?.bidSz)) ? Number(p.bidSz) : 0,
          askSz: Number.isFinite(Number(p?.askSz)) ? Number(p.askSz) : 0
        }))
        .filter((p) => Number.isFinite(p.price) && p.price > 0)
      : []
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request)
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(json?.error || `HTTP ${response.status}`);
  }
  if (!json || typeof json !== 'object') {
    throw new Error('Invalid inference response');
  }
  if (json.ok && json.prediction && typeof json.prediction === 'object') {
    return json.prediction;
  }
  return json;
}

function buildGrpcPredictRequest(payload) {
  return {
    symbol: String(payload?.symbol || ''),
    channel: String(payload?.channel || ''),
    horizon_sec: Number.isFinite(Number(payload?.horizonSec)) ? Number(payload.horizonSec) : 30,
    strategy_mode: String(payload?.strategyMode || 'market_making'),
    hold_ms: Number.isFinite(Number(payload?.holdMs)) ? Number(payload.holdMs) : 500,
    mm_adverse_ret_threshold: Number.isFinite(Number(payload?.mmAdverseRetThreshold))
      ? Number(payload.mmAdverseRetThreshold)
      : 0.0006,
    mm_one_sided_imbalance_threshold: Number.isFinite(Number(payload?.mmOneSidedImbalanceThreshold))
      ? Number(payload.mmOneSidedImbalanceThreshold)
      : 0.15,
    min_spread_bps: Number.isFinite(Number(payload?.minSpreadBps))
      ? Number(payload.minSpreadBps)
      : 0.8,
    alpha_imbalance_threshold: Number.isFinite(Number(payload?.alphaImbalanceThreshold))
      ? Number(payload.alphaImbalanceThreshold)
      : 0.2,
    alpha_pred_ret_threshold: Number.isFinite(Number(payload?.alphaPredRetThreshold))
      ? Number(payload.alphaPredRetThreshold)
      : 0.0001,
    max_entry_spread_bps: Number.isFinite(Number(payload?.maxEntrySpreadBps))
      ? Number(payload.maxEntrySpreadBps)
      : 3.0,
    model_type: String(payload?.modelType || 'xgboost'),
    points: Array.isArray(payload?.points)
      ? payload.points
        .map((p) => ({
          ts: Number.isFinite(Number(p?.ts)) ? Number(p.ts) : Date.now(),
          price: Number(p?.price),
          bid_px: Number.isFinite(Number(p?.bidPx)) ? Number(p.bidPx) : 0,
          ask_px: Number.isFinite(Number(p?.askPx)) ? Number(p.askPx) : 0,
          bid_sz: Number.isFinite(Number(p?.bidSz)) ? Number(p.bidSz) : 0,
          ask_sz: Number.isFinite(Number(p?.askSz)) ? Number(p.askSz) : 0,
          mid_price: Number.isFinite(Number(p?.midPrice)) ? Number(p.midPrice) : 0,
          spread: Number.isFinite(Number(p?.spread)) ? Number(p.spread) : 0,
          rel_spread: Number.isFinite(Number(p?.relSpread)) ? Number(p.relSpread) : 0,
          microprice: Number.isFinite(Number(p?.microprice)) ? Number(p.microprice) : 0,
          imbalance: Number.isFinite(Number(p?.imbalance)) ? Number(p.imbalance) : 0,
          imbalance_l1: Number.isFinite(Number(p?.imbalanceL1)) ? Number(p.imbalanceL1) : 0,
          imbalance_l5: Number.isFinite(Number(p?.imbalanceL5)) ? Number(p.imbalanceL5) : 0,
          bid_vol_l5: Number.isFinite(Number(p?.bidVolL5)) ? Number(p.bidVolL5) : 0,
          ask_vol_l5: Number.isFinite(Number(p?.askVolL5)) ? Number(p.askVolL5) : 0,
          weighted_bid_depth: Number.isFinite(Number(p?.weightedBidDepth)) ? Number(p.weightedBidDepth) : 0,
          weighted_ask_depth: Number.isFinite(Number(p?.weightedAskDepth)) ? Number(p.weightedAskDepth) : 0,
          trade_count: Number.isFinite(Number(p?.tradeCount)) ? Number(p.tradeCount) : 0,
          trade_volume: Number.isFinite(Number(p?.tradeVolume)) ? Number(p.tradeVolume) : 0,
          trade_imbalance: Number.isFinite(Number(p?.tradeImbalance)) ? Number(p.tradeImbalance) : 0,
          trade_vwap_dev_from_mid: Number.isFinite(Number(p?.tradeVwapDevFromMid)) ? Number(p.tradeVwapDevFromMid) : 0,
          delta_mid_price: Number.isFinite(Number(p?.deltaMidPrice)) ? Number(p.deltaMidPrice) : 0,
          delta_spread: Number.isFinite(Number(p?.deltaSpread)) ? Number(p.deltaSpread) : 0,
          delta_imbalance_l5: Number.isFinite(Number(p?.deltaImbalanceL5)) ? Number(p.deltaImbalanceL5) : 0,
          is_snapshot: Number.isFinite(Number(p?.isSnapshot)) ? Number(p.isSnapshot) : 0,
          is_update: Number.isFinite(Number(p?.isUpdate)) ? Number(p.isUpdate) : 0
        }))
        .filter((p) => Number.isFinite(p.price) && p.price > 0)
      : []
  };
}

async function inferPredictionGrpc(payload) {
  const target = normalizePredictionGrpcTarget(payload?.predictionTarget);
  const request = buildGrpcPredictRequest(payload);
  const client = new marketstream.PredictionService(target, grpc.credentials.createInsecure(), {
    'grpc.keepalive_time_ms': 5000,
    'grpc.keepalive_timeout_ms': 2000,
    'grpc.initial_reconnect_backoff_ms': 200,
    'grpc.min_reconnect_backoff_ms': 200,
    'grpc.max_reconnect_backoff_ms': 2000
  });

  return await new Promise((resolve, reject) => {
    client.waitForReady(Date.now() + 1500, (readyError) => {
      if (readyError) {
        client.close();
        reject(readyError);
        return;
      }
      client.Predict(request, (error, response) => {
        client.close();
        if (error) {
          reject(error);
          return;
        }
        resolve(response);
      });
    });
  });
}

function attachGrpcSubscription(client, config, subscription, currentEpoch) {
  const symbol = subscription.symbol;
  const channel = subscription.channel;
  const stream = client.Subscribe({ symbol, channel });
  grpcStreams.push(stream);

  stream.on('metadata', () => {
    if (currentEpoch !== streamEpoch || !grpcStreams.includes(stream)) {
      return;
    }
    sendStatus({
      state: 'connected',
      detail: `gRPC subscribed to ${channel}:${symbol}`
    });
  });

  stream.on('data', (tick) => {
    if (currentEpoch !== streamEpoch || !grpcStreams.includes(stream)) {
      return;
    }
    const ts = Number(tick.ts);
    const srcFields = tick.fields || {};
    const fields = {
      channel: srcFields.channel,
      instId: srcFields.instId,
      bidPx: srcFields.bidPx,
      askPx: srcFields.askPx,
      bidSz: srcFields.bidSz,
      askSz: srcFields.askSz,
      vol24h: srcFields.vol24h,
      high24h: srcFields.high24h,
      low24h: srcFields.low24h,
      side: srcFields.side,
      seqId: srcFields.seqId
    };
    const changedFields = Array.isArray(tick.changed_fields) ? tick.changed_fields : [];
    queuePoint({
      ts: Number.isFinite(ts) ? ts : Date.now(),
      price: Number(tick.price),
      change: Number(tick.change),
      source: tick.source || 'cxx-grpc',
      fields,
      changedFields
    });
  });

  stream.on('error', (error) => {
    if (currentEpoch !== streamEpoch) {
      return;
    }
    if (isGrpcClientCancelled(error) || isIntentionalGrpcStop) {
      return;
    }
    sendStatus({
      state: 'error',
      detail: `gRPC error (${channel}:${symbol}): ${error.message}`
    });
    scheduleReconnect(() => startGrpcStream(config), 300);
  });

  stream.on('end', () => {
    if (currentEpoch !== streamEpoch) {
      return;
    }
    if (isIntentionalGrpcStop) {
      return;
    }
    if (reconnectTimer) {
      return;
    }
    sendStatus({
      state: 'disconnected',
      detail: 'gRPC stream ended, reconnecting...'
    });
    scheduleReconnect(() => startGrpcStream(config), 300);
  });
}

function startGrpcStream(config) {
  cleanupStream();
  isIntentionalGrpcStop = false;
  const currentEpoch = streamEpoch;
  const subscriptions = normalizeSubscriptions(config);

  const target = normalizeGrpcTarget(config.url);
  currentGrpcStreamTarget = target;

  sendStatus({
    state: 'connecting',
    detail: `Connecting gRPC ${target}`
  });

  grpcClient = new marketstream.MarketData(target, grpc.credentials.createInsecure(), {
    'grpc.keepalive_time_ms': 5000,
    'grpc.keepalive_timeout_ms': 2000,
    'grpc.initial_reconnect_backoff_ms': 200,
    'grpc.min_reconnect_backoff_ms': 200,
    'grpc.max_reconnect_backoff_ms': 2000
  });
  const currentClient = grpcClient;

  grpcClient.waitForReady(Date.now() + 1000, (readyError) => {
    if (grpcClient !== currentClient) {
      return;
    }
    if (readyError) {
      sendStatus({
        state: 'error',
        detail: `gRPC not ready: ${readyError.message}`
      });
      scheduleReconnect(() => startGrpcStream(config), 300);
      return;
    }
    for (const subscription of subscriptions) {
      attachGrpcSubscription(currentClient, config, subscription, currentEpoch);
    }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 960,
    minHeight: 700,
    backgroundColor: '#081018',
    title: 'Pulse Desk',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(resolveRendererEntry());
}

function resolveRendererEntry() {
  const customPath = process.env.PULSE_UI_PATH;
  const candidates = [
    customPath,
    path.join(__dirname, 'index.html'),
    path.join(__dirname, 'lovable-export', 'dist', 'index.html'),
    path.join(__dirname, 'lovable-export', 'index.html')
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return path.join(__dirname, 'index.html');
}

ipcMain.handle('stream:start', async (_event, config) => {
  lastPrice = undefined;
  currentPredictionHttpTarget = '';
  currentPredictionGrpcTarget = '';

  if (config && config.simulated) {
    const subs = normalizeSubscriptions(config);
    const primary = subs[0] || { symbol: config.symbol || 'BTC-USDT', channel: 'books' };
    startSimulatedStream(primary.symbol || 'BTC-USDT', primary.channel || 'books');
    return { ok: true };
  }

  const url = (config?.url || 'grpc://127.0.0.1:50051').trim();
  if (url.startsWith('ws://') || url.startsWith('wss://')) {
    startWebSocketStream({ ...config, url });
  } else if (url.startsWith('http://') || url.startsWith('https://')) {
    if (config?.predictionTarget) {
      currentPredictionGrpcTarget = normalizePredictionGrpcTarget(config.predictionTarget);
    }
    void startGatewaySseStream({ ...config, url });
  } else {
    currentPredictionGrpcTarget = normalizePredictionGrpcTarget(
      config?.predictionTarget || deriveGrpcPredictionTargetFromStream(url)
    );
    startGrpcStream({ ...config, url });
  }

  return { ok: true };
});

ipcMain.handle('stream:stop', async () => {
  cleanupStream();
  sendStatus({
    state: 'disconnected',
    detail: 'Stream stopped'
  });
  return { ok: true };
});

ipcMain.handle('prediction:infer', async (_event, payload) => {
  try {
    const rawTarget = String(
      payload?.predictionTarget
      || currentPredictionGrpcTarget
      || currentPredictionHttpTarget
      || process.env.PRED_GRPC_TARGET
      || process.env.INFERENCE_GRPC_TARGET
      || process.env.PRED_HTTP_TARGET
      || process.env.INFERENCE_HTTP_URL
      || ''
    ).trim();
    const useGrpc = rawTarget.startsWith('grpc://') || (!rawTarget.startsWith('http://') && !rawTarget.startsWith('https://'));
    logPredictionEvent('prediction request', {
      symbol: String(payload?.symbol || ''),
      channel: String(payload?.channel || ''),
      modelType: String(payload?.modelType || 'xgboost'),
      target: rawTarget || '<default>',
      transport: useGrpc ? 'grpc' : 'http',
      points: Array.isArray(payload?.points) ? payload.points.length : 0
    });
    const response = useGrpc
      ? await inferPredictionGrpc({ ...(payload || {}), predictionTarget: rawTarget })
      : await inferPredictionHttp({ ...(payload || {}), predictionTarget: rawTarget });
    logPredictionEvent('prediction response', {
      requestedModelType: String(payload?.modelType || 'xgboost'),
      runtimeModel: String(response?.model_name || response?.modelName || ''),
      signal: String(response?.signal || ''),
      target: rawTarget || '<default>',
      transport: useGrpc ? 'grpc' : 'http'
    });
    return { ok: true, prediction: response };
  } catch (error) {
    logPredictionEvent('prediction error', {
      symbol: String(payload?.symbol || ''),
      channel: String(payload?.channel || ''),
      modelType: String(payload?.modelType || 'xgboost'),
      target: String(
        payload?.predictionTarget
        || currentPredictionGrpcTarget
        || currentPredictionHttpTarget
        || '<default>'
      ),
      error: error?.message || String(error)
    });
    return {
      ok: false,
      error: error?.message || String(error)
    };
  }
});

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  cleanupStream();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

process.on('uncaughtException', (error) => {
  if (isGrpcClientCancelled(error)) {
    return;
  }
  console.error('[main] uncaughtException', error);
});

process.on('unhandledRejection', (reason) => {
  if (isGrpcClientCancelled(reason)) {
    return;
  }
  console.error('[main] unhandledRejection', reason);
});
