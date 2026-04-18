const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const WebSocket = require('ws');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const PROTO_PATH = path.join(__dirname, '..', 'proto', 'market_data.proto');
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
let predictionClient;
let grpcStreams = [];
let reconnectTimer;
let simulateTimer;
let lastPrice;
let flushTimer;
const pointBuffer = [];
const POINT_FLUSH_MS = 33;
let isIntentionalGrpcStop = false;
let streamEpoch = 0;

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

function startSimulatedStream(symbol) {
  cleanupStream();
  sendStatus({
    state: 'connecting',
    detail: `Starting simulated stream for ${symbol}`
  });

  let current = Number.isFinite(lastPrice) ? lastPrice : 65000;
  let vol24h = 1200000;
  simulateTimer = setInterval(() => {
    const drift = (Math.random() - 0.5) * 120;
    current = Math.max(1, current + drift);
    vol24h = Math.max(1, vol24h + Math.random() * 40);
    const now = Date.now();
    const change = Number.isFinite(lastPrice) ? current - lastPrice : 0;
    lastPrice = current;
    queuePoint({
      ts: now,
      price: current,
      change,
      source: 'simulated',
      fields: {
        instId: symbol,
        bidPx: (current - 0.3).toFixed(2),
        askPx: (current + 0.3).toFixed(2),
        vol24h: vol24h.toFixed(2),
        high24h: (current + 320).toFixed(2),
        low24h: (current - 320).toFixed(2)
      }
    });
  }, 500);

  sendStatus({
    state: 'connected',
    detail: `Simulated stream active (${symbol})`
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
    const channel = String(config?.channel || 'books5').trim() || 'books5';
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

function normalizePredictionTarget(target) {
  const raw = (target || process.env.PRED_GRPC_TARGET || '127.0.0.1:50061').trim();
  return raw.replace(/^grpc:\/\//, '');
}

function getPredictionClient() {
  const target = normalizePredictionTarget();
  if (!predictionClient) {
    predictionClient = new marketstream.PredictionService(target, grpc.credentials.createInsecure(), {
      'grpc.keepalive_time_ms': 5000,
      'grpc.keepalive_timeout_ms': 2000
    });
  }
  return predictionClient;
}

function inferPredictionGrpc(payload) {
  return new Promise((resolve, reject) => {
    try {
      const client = getPredictionClient();
      const points = Array.isArray(payload?.points)
        ? payload.points
          .map((p) => ({
            ts: Number.isFinite(Number(p?.ts)) ? Number(p.ts) : Date.now(),
            price: Number(p?.price),
            bid_px: Number.isFinite(Number(p?.bidPx)) ? Number(p.bidPx) : 0,
            ask_px: Number.isFinite(Number(p?.askPx)) ? Number(p.askPx) : 0,
            bid_sz: Number.isFinite(Number(p?.bidSz)) ? Number(p.bidSz) : 0,
            ask_sz: Number.isFinite(Number(p?.askSz)) ? Number(p.askSz) : 0
          }))
          .filter((p) => Number.isFinite(p.price) && p.price > 0)
        : [];

      const request = {
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
        points
      };

      client.Predict(request, { deadline: Date.now() + 1200 }, (error, response) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(response);
      });
    } catch (error) {
      reject(error);
    }
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
    const fields = tick.fields ? { ...tick.fields } : {};
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

  if (config && config.simulated) {
    startSimulatedStream(config.symbol || 'BTC-USDT');
    return { ok: true };
  }

  const url = (config?.url || 'grpc://127.0.0.1:50051').trim();
  if (url.startsWith('ws://') || url.startsWith('wss://')) {
    startWebSocketStream({ ...config, url });
  } else {
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
    const response = await inferPredictionGrpc(payload || {});
    return { ok: true, prediction: response };
  } catch (error) {
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
  if (predictionClient) {
    try {
      predictionClient.close();
    } catch (_error) {
      // Ignore close errors on shutdown.
    }
    predictionClient = null;
  }
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
