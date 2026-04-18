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
const simMinSpreadWrap = document.getElementById('sim-min-spread-wrap');
const simAdverseWrap = document.getElementById('sim-adverse-wrap');
const simAutoStartBtn = document.getElementById('sim-auto-start-btn');
const simAutoStopBtn = document.getElementById('sim-auto-stop-btn');
const simAccountResetBtn = document.getElementById('sim-account-reset-btn');
const simSummary = document.getElementById('sim-summary');
const simSignal = document.getElementById('sim-signal');
const simPredPrice = document.getElementById('sim-pred-price');
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
const urlInput = document.getElementById('url-input');
const connectBtn = document.getElementById('connect-btn');
const simulateBtn = document.getElementById('simulate-btn');
const stopBtn = document.getElementById('stop-btn');

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
  xgboost: 'XGBoost',
  lstm: 'LSTM',
  cnn: 'CNN',
  transformer: 'Transformer'
};
const CONFIG_PROFILES = {
  market_maker: {
    label: 'Market Maker',
    strategy: 'market_making',
    capital: '5,000',
    holdMs: 500,
    horizonSec: 30,
    autoRangeSec: 60,
    imbalanceThreshold: 0.2,
    adverseThreshold: 0.0006,
    minSpreadBps: 0.8,
    alphaCooldownMs: 250,
    summary: 'Config Market Maker applied: balanced quoting with adverse-selection protection.'
  },
  alpha_fast: {
    label: 'Alpha Fast',
    strategy: 'short_term_alpha',
    capital: '10,000',
    holdMs: 140,
    horizonSec: 20,
    autoRangeSec: 300,
    imbalanceThreshold: 0.06,
    adverseThreshold: 0.00005,
    minSpreadBps: 0.8,
    alphaCooldownMs: 220,
    summary: 'Config Alpha Fast applied: active entries with moderate aggression.'
  },
  alpha_ultra: {
    label: 'Ultra Alpha',
    strategy: 'short_term_alpha',
    capital: '20,000',
    holdMs: 80,
    horizonSec: 10,
    autoRangeSec: 420,
    imbalanceThreshold: 0.03,
    adverseThreshold: 0.00002,
    minSpreadBps: 0.6,
    alphaCooldownMs: 120,
    summary: 'Config Ultra Alpha applied: very aggressive, high-turnover trading.'
  }
};
const predictionState = {
  pending: false,
  lastRequestAt: 0,
  lastResult: null,
  lastError: ''
};
const simState = {
  open: false,
  capital: 5000,
  horizonMs: 30000,
  openedTs: 0,
  strategy: 'market_making',
  side: 'LONG',
  entryPrice: 0,
  exitPrice: 0,
  predictedPrice: 0,
  expectedPnl: 0,
  realizedPnl: 0,
  qty: 0,
  seriesKey: '',
  pendingDecision: false,
  holdCycles: 0
};
const autoTradeState = {
  running: false,
  endTs: 0,
  totalPnl: 0,
  sessionStartEquity: 0,
  trades: 0,
  wins: 0,
  losses: 0,
  lastEntryTs: 0
};
const accountState = {
  initialized: false,
  cash: 0,
  equity: 0,
  lastAction: '-'
};
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

  if (pointQueue.length > 6000) {
    pointQueue.splice(0, pointQueue.length - 3000);
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
      ${CHANNEL_OPTIONS.map((channel) => `<option value="${channel}" ${channel === (defaults.channel || 'books5') ? 'selected' : ''}>${channel}</option>`).join('')}
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
    return [{ symbol: 'BTC-USDT', channel: 'books5' }];
  }
  return subscriptions;
}

function pickActiveGrpcSeriesKey(subscriptions = []) {
  if (subscriptions.length > 0) {
    const primary = subscriptions[0];
    activeGrpcSeriesKey = `${primary.channel}:${primary.symbol}`;
    return;
  }
  if (!activeGrpcSeriesKey && grpcSeriesByKey.size > 0) {
    activeGrpcSeriesKey = grpcSeriesByKey.keys().next().value;
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
  const max20 = Math.max(...recent20);
  const min20 = Math.min(...recent20);
  const mean20 = recent20.reduce((acc, x) => acc + x, 0) / recent20.length;
  let variance = 0;
  for (const x of recent20) {
    const d = x - mean20;
    variance += d * d;
  }
  variance /= recent20.length;
  const std20 = Math.sqrt(variance);

  const features = {
    momentum5: pctChange(last, p5),
    momentum20: pctChange(last, p20),
    volatility20: mean20 !== 0 ? std20 / mean20 : 0,
    range20: mean20 !== 0 ? (max20 - min20) / mean20 : 0
  };

  const score = PREBUILT_MODEL.intercept
    + PREBUILT_MODEL.weights.momentum5 * features.momentum5
    + PREBUILT_MODEL.weights.momentum20 * features.momentum20
    + PREBUILT_MODEL.weights.volatility20 * features.volatility20
    + PREBUILT_MODEL.weights.range20 * features.range20;

  const bounded = Math.max(-0.03, Math.min(0.03, score));
  const predictedPrice = last * (1 + bounded);
  let signal = 'HOLD';
  if (bounded > 0.0008) signal = 'LONG';
  else if (bounded < -0.0008) signal = 'SHORT';

  return {
    signal,
    score: bounded,
    lastPrice: last,
    predictedPrice,
    modelName: PREBUILT_MODEL.name,
    detail: 'local linear fallback model'
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
    lastPrice,
    predictedPrice,
    modelName: result.model_name || 'PredictionService',
    detail: result.detail || ''
  };
}

function buildPredictionPayload(series) {
  const points = Array.isArray(series) ? series.slice(-120) : [];
  const [channel = '', symbol = ''] = String(activeGrpcSeriesKey || '').split(':');
  const horizonSec = Math.max(1, Number(simHorizonInput?.value || 30));
  const cfg = readStrategyConfig();
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
    points
  };
}

async function requestPrediction(series, force = false) {
  if (!Array.isArray(series) || series.length < 8 || predictionState.pending) {
    return predictionState.lastResult;
  }
  const now = Date.now();
  if (!force && now - predictionState.lastRequestAt < 1000) {
    return predictionState.lastResult;
  }

  predictionState.pending = true;
  predictionState.lastRequestAt = now;
  try {
    const payload = buildPredictionPayload(series);
    const response = await window.streamApi.predict(payload);
    if (response?.ok && response.prediction) {
      predictionState.lastResult = toGrpcPrediction(response.prediction);
      predictionState.lastError = '';
      return predictionState.lastResult;
    }
    predictionState.lastError = response?.error || 'gRPC prediction failed';
    predictionState.lastResult = null;
  } catch (error) {
    predictionState.lastError = error?.message || String(error);
    predictionState.lastResult = null;
  } finally {
    predictionState.pending = false;
  }
  return predictionState.lastResult;
}

function formatUsdSigned(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return '-';
  }
  const sign = num >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(num).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatUsd(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return '-';
  }
  return `$${num.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function parseMoneyInput(inputEl, fallback = 0) {
  const raw = String(inputEl?.value || '').trim();
  const cleaned = raw.replace(/[^0-9.]/g, '');
  const numeric = Number(cleaned);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return numeric;
}

function parseCapitalInput() {
  return parseMoneyInput(simCapitalInput, 0);
}

function formatCapitalInput() {
  if (!simCapitalInput) {
    return;
  }
  const capital = parseCapitalInput();
  if (!Number.isFinite(capital) || capital <= 0) {
    return;
  }
  simCapitalInput.value = Math.round(capital).toLocaleString();
}

function parseAccountInput() {
  return parseMoneyInput(simAccountInput, 0);
}

function parsePositiveNumber(inputEl, fallback) {
  const raw = Number(inputEl?.value);
  if (!Number.isFinite(raw) || raw <= 0) {
    return fallback;
  }
  return raw;
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
    holdMs: Math.max(50, Math.round(parsePositiveNumber(simHoldMsInput, 500))),
    imbalanceThreshold: parsePositiveNumber(simImbalanceInput, 0.2),
    adverseThreshold,
    minSpreadBps,
    alphaPredRetThreshold: Math.max(0.00001, adverseThreshold * 0.2),
    maxEntrySpreadBps: Math.max(3, minSpreadBps * 3),
    alphaCooldownMs: profile.alphaCooldownMs
  };
}

function refreshStrategyUi() {
  const cfg = readStrategyConfig();
  const isMM = cfg.strategy === 'market_making';
  const profile = CONFIG_PROFILES[cfg.profile] || CONFIG_PROFILES.market_maker;

  if (simModelBadge) {
    simModelBadge.textContent = `Model: ${MODEL_OPTIONS[cfg.modelType] || 'XGBoost'}`;
  }
  if (simModeBadge) {
    simModeBadge.textContent = `Mode: ${profile.label}`;
  }
  if (simRuleHint) {
    simRuleHint.textContent = isMM
      ? 'Quote both sides, skip adverse windows.'
      : cfg.profile === 'alpha_ultra'
        ? 'Ultra fast alpha entries with tight confirmation.'
        : 'Fast alpha entries on imbalance and model confirmation.';
  }
  if (simAdverseTitle) {
    simAdverseTitle.textContent = isMM ? 'Adverse Filter' : 'Model Confirm Threshold';
  }
  if (simMinSpreadWrap) {
    simMinSpreadWrap.classList.toggle('input-muted', !isMM);
  }
  if (simAdverseWrap) {
    simAdverseWrap.classList.toggle('input-muted', false);
  }
}

function refreshAutoBadge() {
  if (!simAutoBadge) {
    return;
  }
  simAutoBadge.classList.toggle('sim-badge-live', autoTradeState.running);
  simAutoBadge.classList.toggle('sim-badge-idle', !autoTradeState.running);
  simAutoBadge.textContent = autoTradeState.running ? 'Auto: RUNNING' : 'Auto: OFF';
}

function applyConfigProfile(profileKey = 'alpha_fast') {
  const profile = CONFIG_PROFILES[profileKey] || CONFIG_PROFILES.alpha_fast;
  if (simConfigSelect) simConfigSelect.value = profileKey;
  simStrategySelect.value = profile.strategy;
  simCapitalInput.value = profile.capital;
  simHoldMsInput.value = String(profile.holdMs);
  simHorizonInput.value = String(profile.horizonSec);
  simImbalanceInput.value = String(profile.imbalanceThreshold);
  simAdverseInput.value = String(profile.adverseThreshold);
  simMinSpreadInput.value = String(profile.minSpreadBps);
  simRangeInput.value = String(profile.autoRangeSec);
  simSummary.textContent = profile.summary;
  formatCapitalInput();
  refreshStrategyUi();
}

function parseBookStatsFromPoint(point) {
  const fields = point?.fields || {};
  const bid = Number(fields.bidPx);
  const ask = Number(fields.askPx);
  const bidSz = Number(fields.bidSz);
  const askSz = Number(fields.askSz);
  if (!Number.isFinite(bid) || !Number.isFinite(ask) || bid <= 0 || ask <= 0 || ask <= bid) {
    return null;
  }
  const mid = 0.5 * (bid + ask);
  const spreadBps = ((ask - bid) / mid) * 10000;
  let imbalance = 0;
  if (Number.isFinite(bidSz) && Number.isFinite(askSz) && bidSz + askSz > 0) {
    imbalance = (bidSz - askSz) / (bidSz + askSz);
  }
  return { bid, ask, mid, spreadBps, imbalance };
}

function decideTradeByStrategy(prediction, point) {
  if (!prediction || !point) {
    return { action: 'HOLD', reason: 'No prediction/point' };
  }
  if (prediction.signal === 'LONG' || prediction.signal === 'SHORT' || prediction.signal === 'HOLD') {
    return {
      action: prediction.signal,
      reason: prediction.detail ? `server: ${prediction.detail}` : 'server strategy decision'
    };
  }

  const cfg = readStrategyConfig();
  const book = parseBookStatsFromPoint(point);
  if (!book) {
    return { action: 'HOLD', reason: 'No valid bid/ask yet' };
  }

  const score = Number(prediction.score) || 0;
  const absScore = Math.abs(score);
  const absImb = Math.abs(book.imbalance);

  if (cfg.strategy === 'market_making') {
    if (book.spreadBps < cfg.minSpreadBps) {
      return { action: 'HOLD', reason: `Spread ${book.spreadBps.toFixed(2)}bps below min` };
    }
    if (absScore >= cfg.adverseThreshold) {
      return { action: 'HOLD', reason: `Adverse filter hit (|ret|=${absScore.toFixed(5)})` };
    }
    if (book.imbalance >= cfg.imbalanceThreshold) {
      return { action: 'SHORT', reason: `MM one-sided risk (imb=${book.imbalance.toFixed(2)})` };
    }
    if (book.imbalance <= -cfg.imbalanceThreshold) {
      return { action: 'LONG', reason: `MM one-sided risk (imb=${book.imbalance.toFixed(2)})` };
    }
    if (score > 0) {
      return { action: 'LONG', reason: `MM balanced book + positive drift (${score.toFixed(5)})` };
    }
    if (score < 0) {
      return { action: 'SHORT', reason: `MM balanced book + negative drift (${score.toFixed(5)})` };
    }
    return { action: 'HOLD', reason: 'MM neutral conditions' };
  }

  // short_term_alpha
  if (book.spreadBps > Math.max(3, cfg.minSpreadBps * 3)) {
    return { action: 'HOLD', reason: `Spread too wide (${book.spreadBps.toFixed(2)}bps)` };
  }
  if (absImb < cfg.imbalanceThreshold) {
    return { action: 'HOLD', reason: `Imbalance ${absImb.toFixed(2)} below threshold` };
  }
  if (book.imbalance > 0 && score >= cfg.adverseThreshold * 0.2) {
    return { action: 'LONG', reason: `Alpha long (imb=${book.imbalance.toFixed(2)}, ret=${score.toFixed(5)})` };
  }
  if (book.imbalance < 0 && score <= -cfg.adverseThreshold * 0.2) {
    return { action: 'SHORT', reason: `Alpha short (imb=${book.imbalance.toFixed(2)}, ret=${score.toFixed(5)})` };
  }
  return { action: 'HOLD', reason: 'Model does not confirm imbalance' };
}

function shouldEnterAuto(decision) {
  if (!decision || decision.action === 'HOLD') {
    return false;
  }
  const cfg = readStrategyConfig();
  if (cfg.strategy === 'short_term_alpha') {
    const now = Date.now();
    if (now - autoTradeState.lastEntryTs < cfg.alphaCooldownMs) {
      return false;
    }
  }
  return true;
}

function formatAccountInput() {
  if (!simAccountInput) {
    return;
  }
  const balance = parseAccountInput();
  if (!Number.isFinite(balance) || balance <= 0) {
    return;
  }
  simAccountInput.value = Math.round(balance).toLocaleString();
}

function setPnlColor(el, value) {
  if (!el) return;
  if (!Number.isFinite(value)) {
    el.style.color = '';
    return;
  }
  el.style.color = value >= 0 ? 'var(--good)' : 'var(--bad)';
}

function renderAccountStats(lastPrice = null) {
  if (!accountState.initialized) {
    simAccountCash.textContent = '-';
    simAccountEquity.textContent = '-';
    simAccountAction.textContent = '-';
    return;
  }

  const price = Number(lastPrice);
  const hasPosition = simState.open && Number.isFinite(price) && price > 0;
  let positionValue = 0;
  if (hasPosition) {
    if (simState.side === 'SHORT') {
      positionValue = simState.capital + (simState.entryPrice - price) * simState.qty;
    } else {
      positionValue = simState.qty * price;
    }
  }
  accountState.equity = accountState.cash + positionValue;

  simAccountCash.textContent = formatUsd(accountState.cash);
  simAccountEquity.textContent = formatUsd(accountState.equity);
  simAccountAction.textContent = accountState.lastAction || '-';
  setPnlColor(simAccountCash, accountState.cash);
  setPnlColor(simAccountEquity, accountState.equity);
}

function initializeAccountIfNeeded() {
  if (accountState.initialized) {
    return;
  }
  const init = parseAccountInput();
  accountState.cash = Number.isFinite(init) && init > 0 ? init : 20000;
  accountState.equity = accountState.cash;
  accountState.lastAction = 'INIT';
  accountState.initialized = true;
  renderAccountStats();
}

function resetAccount() {
  if (simState.open) {
    closeSimulation('Account reset -> SELL executed');
  }
  const init = parseAccountInput();
  accountState.cash = Number.isFinite(init) && init > 0 ? init : 20000;
  accountState.equity = accountState.cash;
  accountState.lastAction = 'RESET';
  accountState.initialized = true;
  renderAccountStats();
  simSummary.textContent = `Account reset to ${formatUsd(accountState.cash)}.`;
}

function renderAutoSessionStats() {
  simTradeCount.textContent = String(autoTradeState.trades);
  simTotalPnl.textContent = formatUsdSigned(autoTradeState.totalPnl);
  setPnlColor(simTotalPnl, autoTradeState.totalPnl);
}

function updateSessionProfitFromEquity(lastPrice = null) {
  if (!autoTradeState.running || !accountState.initialized) {
    return;
  }
  renderAccountStats(lastPrice);
  autoTradeState.totalPnl = accountState.equity - autoTradeState.sessionStartEquity;
  renderAutoSessionStats();
}

function closeSimulation(reason = 'Closed', options = {}) {
  const { recordInSession = false } = options;
  if (!simState.open) return;

  const activeSeries = grpcSeriesByKey.get(simState.seriesKey);
  const lastPoint = Array.isArray(activeSeries) && activeSeries.length > 0
    ? activeSeries[activeSeries.length - 1]
    : null;
  const exitPrice = lastPoint ? Number(lastPoint.price) : simState.entryPrice;
  let realizedPnl = 0;
  let settlement = simState.capital;
  if (simState.side === 'SHORT') {
    realizedPnl = (simState.entryPrice - exitPrice) * simState.qty;
    settlement += realizedPnl;
    accountState.lastAction = 'COVER';
  } else {
    realizedPnl = (exitPrice - simState.entryPrice) * simState.qty;
    settlement += realizedPnl;
    accountState.lastAction = 'SELL';
  }
  accountState.cash += settlement;
  const finalEquity = accountState.cash;

  simState.open = false;
  simState.exitPrice = exitPrice;
  simState.realizedPnl = realizedPnl;
  simState.pendingDecision = false;
  simState.holdCycles = 0;

  simLivePnl.textContent = formatUsdSigned(realizedPnl);
  simLiveEquity.textContent = formatUsd(finalEquity);
  simPosition.textContent = `CLOSED (${simState.side})`;
  setPnlColor(simLivePnl, realizedPnl);
  setPnlColor(simLiveEquity, realizedPnl);
  renderAccountStats(exitPrice);

  if (recordInSession) {
    autoTradeState.trades += 1;
    if (realizedPnl >= 0) autoTradeState.wins += 1;
    else autoTradeState.losses += 1;
    updateSessionProfitFromEquity(exitPrice);
  }

  simSummary.textContent = `${reason}. ${simState.side} @ ${simState.entryPrice.toFixed(2)} -> CLOSE @ ${exitPrice.toFixed(2)} | Realized PnL: ${formatUsdSigned(realizedPnl)} | Equity: ${formatUsd(finalEquity)}`;
}

function openSimulationFromPrediction(pred, resolvedKey, capital, horizonSec, mode = 'manual', side = 'LONG', decisionReason = '') {
  if (!pred) {
    simSummary.textContent = 'Prediction not available.';
    return false;
  }
  if (!Number.isFinite(capital) || capital <= 0) {
    simSummary.textContent = 'Capital must be greater than 0.';
    return false;
  }
  if (!Number.isFinite(horizonSec) || horizonSec < 0) {
    simSummary.textContent = 'Horizon must be at least 1 second.';
    return false;
  }
  initializeAccountIfNeeded();
  if (accountState.cash < capital) {
    simSummary.textContent = `Insufficient account cash. Need ${formatUsd(capital)}, available ${formatUsd(accountState.cash)}.`;
    return false;
  }

  const qty = capital / pred.lastPrice;
  const direction = side === 'SHORT' ? -1 : 1;
  const expectedPnl = (pred.predictedPrice - pred.lastPrice) * qty * direction;

  simState.open = true;
  accountState.cash -= capital;
  accountState.lastAction = side === 'SHORT' ? 'SHORT' : 'BUY';
  simState.capital = capital;
  simState.strategy = String(simStrategySelect?.value || 'market_making');
  simState.side = side === 'SHORT' ? 'SHORT' : 'LONG';
  simState.horizonMs = readStrategyConfig().holdMs;
  simState.openedTs = Date.now();
  simState.entryPrice = pred.lastPrice;
  simState.predictedPrice = pred.predictedPrice;
  simState.expectedPnl = expectedPnl;
  simState.qty = qty;
  simState.seriesKey = resolvedKey || activeGrpcSeriesKey;
  simState.exitPrice = 0;
  simState.realizedPnl = 0;
  simState.pendingDecision = false;
  simState.holdCycles = 0;
  if (mode === 'auto') {
    autoTradeState.lastEntryTs = Date.now();
  }
  renderAccountStats(pred.lastPrice);

  const reasonText = decisionReason ? ` | Reason: ${decisionReason}` : '';
  simSummary.textContent = `${simState.side} opened on ${simState.seriesKey} with ${formatUsd(capital)} | Entry: ${pred.lastPrice.toFixed(2)} | Predicted: ${pred.predictedPrice.toFixed(2)} | Hold: ${simState.horizonMs}ms | Model: ${pred.modelName || PREBUILT_MODEL.name}${reasonText}`;
  return true;
}

async function evaluateHorizonDecision(series) {
  if (!simState.open || simState.pendingDecision) {
    return;
  }
  simState.pendingDecision = true;
  try {
    let pred = await requestPrediction(series, true);

    const lastPoint = Array.isArray(series) && series.length > 0 ? series[series.length - 1] : null;
    const currentPrice = lastPoint ? Number(lastPoint.price) : simState.entryPrice;
    const isAlpha = simState.strategy === 'short_term_alpha';
    let shouldHold = false;
    if (!isAlpha && pred && Number.isFinite(currentPrice)) {
      if (simState.side === 'SHORT') {
        shouldHold = pred.predictedPrice < currentPrice;
      } else {
        shouldHold = pred.predictedPrice > currentPrice;
      }
    }

    if (shouldHold) {
      simState.openedTs = Date.now();
      simState.predictedPrice = pred.predictedPrice;
      simState.expectedPnl = (pred.predictedPrice - currentPrice) * simState.qty;
      simState.holdCycles += 1;
      simSummary.textContent = `Hold window reached -> EXTEND (${simState.holdCycles}) | Side: ${simState.side} | Predicted: ${pred.predictedPrice.toFixed(2)} | Model: ${pred.modelName || PREBUILT_MODEL.name}`;
      return;
    }

    if (isAlpha) {
      closeSimulation('Alpha quick exit at hold limit', { recordInSession: autoTradeState.running });
    } else {
      closeSimulation('Hold window reached -> CLOSE by prediction', { recordInSession: autoTradeState.running });
    }

    // Re-entry is auto-mode only.
    if (!autoTradeState.running) {
      return;
    }
    // After SELL, immediately evaluate re-entry with a fresh prediction.
    if (Date.now() >= autoTradeState.endTs) {
      return;
    }
    const resolved = resolveActiveSeries();
    const refreshedSeries = resolved?.series || series;
    let nextPred = await requestPrediction(refreshedSeries, true);
    if (!nextPred) {
      return;
    }

    const latest = Array.isArray(refreshedSeries) && refreshedSeries.length > 0
      ? refreshedSeries[refreshedSeries.length - 1]
      : null;
    if (!latest) {
      return;
    }
    const decision = decideTradeByStrategy(nextPred, latest);
    if (decision.action === 'HOLD' || !shouldEnterAuto(decision)) {
      return;
    }

    const capital = parseCapitalInput() || 5000;
    const horizonSec = Number(simHorizonInput?.value || 30);
    const opened = openSimulationFromPrediction(
      nextPred,
      resolved?.key || activeGrpcSeriesKey,
      capital,
      horizonSec,
      'auto',
      decision.action,
      decision.reason
    );
    if (opened) {
      simSummary.textContent = `Re-entry ${decision.action} after close | ${resolved?.key || activeGrpcSeriesKey} | ${decision.reason}`;
    }
  } finally {
    simState.pendingDecision = false;
  }
}

async function openSimulation() {
  const resolved = resolveActiveSeries();
  const series = resolved?.series;
  let pred = await requestPrediction(series, true);
  const capital = parseCapitalInput();
  const horizonSec = Number(simHorizonInput?.value || 30);
  if (!pred) {
    simSummary.textContent = 'Need at least 8 data points before prediction.';
    return;
  }
  const latest = Array.isArray(series) && series.length > 0 ? series[series.length - 1] : null;
  const decision = decideTradeByStrategy(pred, latest);
  if (decision.action === 'HOLD') {
    simSummary.textContent = `No manual entry: ${decision.reason}`;
    return;
  }
  openSimulationFromPrediction(
    pred,
    resolved?.key || activeGrpcSeriesKey,
    capital,
    horizonSec,
    'manual',
    decision.action,
    decision.reason
  );
}

function startAutoTradingSession() {
  const rangeSec = Number(simRangeInput?.value || 60);
  if (!Number.isFinite(rangeSec) || rangeSec < 10) {
    simSummary.textContent = 'Auto range must be at least 10 seconds.';
    return;
  }
  autoTradeState.running = true;
  autoTradeState.endTs = Date.now() + rangeSec * 1000;
  autoTradeState.totalPnl = 0;
  initializeAccountIfNeeded();
  renderAccountStats();
  autoTradeState.sessionStartEquity = accountState.equity;
  autoTradeState.trades = 0;
  autoTradeState.wins = 0;
  autoTradeState.losses = 0;
  renderAutoSessionStats();
  refreshAutoBadge();
  const cfg = readStrategyConfig();
  const profile = CONFIG_PROFILES[cfg.profile] || CONFIG_PROFILES.market_maker;
  simSummary.textContent = `Auto trading started for ${rangeSec}s | Config: ${profile.label} | Model: ${MODEL_OPTIONS[cfg.modelType] || 'XGBoost'} | Hold: ${cfg.holdMs}ms`;
}

function stopAutoTradingSession(reason = 'Auto trading stopped') {
  if (!autoTradeState.running) {
    return;
  }
  if (simState.open) {
    closeSimulation('Auto session ended - SELL executed', { recordInSession: true });
  }
  updateSessionProfitFromEquity();
  autoTradeState.running = false;
  refreshAutoBadge();
  const winRate = autoTradeState.trades > 0
    ? ((autoTradeState.wins / autoTradeState.trades) * 100).toFixed(1)
    : '0.0';
  simSummary.textContent = `${reason}. Trades: ${autoTradeState.trades} | Total Profit: ${formatUsdSigned(autoTradeState.totalPnl)} | Win rate: ${winRate}%`;
}

async function runInferenceNow() {
  const resolved = resolveActiveSeries();
  const series = resolved?.series;
  if (!Array.isArray(series) || series.length < 8) {
    simSummary.textContent = 'Need at least 8 points to run inference.';
    return;
  }

  let prediction = await requestPrediction(series, true);
  if (!prediction) {
    simSummary.textContent = 'Inference failed: no prediction available.';
    return;
  }

  const capitalPreview = parseCapitalInput() || 5000;
  const qtyPreview = Number.isFinite(capitalPreview) && capitalPreview > 0
    ? capitalPreview / prediction.lastPrice
    : 0;
  const latest = Array.isArray(series) && series.length > 0 ? series[series.length - 1] : null;
  const decision = decideTradeByStrategy(prediction, latest);
  const direction = decision.action === 'SHORT' ? -1 : 1;
  const expectedPreview = (prediction.predictedPrice - prediction.lastPrice) * qtyPreview * direction;
  simSignal.textContent = decision.action;
  simPredPrice.textContent = `$${prediction.predictedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  simExpPnl.textContent = formatUsdSigned(expectedPreview);
  setPnlColor(simExpPnl, expectedPreview);
  simSummary.textContent = `Inference done on ${resolved?.key || activeGrpcSeriesKey || '-'} | Model: ${prediction.modelName || PREBUILT_MODEL.name} | Signal: ${simSignal.textContent} | ${decision.reason}`;
}

function updatePredictionAndSimulation(series) {
  if (!Array.isArray(series) || series.length === 0) {
    simSummary.textContent = 'No active series data yet. Connect stream and wait for ticks.';
  }
  requestPrediction(series, false);
  const prediction = predictionState.lastResult;
  if (!prediction) {
    simSignal.textContent = '-';
    simPredPrice.textContent = '-';
    simExpPnl.textContent = '-';
    simLivePnl.textContent = '-';
    simLiveEquity.textContent = '-';
    simPosition.textContent = '-';
    if (predictionState.lastError) {
      simSummary.textContent = `Prediction service unavailable: ${predictionState.lastError}.`;
    }
    return;
  }

  const capitalPreview = parseCapitalInput() || 5000;
  const qtyPreview = Number.isFinite(capitalPreview) && capitalPreview > 0
    ? capitalPreview / prediction.lastPrice
    : 0;
  const latest = Array.isArray(series) && series.length > 0 ? series[series.length - 1] : null;
  const decision = decideTradeByStrategy(prediction, latest);
  const direction = decision.action === 'SHORT' ? -1 : 1;
  const expectedPreview = (prediction.predictedPrice - prediction.lastPrice) * qtyPreview * direction;
  simSignal.textContent = decision.action;
  simPredPrice.textContent = `$${prediction.predictedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  simExpPnl.textContent = formatUsdSigned(expectedPreview);
  setPnlColor(simExpPnl, expectedPreview);

  if (!simState.open) {
    simLivePnl.textContent = '-';
    simLiveEquity.textContent = '-';
    simPosition.textContent = '-';
    if (!autoTradeState.running) {
      simSummary.textContent = `Model ${(prediction.modelName || PREBUILT_MODEL.name)} on ${activeGrpcSeriesKey || '-'}: ${decision.action} | ${decision.reason}`;
    }
    renderAccountStats(prediction.lastPrice);
    updateSessionProfitFromEquity(prediction.lastPrice);

    if (autoTradeState.running) {
      const now = Date.now();
      if (now >= autoTradeState.endTs) {
        stopAutoTradingSession('Auto trading time range ended');
      } else if (shouldEnterAuto(decision)) {
        const resolved = resolveActiveSeries();
        const capital = parseCapitalInput() || 5000;
        const horizonSec = Number(simHorizonInput?.value || 30);
        openSimulationFromPrediction(
          prediction,
          resolved?.key || activeGrpcSeriesKey,
          capital,
          horizonSec,
          'auto',
          decision.action,
          decision.reason
        );
      }
    }
    return;
  }

  const activeSeries = grpcSeriesByKey.get(simState.seriesKey);
  const lastPoint = Array.isArray(activeSeries) && activeSeries.length > 0
    ? activeSeries[activeSeries.length - 1]
    : null;
  if (!lastPoint) {
    return;
  }

  const livePnl = simState.side === 'SHORT'
    ? (simState.entryPrice - lastPoint.price) * simState.qty
    : (lastPoint.price - simState.entryPrice) * simState.qty;
  const liveEquity = simState.capital + livePnl;
  const elapsedMs = Date.now() - simState.openedTs;
  const leftMs = Math.max(0, simState.horizonMs - elapsedMs);

  simLivePnl.textContent = formatUsdSigned(livePnl);
  simLiveEquity.textContent = formatUsd(liveEquity);
  simPosition.textContent = `${simState.side} ${simState.qty.toFixed(4)} (${leftMs}ms left)`;
  setPnlColor(simLivePnl, livePnl);
  setPnlColor(simLiveEquity, livePnl);
  renderAccountStats(lastPoint.price);
  updateSessionProfitFromEquity(lastPoint.price);

  if (leftMs <= 0) {
    simPosition.textContent = `${simState.side} ${simState.qty.toFixed(4)} (decision...)`;
    evaluateHorizonDecision(activeSeries);
  }

  // Fast defensive exit for short-term alpha when signal flips.
  if (simState.open && simState.strategy === 'short_term_alpha') {
    const flip =
      (simState.side === 'LONG' && decision.action === 'SHORT') ||
      (simState.side === 'SHORT' && decision.action === 'LONG');
    if (flip) {
      closeSimulation(`Alpha protective exit on signal flip (${decision.action})`, {
        recordInSession: autoTradeState.running
      });
      return;
    }
  }

  if (autoTradeState.running && Date.now() >= autoTradeState.endTs) {
    stopAutoTradingSession('Auto trading time range ended');
  }
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
  const statsRenderMs = 120;

  function frame(now) {
    let processed = 0;
    while (pointQueue.length > 0 && processed < 200) {
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
      drawGrpcSeries(series);
      updatePredictionAndSimulation(series);
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
  const subscriptions = getSubscriptions();
  const primary = subscriptions[0] || { symbol: 'BTC-USDT', channel: 'books5' };
  pickActiveGrpcSeriesKey(subscriptions);
  notifyChartSymbol(primary.symbol);
  await window.streamApi.start({
    symbol: primary.symbol,
    channel: primary.channel,
    subscriptions,
    url: urlInput.value.trim(),
    simulated: false
  });
});

simulateBtn.addEventListener('click', async () => {
  const subscriptions = getSubscriptions();
  const primary = subscriptions[0] || { symbol: 'BTC-USDT', channel: 'books5' };
  pickActiveGrpcSeriesKey(subscriptions);
  notifyChartSymbol(primary.symbol);
  await window.streamApi.start({
    symbol: primary.symbol,
    subscriptions,
    simulated: true
  });
});

stopBtn.addEventListener('click', async () => {
  if (autoTradeState.running) {
    stopAutoTradingSession('Auto trading stopped because stream stopped');
  } else {
    closeSimulation('Position closed because stream stopped');
  }
  await window.streamApi.stop();
});

simAutoStartBtn?.addEventListener('click', () => {
  startAutoTradingSession();
});

simAutoStopBtn?.addEventListener('click', () => {
  stopAutoTradingSession('Auto trading stopped by user');
});

simModelSelect?.addEventListener('change', () => {
  predictionState.lastResult = null;
  predictionState.lastError = '';
  refreshStrategyUi();
});

simConfigSelect?.addEventListener('change', () => {
  applyConfigProfile(simConfigSelect.value);
});

simStrategySelect?.addEventListener('change', () => {
  refreshStrategyUi();
});

simCapitalInput?.addEventListener('focus', () => {
  const capital = parseCapitalInput();
  if (capital > 0) {
    simCapitalInput.value = String(Math.round(capital));
  }
});

simCapitalInput?.addEventListener('blur', () => {
  formatCapitalInput();
});

simAccountInput?.addEventListener('focus', () => {
  const balance = parseAccountInput();
  if (balance > 0) {
    simAccountInput.value = String(Math.round(balance));
  }
});

simAccountInput?.addEventListener('blur', () => {
  formatAccountInput();
  if (!simState.open) {
    resetAccount();
  }
});

simAccountResetBtn?.addEventListener('click', () => {
  resetAccount();
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

subscriptionRows.appendChild(createSubscriptionRow({ symbol: 'BTC-USDT', channel: 'books5' }));
subscriptionRows.appendChild(createSubscriptionRow({ symbol: 'BTC-USDT', channel: 'trades' }));
notifyChartSymbol('BTC-USDT');
pickActiveGrpcSeriesKey(getSubscriptions());

formatCapitalInput();
formatAccountInput();
initializeAccountIfNeeded();
renderAutoSessionStats();
refreshStrategyUi();
refreshAutoBadge();
initGrpcCanvas();
startLoop();
