const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const latestPrice = document.getElementById('latest-price');
const bestBid = document.getElementById('best-bid');
const bestAsk = document.getElementById('best-ask');
const vol24h = document.getElementById('vol-24h');
const high24h = document.getElementById('high-24h');
const low24h = document.getElementById('low-24h');
const messageRate = document.getElementById('msg-rate');
const sourceText = document.getElementById('source-text');
const changedFields = document.getElementById('changed-fields');
const channelChangeList = document.getElementById('channel-change-list');
const grpcChartCanvas = document.getElementById('grpc-chart-canvas');
const grpcChartMeta = document.getElementById('grpc-chart-meta');
const simAccountInput = document.getElementById('sim-account-input');
const simCapitalInput = document.getElementById('sim-capital-input');
const simModelSelect = document.getElementById('sim-model-select');
const simConfigSelect = document.getElementById('sim-config-select');
const simStrategySelect = document.getElementById('sim-strategy-select');
const simHorizonInput = document.getElementById('sim-horizon-input');
const simHoldMsInput = document.getElementById('sim-hold-ms-input');
const simRangeInput = document.getElementById('sim-range-input');
const simImbalanceInput = document.getElementById('sim-imbalance-input');
const simAdverseInput = document.getElementById('sim-adverse-input');
const simMinSpreadInput = document.getElementById('sim-min-spread-input');
const simModelBadge = document.getElementById('sim-model-badge');
const simModeBadge = document.getElementById('sim-mode-badge');
const simAutoBadge = document.getElementById('sim-auto-badge');
const simRuleHint = document.getElementById('sim-rule-hint');
const simAdverseTitle = document.getElementById('sim-adverse-title');
const simAdverseHelp = document.getElementById('sim-adverse-help');
const simMinSpreadWrap = document.getElementById('sim-min-spread-wrap');
const simAdverseWrap = document.getElementById('sim-adverse-wrap');
const simMmOneSidedValue = document.getElementById('sim-mm-one-sided-value');
const simAlphaConfirmValue = document.getElementById('sim-alpha-confirm-value');
const simMaxEntrySpreadValue = document.getElementById('sim-max-entry-spread-value');
const simAlphaCooldownValue = document.getElementById('sim-alpha-cooldown-value');
const simDecisionBasis = document.getElementById('sim-decision-basis');
const simPredictBtn = document.getElementById('sim-predict-btn');
const simAutoStartBtn = document.getElementById('sim-auto-start-btn');
const simAutoStopBtn = document.getElementById('sim-auto-stop-btn');
const simAccountResetBtn = document.getElementById('sim-account-reset-btn');
const simSummary = document.getElementById('sim-summary');
const simSignal = document.getElementById('sim-signal');
const simPredPrice = document.getElementById('sim-pred-price');
const simPredRet = document.getElementById('sim-pred-ret');
const simExpPnl = document.getElementById('sim-exp-pnl');
const simLivePnl = document.getElementById('sim-live-pnl');
const simLiveEquity = document.getElementById('sim-live-equity');
const simPosition = document.getElementById('sim-position');
const simTotalPnl = document.getElementById('sim-total-pnl');
const simTradeCount = document.getElementById('sim-trade-count');
const simAccountCash = document.getElementById('sim-account-cash');
const simAccountEquity = document.getElementById('sim-account-equity');
const simAccountAction = document.getElementById('sim-account-action');

const subscriptionRows = document.getElementById('subscription-rows');
const addRowBtn = document.getElementById('add-row-btn');
const gatewayPresetSelect = document.getElementById('gateway-preset-select');
const urlInput = document.getElementById('url-input');
const predictionTargetInput = document.getElementById('prediction-target-input');
const connectBtn = document.getElementById('connect-btn');
const simulateBtn = document.getElementById('simulate-btn');
const stopBtn = document.getElementById('stop-btn');
const GATEWAY_PRESET_STORAGE_KEY = 'pulseDesk.gatewayPreset';
const URL_STORAGE_KEY = 'pulseDesk.streamUrl';
const PREDICTION_TARGET_STORAGE_KEY = 'pulseDesk.predictionTarget';
const MODEL_TYPE_STORAGE_KEY = 'pulseDesk.modelType';
const GATEWAY_PRESETS = {
  local: 'grpc://127.0.0.1:50051',
  'aws-ec2': 'http://hft-loadbalancer-1038079046.us-east-2.elb.amazonaws.com',
  'aws-fargate': 'http://hft-fargate-alb-36714288.us-east-2.elb.amazonaws.com'
};

const msgTimestamps = [];
const pointQueue = [];
let latestPoint = null;
const channelChanges = new Map();
const grpcSeriesByKey = new Map();
let activeGrpcSeriesKey = '';
let latestGrpcSeriesKey = '';
let grpcCanvasCssWidth = 0;
let grpcCanvasCssHeight = 0;
let grpcResizeObserver = null;
const PREBUILT_MODEL = {
  name: 'PulseLinearV1-Fallback',
  intercept: 0.00002,
  weights: {
    momentum5: 0.62,
    momentum20: 0.38,
    volatility20: -0.25,
    range20: -0.06
  }
};
const MODEL_OPTIONS = {
  lightgbm: 'LightGBM',
  xgboost: 'XGBoost'
};
const CONFIG_PROFILES = {
  market_maker: {
    label: 'Market Maker',
    strategy: 'market_making',
    capital: '5,000',
    holdMs: 100,
    horizonMs: 100,
    autoRangeSec: 600,
    imbalanceThreshold: 0.2,
    adverseThreshold: 0.00025,
    minSpreadBps: 0.8,
    alphaCooldownMs: 250,
    summary: 'Config Market Maker applied: balanced quoting with adverse-selection protection.'
  }
};
const predictionState = {
  pending: false,
  pendingStartedAt: 0,
  lastRequestAt: 0,
  lastSuccessAt: 0,
  totalRequests: 0,
  totalFailures: 0,
  lastLatencyMs: 0,
  lastResult: null,
  lastError: '',
  lastRequestedModelType: 'xgboost'
};
const PREDICTION_POINTS_MAX = 80;
const PREDICTION_STUCK_MS = 2200;
let predictionPollTimer = null;
let predictionSeriesKeyHint = '';
const CHANNEL_OPTIONS = [
  'bbo-tbt',
  'books5',
  'books',
  'trades',
  'tickers',
  'candle1m',
  'mark-price',
  'index-tickers',
  'open-interest',
  'funding-rate',
  'estimated-price',
  'liquidation-orders',
  'trades-all'
];

const simulator = window.PulseSimulator.create({
  elements: {
    simAccountInput,
    simCapitalInput,
    simModelSelect,
    simConfigSelect,
    simStrategySelect,
    simHorizonInput,
    simHoldMsInput,
    simRangeInput,
    simImbalanceInput,
    simAdverseInput,
    simMinSpreadInput,
    simModelBadge,
    simModeBadge,
    simAutoBadge,
    simRuleHint,
    simAdverseTitle,
    simAdverseHelp,
    simMinSpreadWrap,
    simAdverseWrap,
    simMmOneSidedValue,
    simAlphaConfirmValue,
    simMaxEntrySpreadValue,
    simAlphaCooldownValue,
    simDecisionBasis,
    simSummary,
    simSignal,
    simPredPrice,
    simPredRet,
    simExpPnl,
    simLivePnl,
    simLiveEquity,
    simPosition,
    simTotalPnl,
    simTradeCount,
    simAccountCash,
    simAccountEquity,
    simAccountAction
  },
  modelOptions: MODEL_OPTIONS,
  configProfiles: CONFIG_PROFILES,
  callbacks: {
    requestPrediction: (series, force) => requestPrediction(series, force, predictionSeriesKeyHint || activeGrpcSeriesKey),
    getLastPrediction: () => predictionState.lastResult,
    getPredictionError: () => predictionState.lastError,
    getLastRequestedModelType: () => predictionState.lastRequestedModelType,
    onAutoTradingChange: (running) => {
      if (running) {
        void requestActiveSeriesPrediction(true);
        startPredictionPolling();
      } else {
        stopPredictionPolling();
      }
    },
    resolveActiveSeries: () => resolveActiveSeries(),
    getSeriesByKey: (key) => grpcSeriesByKey.get(key),
    getActiveSeriesKey: () => activeGrpcSeriesKey
  }
});

function escapeHtml(input) {
  return String(input)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildPointKey(point) {
  const fields = point?.fields || {};
  const channel = fields.channel || 'unknown';
  const instId = fields.instId || 'unknown';
  return `${channel}:${instId}`;
}
function normalizeKey(text) {
  return String(text || '').trim().toLowerCase();
}
function formatNumber(value, fractionDigits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return '-';
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: fractionDigits });
}

function formatClockTime(ts) {
  const d = new Date(Number(ts));
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  const ss = String(d.getUTCSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss} UTC`;
}

function pctChange(newValue, oldValue) {
  if (!Number.isFinite(newValue) || !Number.isFinite(oldValue) || oldValue === 0) {
    return 0;
  }
  return (newValue - oldValue) / oldValue;
}

function ema(values, alpha) {
  if (!Array.isArray(values) || values.length === 0) {
    return 0;
  }
  let acc = Number(values[0]) || 0;
  for (let i = 1; i < values.length; i += 1) {
    const v = Number(values[i]) || acc;
    acc = alpha * v + (1 - alpha) * acc;
  }
  return acc;
}

function std(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return 0;
  }
  let mean = 0;
  for (const v of values) {
    mean += Number(v) || 0;
  }
  mean /= values.length;
  let varSum = 0;
  for (const v of values) {
    const d = (Number(v) || 0) - mean;
    varSum += d * d;
  }
  return Math.sqrt(varSum / values.length);
}

function updateRate(now) {
  msgTimestamps.push(now);
  const minTs = now - 5000;
  while (msgTimestamps.length && msgTimestamps[0] < minTs) {
    msgTimestamps.shift();
  }
  messageRate.textContent = (msgTimestamps.length / 5).toFixed(2);
}

function updateStatus(state, detail) {
  statusPill.className = `status-pill status-${state || 'idle'}`;
  statusPill.textContent = state || 'idle';
  statusText.textContent = detail || '';
}

function queuePoints(points) {
  for (const point of points) {
    pointQueue.push(point);
  }

  // UI is for observability; prefer freshest data over replaying stale backlog.
  if (pointQueue.length > 2000) {
    pointQueue.splice(0, pointQueue.length - 600);
  }
}

function appendGrpcPoint(point) {
  const numericPrice = Number(point?.price);
  if (!Number.isFinite(numericPrice) || numericPrice <= 0) {
    return;
  }
  const fields = point?.fields || {};
  const key = buildPointKey(point);
  if (!grpcSeriesByKey.has(key)) {
    grpcSeriesByKey.set(key, []);
  }
  const series = grpcSeriesByKey.get(key);
  series.push({
    ts: Number(point?.ts) || Date.now(),
    price: numericPrice,
    bidPx: Number(fields.bidPx),
    askPx: Number(fields.askPx),
    bidSz: Number(fields.bidSz),
    askSz: Number(fields.askSz)
  });
  latestGrpcSeriesKey = key;
  if (series.length > 480) {
    series.splice(0, series.length - 480);
  }
}

function renderStats(point) {
  if (!point) {
    return;
  }

  latestPrice.textContent = `$${formatNumber(point.price, 2)}`;
  bestBid.textContent = point.fields?.bidPx != null ? `$${formatNumber(point.fields.bidPx, 2)}` : '-';
  bestAsk.textContent = point.fields?.askPx != null ? `$${formatNumber(point.fields.askPx, 2)}` : '-';
  vol24h.textContent = point.fields?.vol24h != null ? formatNumber(point.fields.vol24h, 2) : '-';
  high24h.textContent = point.fields?.high24h != null ? `$${formatNumber(point.fields.high24h, 2)}` : '-';
  low24h.textContent = point.fields?.low24h != null ? `$${formatNumber(point.fields.low24h, 2)}` : '-';
  sourceText.textContent = point.source || '-';

  const currentFields = point.fields || {};
  const changed = Array.isArray(point.changedFields) && point.changedFields.length > 0
    ? point.changedFields
    : Object.keys(currentFields);

  const channelName = currentFields.channel || 'unknown';
  const instId = currentFields.instId || 'unknown';
  const rowKey = `${channelName}:${instId}`;
  changedFields.textContent = rowKey;

  channelChanges.set(rowKey, {
    channel: channelName,
    instId,
    price: point.price,
    change: point.change,
    changed,
    ts: point.ts || Date.now()
  });
  renderChannelChanges();
}

function renderChannelChanges() {
  if (channelChanges.size === 0) {
    channelChangeList.textContent = 'No channel updates yet.';
    return;
  }

  const rows = [...channelChanges.entries()]
    .sort((a, b) => b[1].ts - a[1].ts)
    .map(([key, data]) => {
      const fieldsText = data.changed.length > 0 ? data.changed.join(', ') : '-';
      const delta = Number.isFinite(Number(data.change)) ? Number(data.change).toFixed(2) : '-';
      const price = Number.isFinite(Number(data.price)) ? Number(data.price).toFixed(2) : '-';
      return `<div class="channel-row">
        <div class="channel-name">${escapeHtml(key)}</div>
        <div class="channel-fields">
          <div class="channel-metrics">price=${escapeHtml(price)} | change=${escapeHtml(delta)}</div>
          <div class="channel-fields-line">changed: ${escapeHtml(fieldsText)}</div>
        </div>
      </div>`;
    });

  channelChangeList.innerHTML = rows.join('');
}

function createSubscriptionRow(defaults = {}) {
  const row = document.createElement('div');
  row.className = 'subscription-row';
  row.innerHTML = `
    <input class="sub-symbol" placeholder="Symbol (e.g. BTC-USDT)" value="${escapeHtml(defaults.symbol || 'BTC-USDT')}" />
    <select class="sub-channel">
      ${CHANNEL_OPTIONS.map((channel) => `<option value="${channel}" ${channel === (defaults.channel || 'books') ? 'selected' : ''}>${channel}</option>`).join('')}
    </select>
    <button type="button" class="btn btn-ghost btn-sm remove-row-btn">Remove</button>
  `;

  const removeBtn = row.querySelector('.remove-row-btn');
  removeBtn.addEventListener('click', () => {
    if (subscriptionRows.children.length <= 1) {
      return;
    }
    row.remove();
  });
  return row;
}

function getSubscriptions() {
  const rows = [...subscriptionRows.querySelectorAll('.subscription-row')];
  const subscriptions = rows
    .map((row) => {
      const symbol = row.querySelector('.sub-symbol')?.value?.trim();
      const channel = row.querySelector('.sub-channel')?.value?.trim();
      if (!symbol || !channel) {
        return null;
      }
      return { symbol, channel };
    })
    .filter(Boolean);

  if (subscriptions.length === 0) {
    return [{ symbol: 'BTC-USDT', channel: 'books' }];
  }
  return subscriptions;
}

function channelPriority(channel) {
  const value = normalizeKey(channel);
  if (value === 'bbo-tbt') return 0;
  if (value === 'trades' || value === 'trades-all') return 1;
  if (value === 'books5') return 2;
  if (value === 'books') return 3;
  return 4;
}

function selectBestSeriesKeyFromKeys(keys = []) {
  let best = null;
  for (const key of keys) {
    const [channel = ''] = String(key || '').split(':');
    const score = channelPriority(channel);
    if (!best || score < best.score) {
      best = { key, score };
    }
  }
  return best?.key || '';
}

function pickActiveGrpcSeriesKey(subscriptions = []) {
  if (subscriptions.length > 0) {
    const keys = subscriptions.map((sub) => `${sub.channel}:${sub.symbol}`);
    activeGrpcSeriesKey = selectBestSeriesKeyFromKeys(keys);
    return;
  }
  if (!activeGrpcSeriesKey && grpcSeriesByKey.size > 0) {
    activeGrpcSeriesKey = selectBestSeriesKeyFromKeys([...grpcSeriesByKey.keys()]);
  }
}

function resolveActiveSeries() {
  if (grpcSeriesByKey.size === 0) {
    return null;
  }

  if (activeGrpcSeriesKey && grpcSeriesByKey.has(activeGrpcSeriesKey)) {
    return { key: activeGrpcSeriesKey, series: grpcSeriesByKey.get(activeGrpcSeriesKey) };
  }

  const want = normalizeKey(activeGrpcSeriesKey);
  if (want) {
    for (const [key, series] of grpcSeriesByKey.entries()) {
      if (normalizeKey(key) === want) {
        activeGrpcSeriesKey = key;
        return { key, series };
      }
    }
  }

  if (latestGrpcSeriesKey && grpcSeriesByKey.has(latestGrpcSeriesKey)) {
    activeGrpcSeriesKey = latestGrpcSeriesKey;
    return { key: latestGrpcSeriesKey, series: grpcSeriesByKey.get(latestGrpcSeriesKey) };
  }

  const preferredKey = selectBestSeriesKeyFromKeys([...grpcSeriesByKey.keys()]);
  if (preferredKey && grpcSeriesByKey.has(preferredKey)) {
    activeGrpcSeriesKey = preferredKey;
    return { key: preferredKey, series: grpcSeriesByKey.get(preferredKey) };
  }

  const [fallbackKey, fallbackSeries] = grpcSeriesByKey.entries().next().value;
  activeGrpcSeriesKey = fallbackKey;
  return { key: fallbackKey, series: fallbackSeries };
}

function calculatePrediction(series) {
  if (!Array.isArray(series) || series.length < 8) {
    return null;
  }
  const prices = series.map((x) => x.price);
  const last = prices[prices.length - 1];
  const p5 = prices[Math.max(0, prices.length - 6)];
  const p20 = prices[Math.max(0, prices.length - 8)];
  const recent20 = prices.slice(-Math.min(20, prices.length));
  const recent60 = prices.slice(-Math.min(60, prices.length));
  const max20 = Math.max(...recent20);
  const min20 = Math.min(...recent20);
  const mean20 = recent20.reduce((acc, x) => acc + x, 0) / recent20.length;
  const std20 = std(recent20);
  const std60 = std(recent60);
  const ema12 = ema(prices.slice(-Math.min(24, prices.length)), 0.18);
  const ema26 = ema(prices.slice(-Math.min(52, prices.length)), 0.08);
  const trend = last !== 0 ? (ema12 - ema26) / last : 0;
  const zScore = std20 > 0 ? (last - mean20) / std20 : 0;

  const features = {
    momentum5: pctChange(last, p5),
    momentum20: pctChange(last, p20),
    volatility20: mean20 !== 0 ? std20 / mean20 : 0,
    range20: mean20 !== 0 ? (max20 - min20) / mean20 : 0,
    trend,
    zScore,
    volatility60: mean20 !== 0 ? std60 / mean20 : 0
  };

  let score = PREBUILT_MODEL.intercept
    + PREBUILT_MODEL.weights.momentum5 * features.momentum5
    + PREBUILT_MODEL.weights.momentum20 * features.momentum20
    + PREBUILT_MODEL.weights.volatility20 * features.volatility20
    + PREBUILT_MODEL.weights.range20 * features.range20;
  score += 0.32 * features.trend;
  score += -0.06 * (features.zScore / 3.0);
  score += -0.12 * features.volatility60;

  const latest = series[series.length - 1];
  const bidPx = Number(latest?.bidPx);
  const askPx = Number(latest?.askPx);
  const bidSz = Number(latest?.bidSz);
  const askSz = Number(latest?.askSz);
  let spreadRet = 0;
  let imbalance = 0;
  if (Number.isFinite(bidPx) && Number.isFinite(askPx) && askPx > bidPx) {
    const mid = 0.5 * (bidPx + askPx);
    if (mid > 0) {
      spreadRet = (askPx - bidPx) / mid;
    }
  }
  if (Number.isFinite(bidSz) && Number.isFinite(askSz) && bidSz + askSz > 0) {
    imbalance = (bidSz - askSz) / (bidSz + askSz);
  }
  score += 0.06 * imbalance;
  score -= 0.35 * spreadRet;

  // Adaptive cap for fallback return: scales with observed micro-volatility/range.
  const adaptiveCap = clamp(
    Math.max(0.0005, features.volatility20 * 4.0 + features.range20 * 0.35),
    0.0005,
    0.01
  );
  const bounded = clamp(score, -adaptiveCap, adaptiveCap);
  const predictedPrice = last * (1 + bounded);

  // Signal threshold should beat noise and a fraction of current spread.
  const signalThreshold = clamp(
    Math.max(0.00005, features.volatility20 * 1.5, spreadRet * 0.6),
    0.00005,
    adaptiveCap * 0.8
  );
  let signal = 'HOLD';
  if (bounded > signalThreshold) signal = 'LONG';
  else if (bounded < -signalThreshold) signal = 'SHORT';

  return {
    signal,
    score: bounded,
    predictedReturn: bounded,
    lastPrice: last,
    predictedPrice,
    modelName: PREBUILT_MODEL.name,
    detail: 'local adaptive fallback model v2'
  };
}

function toGrpcPrediction(result) {
  if (!result) {
    return null;
  }
  const lastPrice = Number(result.last_price);
  const predictedPrice = Number(result.predicted_price);
  const predictedReturn = Number(result.predicted_return);
  if (!Number.isFinite(lastPrice) || !Number.isFinite(predictedPrice)) {
    return null;
  }
  return {
    signal: result.signal || (predictedPrice > lastPrice ? 'BUY' : 'HOLD'),
    score: Number.isFinite(predictedReturn) ? predictedReturn : 0,
    predictedReturn: Number.isFinite(predictedReturn) ? predictedReturn : 0,
    lastPrice,
    predictedPrice,
    modelName: result.model_name || 'PredictionService',
    detail: result.detail || ''
  };
}

function normalizePredictionSeriesKey(seriesKey) {
  const [rawChannel = '', rawSymbol = ''] = String(seriesKey || '').split(':');
  const symbol = rawSymbol || 'BTC-USDT';
  let channel = rawChannel;

  if (!channel || channel === 'unknown') {
    const [activeChannel = ''] = String(activeGrpcSeriesKey || '').split(':');
    if (activeChannel && activeChannel !== 'unknown') {
      channel = activeChannel;
    } else {
      const best = selectBestSeriesKeyFromKeys([...grpcSeriesByKey.keys()]);
      const [bestChannel = ''] = String(best || '').split(':');
      channel = bestChannel || 'books';
    }
  }

  return `${channel}:${symbol}`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeEndpointInput(raw) {
  const value = String(raw || '').trim();
  if (!value) {
    return 'grpc://127.0.0.1:50051';
  }
  if (
    value.startsWith('grpc://')
    || value.startsWith('ws://')
    || value.startsWith('wss://')
    || value.startsWith('http://')
    || value.startsWith('https://')
  ) {
    return value;
  }
  if (value.includes('amazonaws.com') || value.includes('.elb.') || value.includes('/')) {
    return `http://${value.replace(/^\/+/, '')}`;
  }
  return `grpc://${value}`;
}

function detectGatewayPreset(rawUrl) {
  const normalized = normalizeEndpointInput(rawUrl);
  for (const [preset, value] of Object.entries(GATEWAY_PRESETS)) {
    if (normalized === value) {
      return preset;
    }
  }
  return 'custom';
}

function setGatewayPresetValue(rawUrl) {
  if (!gatewayPresetSelect) {
    return;
  }
  gatewayPresetSelect.value = detectGatewayPreset(rawUrl);
}

function normalizePredictionTargetInput(raw, streamUrl = normalizeEndpointInput(urlInput?.value || '')) {
  const value = String(raw || '').trim();
  if (!value) {
    if (streamUrl.startsWith('http://') || streamUrl.startsWith('https://')) {
      return '';
    }
    const grpcUrl = normalizeEndpointInput(streamUrl);
    if (!grpcUrl.startsWith('grpc://')) {
      return 'grpc://127.0.0.1:50061';
    }
    try {
      const parsed = new URL(grpcUrl);
      const host = parsed.hostname || '127.0.0.1';
      return `grpc://${host}:50061`;
    } catch (_error) {
      return 'grpc://127.0.0.1:50061';
    }
  }
  if (
    value.startsWith('grpc://')
    || value.startsWith('http://')
    || value.startsWith('https://')
  ) {
    return value;
  }
  if (value.includes('amazonaws.com') || value.includes('.elb.')) {
    return `grpc://${value.replace(/^\/+/, '')}`;
  }
  if (value.includes(':')) {
    return `grpc://${value}`;
  }
  return `grpc://${value}:50061`;
}

function alignPredictionTargetForStream(streamUrl, predictionTarget) {
  const normalizedStreamUrl = normalizeEndpointInput(streamUrl);
  const normalizedPredictionTarget = normalizePredictionTargetInput(predictionTarget, normalizedStreamUrl);
  if (
    (normalizedStreamUrl.startsWith('http://') || normalizedStreamUrl.startsWith('https://'))
    && (normalizedPredictionTarget === 'grpc://127.0.0.1:50061' || normalizedPredictionTarget === 'grpc://localhost:50061')
  ) {
    return '';
  }
  return normalizedPredictionTarget;
}

function persistEndpointInput() {
  try {
    localStorage.setItem(URL_STORAGE_KEY, normalizeEndpointInput(urlInput.value));
  } catch (_error) {
    // Ignore persistence errors in restricted environments.
  }
}

function persistGatewayPresetInput() {
  try {
    localStorage.setItem(
      GATEWAY_PRESET_STORAGE_KEY,
      gatewayPresetSelect?.value || detectGatewayPreset(urlInput?.value || '')
    );
  } catch (_error) {
    // Ignore persistence errors in restricted environments.
  }
}

function persistPredictionTargetInput() {
  try {
    const normalized = normalizePredictionTargetInput(predictionTargetInput?.value || '', urlInput?.value || '');
    localStorage.setItem(PREDICTION_TARGET_STORAGE_KEY, normalized);
  } catch (_error) {
    // Ignore persistence errors in restricted environments.
  }
}

function persistModelTypeInput() {
  try {
    localStorage.setItem(MODEL_TYPE_STORAGE_KEY, String(simModelSelect?.value || 'xgboost'));
  } catch (_error) {
    // Ignore persistence errors in restricted environments.
  }
}

function hydrateEndpointInput() {
  try {
    const savedPreset = localStorage.getItem(GATEWAY_PRESET_STORAGE_KEY);
    const saved = localStorage.getItem(URL_STORAGE_KEY);
    if (saved) {
      urlInput.value = saved;
    }
    if (gatewayPresetSelect) {
      gatewayPresetSelect.value = savedPreset && (savedPreset in GATEWAY_PRESETS || savedPreset === 'custom')
        ? savedPreset
        : detectGatewayPreset(urlInput?.value || '');
    }
    const savedPredictionTarget = localStorage.getItem(PREDICTION_TARGET_STORAGE_KEY);
    if (predictionTargetInput) {
      predictionTargetInput.value = alignPredictionTargetForStream(
        urlInput?.value || '',
        savedPredictionTarget || normalizePredictionTargetInput('', urlInput?.value || '')
      );
    }
    const savedModelType = localStorage.getItem(MODEL_TYPE_STORAGE_KEY);
    if (simModelSelect && savedModelType && MODEL_OPTIONS[savedModelType]) {
      simModelSelect.value = savedModelType;
    }
  } catch (_error) {
    // Ignore persistence errors in restricted environments.
  }
}

function getAdaptivePredictionMinIntervalMs() {
  const holdMs = Number(simHoldMsInput?.value);
  const base = Number.isFinite(holdMs) && holdMs > 0 ? holdMs : 500;
  return clamp(Math.round(base), 100, 60000);
}

function getAdaptivePredictionPollMs() {
  const holdMs = Number(simHoldMsInput?.value);
  const base = Number.isFinite(holdMs) && holdMs > 0 ? holdMs : 500;
  return clamp(Math.round(base), 100, 60000);
}

function syncPredictionHorizonInput() {
  if (!simHorizonInput) {
    return;
  }
  const holdMs = Number(simHoldMsInput?.value);
  const normalizedHoldMs = Number.isFinite(holdMs) && holdMs > 0 ? Math.round(holdMs) : 500;
  simHorizonInput.value = String(normalizedHoldMs);
}

function buildPredictionPayload(series, seriesKey = activeGrpcSeriesKey) {
  const points = Array.isArray(series) ? series.slice(-PREDICTION_POINTS_MAX) : [];
  const [channel = '', symbol = ''] = normalizePredictionSeriesKey(seriesKey).split(':');
  const cfg = readStrategyConfig();
  const horizonSec = Math.max(1, Math.ceil(cfg.holdMs / 1000));
  return {
    symbol,
    channel,
    horizonSec,
    modelType: cfg.modelType,
    strategyMode: cfg.strategy,
    holdMs: cfg.holdMs,
    mmAdverseRetThreshold: cfg.adverseThreshold,
    mmOneSidedImbalanceThreshold: cfg.imbalanceThreshold,
    minSpreadBps: cfg.minSpreadBps,
    alphaImbalanceThreshold: cfg.imbalanceThreshold,
    alphaPredRetThreshold: cfg.alphaPredRetThreshold,
    maxEntrySpreadBps: cfg.maxEntrySpreadBps,
    predictionTarget: normalizePredictionTargetInput(predictionTargetInput?.value || '', urlInput?.value || ''),
    points
  };
}

function shouldRetryWithXgboost(errorText, requestedModelType) {
  const message = String(errorText || '').toLowerCase();
  return requestedModelType === 'lightgbm'
    && (message.includes("no module named 'lightgbm'") || message.includes('lightgbm'));
}

async function requestPrediction(series, force = false, seriesKey = predictionSeriesKeyHint || activeGrpcSeriesKey) {
  if (!Array.isArray(series) || series.length < 8) {
    return predictionState.lastResult;
  }
  const now = Date.now();

  if (predictionState.pending && now - predictionState.pendingStartedAt > PREDICTION_STUCK_MS) {
    predictionState.pending = false;
    predictionState.lastError = 'Prediction request timed out in UI loop; retrying.';
  }

  if (predictionState.pending) {
    return predictionState.lastResult;
  }

  const minIntervalMs = getAdaptivePredictionMinIntervalMs();
  if (!force && now - predictionState.lastRequestAt < minIntervalMs) {
    return predictionState.lastResult;
  }

  predictionState.pending = true;
  predictionState.pendingStartedAt = now;
  predictionState.lastRequestAt = now;
  predictionState.totalRequests += 1;
  try {
    const payload = buildPredictionPayload(series, seriesKey);
    predictionState.lastRequestedModelType = String(payload.modelType || 'xgboost');
    let response = await window.streamApi.predict(payload);
    if ((!response?.ok || !response.prediction) && shouldRetryWithXgboost(response?.error, payload.modelType)) {
      payload.modelType = 'xgboost';
      predictionState.lastRequestedModelType = 'xgboost';
      if (simModelSelect) simModelSelect.value = 'xgboost';
      simulator.refreshStrategyUi();
      predictionState.lastError = 'LightGBM unavailable in runtime; retried with XGBoost.';
      response = await window.streamApi.predict(payload);
    }
    if (response?.ok && response.prediction) {
      predictionState.lastResult = toGrpcPrediction(response.prediction);
      predictionState.lastError = '';
      predictionState.lastSuccessAt = Date.now();
      predictionState.lastLatencyMs = predictionState.lastSuccessAt - now;
      simulator.refreshStrategyUi();
      return predictionState.lastResult;
    }
    predictionState.lastError = response?.error || 'gRPC prediction failed';
    predictionState.totalFailures += 1;
    const fallback = calculatePrediction(series);
    predictionState.lastResult = fallback;
    if (fallback) {
      predictionState.lastError = `${predictionState.lastError} (using local fallback)`;
    }
    simulator.refreshStrategyUi();
  } catch (error) {
    predictionState.lastError = error?.message || String(error);
    predictionState.totalFailures += 1;
    const fallback = calculatePrediction(series);
    predictionState.lastResult = fallback;
    if (fallback) {
      predictionState.lastError = `${predictionState.lastError} (using local fallback)`;
    }
    simulator.refreshStrategyUi();
  } finally {
    predictionState.pending = false;
    predictionState.pendingStartedAt = 0;
  }
  return predictionState.lastResult;
}

function startPredictionPolling() {
  stopPredictionPolling();
  const pollMs = getAdaptivePredictionPollMs();
  if (!Number.isFinite(pollMs) || pollMs <= 0) {
    return;
  }
  predictionPollTimer = setInterval(() => {
    void requestActiveSeriesPrediction(false);
  }, pollMs);
}

function stopPredictionPolling() {
  if (predictionPollTimer) {
    clearInterval(predictionPollTimer);
    predictionPollTimer = null;
  }
}

async function requestActiveSeriesPrediction(force = true) {
  const resolved = resolveActiveSeries();
  if (!resolved?.series || resolved.series.length === 0) {
    if (simSummary) {
      simSummary.textContent = 'No active series data yet. Connect stream and wait for ticks.';
    }
    return null;
  }
  if (resolved.series.length < 8) {
    if (simSummary) {
      simSummary.textContent = `Need at least 8 points before requesting prediction. Current series has ${resolved.series.length}.`;
    }
    return predictionState.lastResult;
  }
  predictionSeriesKeyHint = resolved.key || activeGrpcSeriesKey;
  return await requestPrediction(resolved.series, force, predictionSeriesKeyHint);
}

function parseMoneyInput(inputEl, fallback = 0) {
  const raw = String(inputEl?.value || '').trim();
  const cleaned = raw.replace(/[^0-9.]/g, '');
  const numeric = Number(cleaned);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function parseCapitalInput() {
  return parseMoneyInput(simCapitalInput, 0);
}

function parseAccountInput() {
  return parseMoneyInput(simAccountInput, 0);
}

function parsePositiveNumber(inputEl, fallback) {
  const raw = Number(inputEl?.value);
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

function readStrategyConfig() {
  const profileKey = String(simConfigSelect?.value || 'market_maker');
  const profile = CONFIG_PROFILES[profileKey] || CONFIG_PROFILES.market_maker;
  const adverseThreshold = parsePositiveNumber(simAdverseInput, profile.adverseThreshold);
  const minSpreadBps = parsePositiveNumber(simMinSpreadInput, profile.minSpreadBps);
  return {
    modelType: String(simModelSelect?.value || 'xgboost'),
    profile: profileKey,
    strategy: String(simStrategySelect?.value || 'market_making'),
    holdMs: Math.max(50, Math.round(parsePositiveNumber(simHoldMsInput, profile.holdMs))),
    imbalanceThreshold: parsePositiveNumber(simImbalanceInput, profile.imbalanceThreshold),
    adverseThreshold,
    minSpreadBps,
    alphaPredRetThreshold: Math.max(0.00001, adverseThreshold * 0.2),
    maxEntrySpreadBps: Math.max(3, minSpreadBps * 3),
    alphaCooldownMs: profile.alphaCooldownMs
  };
}

function notifyChartSymbol(symbol) {
  window.dispatchEvent(new CustomEvent('stream:symbol-change', {
    detail: { symbol }
  }));
}

function resizeGrpcCanvas() {
  if (!grpcChartCanvas) {
    return;
  }
  const rect = grpcChartCanvas.getBoundingClientRect();
  const width = Math.max(10, Math.floor(rect.width));
  const height = Math.max(10, Math.floor(rect.height));
  grpcCanvasCssWidth = width;
  grpcCanvasCssHeight = height;
  const dpr = window.devicePixelRatio || 1;
  grpcChartCanvas.width = Math.floor(width * dpr);
  grpcChartCanvas.height = Math.floor(height * dpr);
  const ctx = grpcChartCanvas.getContext('2d');
  if (ctx) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
}

function initGrpcCanvas() {
  if (!grpcChartCanvas) {
    return;
  }
  resizeGrpcCanvas();
  if (typeof ResizeObserver === 'function') {
    grpcResizeObserver = new ResizeObserver(() => resizeGrpcCanvas());
    grpcResizeObserver.observe(grpcChartCanvas);
  } else {
    window.addEventListener('resize', resizeGrpcCanvas);
  }
}

function drawGrpcSeries(series) {
  if (!grpcChartCanvas) {
    return;
  }
  const ctx = grpcChartCanvas.getContext('2d');
  if (!ctx || grpcCanvasCssWidth <= 0 || grpcCanvasCssHeight <= 0) {
    return;
  }

  const w = grpcCanvasCssWidth;
  const h = grpcCanvasCssHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(8, 19, 30, 0.65)';
  ctx.fillRect(0, 0, w, h);

  if (!Array.isArray(series) || series.length < 2) {
    ctx.fillStyle = '#8db2c6';
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.fillText('Waiting for enough data points...', 12, 22);
    return;
  }

  let minPrice = Number.POSITIVE_INFINITY;
  let maxPrice = Number.NEGATIVE_INFINITY;
  let minTs = Number.POSITIVE_INFINITY;
  let maxTs = Number.NEGATIVE_INFINITY;
  for (const item of series) {
    if (item.price < minPrice) minPrice = item.price;
    if (item.price > maxPrice) maxPrice = item.price;
    if (item.ts < minTs) minTs = item.ts;
    if (item.ts > maxTs) maxTs = item.ts;
  }
  const pad = (maxPrice - minPrice) * 0.1 || Math.max(1, maxPrice * 0.001);
  minPrice -= pad;
  maxPrice += pad;

  const left = 12;
  const right = w - 66;
  const top = 16;
  const bottom = h - 38;
  const spanX = Math.max(1, right - left);
  const spanY = Math.max(1, bottom - top);
  const priceRange = Math.max(1e-9, maxPrice - minPrice);
  const timeRange = Math.max(1, maxTs - minTs);

  ctx.strokeStyle = 'rgba(148, 199, 229, 0.22)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = top + (spanY * i) / 3;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  for (let i = 0; i < 4; i += 1) {
    const x = left + (spanX * i) / 3;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
  }

  // Right-side price ticks.
  ctx.fillStyle = '#94bed3';
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  for (let i = 0; i < 4; i += 1) {
    const normalized = i / 3;
    const y = bottom - normalized * spanY;
    const p = minPrice + normalized * priceRange;
    ctx.fillText(p.toFixed(2), right + 6, y + 3);
  }

  // Bottom time ticks.
  ctx.textAlign = 'center';
  for (let i = 0; i < 4; i += 1) {
    const normalized = i / 3;
    const x = left + normalized * spanX;
    const t = minTs + normalized * timeRange;
    ctx.fillText(formatClockTime(t), x, bottom + 14);
  }

  // Area fill under price line for better market-chart readability.
  const gradient = ctx.createLinearGradient(0, top, 0, bottom);
  gradient.addColorStop(0, 'rgba(72, 184, 255, 0.25)');
  gradient.addColorStop(1, 'rgba(72, 184, 255, 0.02)');
  ctx.fillStyle = gradient;
  ctx.beginPath();
  for (let i = 0; i < series.length; i += 1) {
    const normalizedTime = (series[i].ts - minTs) / timeRange;
    const normalizedPrice = (series[i].price - minPrice) / priceRange;
    const x = left + normalizedTime * spanX;
    const y = bottom - normalizedPrice * spanY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.lineTo(right, bottom);
  ctx.lineTo(left, bottom);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = '#48b8ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < series.length; i += 1) {
    const normalizedTime = (series[i].ts - minTs) / timeRange;
    const normalizedPrice = (series[i].price - minPrice) / priceRange;
    const x = left + normalizedTime * spanX;
    const y = bottom - normalizedPrice * spanY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  const last = series[series.length - 1];
  const prev = series[series.length - 2];
  const delta = last && prev ? last.price - prev.price : 0;
  ctx.fillStyle = delta >= 0 ? '#31cf97' : '#ff6b5e';
  ctx.font = '12px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText(`last=${last.price.toFixed(2)}  delta=${delta.toFixed(2)}`, left, h - 8);

  ctx.fillStyle = '#94bed3';
  ctx.font = '12px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('X: Time', (left + right) / 2, h - 23);
  ctx.save();
  ctx.translate(w - 14, (top + bottom) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillText('Y: Price', 0, 0);
  ctx.restore();
}

function startLoop() {
  let lastStatsRender = 0;
  // Render/update more frequently to reduce visible and decision latency.
  const statsRenderMs = 25;

  function frame(now) {
    if (pointQueue.length > 1200) {
      pointQueue.splice(0, pointQueue.length - 400);
    }

    let processed = 0;
    while (pointQueue.length > 0 && processed < 400) {
      const point = pointQueue.shift();
      latestPoint = point;
      appendGrpcPoint(point);
      updateRate(point.ts || Date.now());
      processed += 1;
    }

    if (latestPoint && now - lastStatsRender >= statsRenderMs) {
      renderStats(latestPoint);
      const resolved = resolveActiveSeries();
      const series = resolved?.series;
      predictionSeriesKeyHint = resolved?.key || activeGrpcSeriesKey;
      drawGrpcSeries(series);
      simulator.update(series, resolved?.key || activeGrpcSeriesKey);
      const points = Array.isArray(series) ? series.length : 0;
      if (Array.isArray(series) && series.length > 1) {
        const first = series[0];
        const last = series[series.length - 1];
        let min = Number.POSITIVE_INFINITY;
        let max = Number.NEGATIVE_INFINITY;
        for (const item of series) {
          if (item.price < min) min = item.price;
          if (item.price > max) max = item.price;
        }
        const windowSec = Math.max(0, Math.round((last.ts - first.ts) / 1000));
        grpcChartMeta.textContent = `Series: ${resolved?.key || activeGrpcSeriesKey || '-'} | Points: ${points} | Last: ${last.price.toFixed(2)} | Min/Max: ${min.toFixed(2)}/${max.toFixed(2)} | Window: ${windowSec}s`;
      } else {
        grpcChartMeta.textContent = `Series: ${resolved?.key || activeGrpcSeriesKey || '-'} | Points: ${points}`;
      }
      lastStatsRender = now;
    }

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

connectBtn.addEventListener('click', async () => {
  stopPredictionPolling();
  const subscriptions = getSubscriptions();
  const primary = subscriptions[0] || { symbol: 'BTC-USDT', channel: 'books' };
  pickActiveGrpcSeriesKey(subscriptions);
  notifyChartSymbol(primary.symbol);
  const normalizedUrl = normalizeEndpointInput(urlInput.value);
  const normalizedPredictionTarget = alignPredictionTargetForStream(
    normalizedUrl,
    predictionTargetInput?.value || ''
  );
  urlInput.value = normalizedUrl;
  setGatewayPresetValue(normalizedUrl);
  if (predictionTargetInput) {
    predictionTargetInput.value = normalizedPredictionTarget;
  }
  persistGatewayPresetInput();
  persistEndpointInput();
  persistPredictionTargetInput();
  await window.streamApi.start({
    symbol: primary.symbol,
    channel: primary.channel,
    subscriptions,
    url: normalizedUrl,
    predictionTarget: normalizedPredictionTarget,
    simulated: false
  });
});

simulateBtn.addEventListener('click', async () => {
  stopPredictionPolling();
  const subscriptions = getSubscriptions();
  const primary = subscriptions[0] || { symbol: 'BTC-USDT', channel: 'books' };
  pickActiveGrpcSeriesKey(subscriptions);
  notifyChartSymbol(primary.symbol);
  await window.streamApi.start({
    symbol: primary.symbol,
    subscriptions,
    simulated: true
  });
});

stopBtn.addEventListener('click', async () => {
  stopPredictionPolling();
  simulator.onStreamStopped();
  await window.streamApi.stop();
});

urlInput?.addEventListener('blur', () => {
  const normalized = normalizeEndpointInput(urlInput.value);
  urlInput.value = normalized;
  setGatewayPresetValue(normalized);
  if (predictionTargetInput) {
    predictionTargetInput.value = alignPredictionTargetForStream(predictionTargetInput.value ? normalized : normalized, predictionTargetInput.value);
  }
  persistGatewayPresetInput();
  persistEndpointInput();
  persistPredictionTargetInput();
});

gatewayPresetSelect?.addEventListener('change', () => {
  const preset = gatewayPresetSelect.value;
  if (preset !== 'custom' && GATEWAY_PRESETS[preset]) {
    const normalized = GATEWAY_PRESETS[preset];
    urlInput.value = normalized;
    if (predictionTargetInput) {
      predictionTargetInput.value = alignPredictionTargetForStream(normalized, predictionTargetInput.value || '');
    }
  } else {
    setGatewayPresetValue(urlInput?.value || '');
  }
  persistGatewayPresetInput();
  persistEndpointInput();
  persistPredictionTargetInput();
});

predictionTargetInput?.addEventListener('blur', () => {
  const normalized = alignPredictionTargetForStream(urlInput?.value || '', predictionTargetInput.value);
  predictionTargetInput.value = normalized;
  persistPredictionTargetInput();
});

simPredictBtn?.addEventListener('click', () => {
  void requestActiveSeriesPrediction(true);
});

simAutoStartBtn?.addEventListener('click', () => {
  simulator.startAutoTradingSession();
});

simAutoStopBtn?.addEventListener('click', () => {
  stopPredictionPolling();
  simulator.stopAutoTradingSession('Auto trading stopped by user');
});

simModelSelect?.addEventListener('change', () => {
  predictionState.lastResult = null;
  predictionState.lastError = '';
  predictionState.pending = false;
  predictionState.pendingStartedAt = 0;
  predictionState.lastRequestAt = 0;
  predictionState.lastRequestedModelType = String(simModelSelect?.value || 'xgboost');
  persistModelTypeInput();
  simulator.refreshStrategyUi();
  if (predictionPollTimer) {
    startPredictionPolling();
  }
});

simConfigSelect?.addEventListener('change', () => {
  simulator.applyConfigProfile(simConfigSelect.value);
  if (predictionPollTimer) {
    startPredictionPolling();
  }
});

simStrategySelect?.addEventListener('change', () => {
  simulator.refreshStrategyUi();
});

simHoldMsInput?.addEventListener('change', () => {
  syncPredictionHorizonInput();
  if (predictionPollTimer) {
    startPredictionPolling();
  }
});
simHoldMsInput?.addEventListener('input', () => {
  syncPredictionHorizonInput();
  if (predictionPollTimer) {
    startPredictionPolling();
  }
});

simCapitalInput?.addEventListener('focus', () => {
  const capital = parseCapitalInput();
  if (capital > 0) {
    simCapitalInput.value = String(Math.round(capital));
  }
});

simCapitalInput?.addEventListener('blur', () => {
  simulator.formatCapitalInput();
});

simAccountInput?.addEventListener('focus', () => {
  const balance = parseAccountInput();
  if (balance > 0) {
    simAccountInput.value = String(Math.round(balance));
  }
});

simAccountInput?.addEventListener('blur', () => {
  simulator.formatAccountInput();
  if (!simulator.isPositionOpen()) {
    simulator.resetAccount();
  }
});

simAccountResetBtn?.addEventListener('click', () => {
  simulator.resetAccount();
});

window.streamApi.onStatus((payload) => {
  updateStatus(payload.state, payload.detail);
});

window.streamApi.onData((payload) => {
  queuePoints([payload]);
});

window.streamApi.onDataBatch((payload) => {
  if (Array.isArray(payload) && payload.length > 0) {
    queuePoints(payload);
  }
});

addRowBtn.addEventListener('click', () => {
  subscriptionRows.appendChild(createSubscriptionRow());
});

subscriptionRows.appendChild(createSubscriptionRow({ symbol: 'BTC-USDT', channel: 'books' }));
subscriptionRows.appendChild(createSubscriptionRow({ symbol: 'BTC-USDT', channel: 'trades' }));
hydrateEndpointInput();
syncPredictionHorizonInput();
notifyChartSymbol('BTC-USDT');
pickActiveGrpcSeriesKey(getSubscriptions());

simulator.bootstrap();
initGrpcCanvas();
startLoop();
