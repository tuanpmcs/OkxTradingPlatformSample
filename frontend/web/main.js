const stateEl = document.getElementById('state');
const priceEl = document.getElementById('price');
const signalEl = document.getElementById('signal');
const predRetEl = document.getElementById('pred-ret');
const logEl = document.getElementById('log');
const symbolEl = document.getElementById('symbol');
const gatewayUrlEl = document.getElementById('gateway-url');
const gatewayModeEl = document.getElementById('gateway-mode');
const modelTypeEl = document.getElementById('model-type');
const chartMetaEl = document.getElementById('chart-meta');

const startBtn = document.getElementById('start-btn');
const stopBtn = document.getElementById('stop-btn');
const healthBtn = document.getElementById('health-btn');

const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');

const points = [];
let timer = null;
let price = 95000;
let lastPredictMs = 0;
let lastSignal = '-';
let lastTickTs = 0;
let lastInvalidLogMs = 0;
let lastStreamWarnMs = 0;
let chartWidth = 1200;
let chartHeight = 380;
let resizeObserver = null;

function setState(text) {
  stateEl.textContent = text;
}

function appendLog(text) {
  const ts = new Date().toISOString();
  logEl.textContent = `[${ts}] ${text}\n${logEl.textContent}`.slice(0, 8000);
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : NaN;
}

function toPositive(value) {
  const n = toNumber(value);
  return n > 0 ? n : NaN;
}

function firstPositive(...values) {
  for (const v of values) {
    const n = toPositive(v);
    if (Number.isFinite(n)) return n;
  }
  return NaN;
}

function resolveTick(tickData) {
  const fields = tickData?.fields || {};
  const ts = toNumber(tickData?.ts) || Date.now();

  const bidPx = firstPositive(fields.bidPx, fields.bid_px, tickData?.bidPx, tickData?.bid_px);
  const askPx = firstPositive(fields.askPx, fields.ask_px, tickData?.askPx, tickData?.ask_px);
  const midPrice = firstPositive(fields.mid_price, fields.midPrice, tickData?.mid_price, tickData?.midPrice);
  const basePrice = firstPositive(tickData?.price, fields.price, fields.px);

  let resolvedPrice = basePrice;
  if (!Number.isFinite(resolvedPrice)) resolvedPrice = midPrice;
  if (!Number.isFinite(resolvedPrice) && Number.isFinite(bidPx) && Number.isFinite(askPx) && askPx >= bidPx) {
    resolvedPrice = (bidPx + askPx) * 0.5;
  }

  const bidSz = firstPositive(fields.bidSz, fields.bid_sz, tickData?.bidSz, tickData?.bid_sz);
  const askSz = firstPositive(fields.askSz, fields.ask_sz, tickData?.askSz, tickData?.ask_sz);
  const spread = Number.isFinite(askPx) && Number.isFinite(bidPx) ? Math.max(0, askPx - bidPx) : NaN;
  const volume = Math.max(0, toNumber(fields.trade_volume) || toNumber(fields.tradeVolume) || 0);

  if (!Number.isFinite(resolvedPrice) || resolvedPrice <= 0) {
    return null;
  }

  return {
    ts: Math.max(1, ts),
    price: resolvedPrice,
    bidPx: Number.isFinite(bidPx) ? bidPx : resolvedPrice * 0.9999,
    askPx: Number.isFinite(askPx) ? askPx : resolvedPrice * 1.0001,
    bidSz: Number.isFinite(bidSz) ? bidSz : 1,
    askSz: Number.isFinite(askSz) ? askSz : 1,
    spread: Number.isFinite(spread) ? spread : 0,
    volume
  };
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(240, Math.floor(rect.height));
  chartWidth = width;
  chartHeight = height;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function initCanvas() {
  resizeCanvas();
  if (typeof ResizeObserver === 'function') {
    resizeObserver = new ResizeObserver(() => resizeCanvas());
    resizeObserver.observe(canvas);
  } else {
    window.addEventListener('resize', resizeCanvas);
  }
}

function fmtClock(ts) {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function drawChart() {
  const w = chartWidth;
  const h = chartHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#08131e';
  ctx.fillRect(0, 0, w, h);

  if (points.length < 2) {
    ctx.fillStyle = '#8db2c6';
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.fillText('Waiting for market points...', 12, 24);
    chartMetaEl.textContent = 'Waiting for market stream...';
    return;
  }

  const left = 14;
  const right = w - 66;
  const top = 16;
  const priceBottom = Math.floor(h * 0.72);
  const volTop = priceBottom + 10;
  const volBottom = h - 28;
  const spanX = Math.max(1, right - left);

  let minPrice = Number.POSITIVE_INFINITY;
  let maxPrice = Number.NEGATIVE_INFINITY;
  let minTs = Number.POSITIVE_INFINITY;
  let maxTs = Number.NEGATIVE_INFINITY;
  let maxVol = 0;
  for (const p of points) {
    if (p.price < minPrice) minPrice = p.price;
    if (p.price > maxPrice) maxPrice = p.price;
    if (p.ts < minTs) minTs = p.ts;
    if (p.ts > maxTs) maxTs = p.ts;
    if (p.volume > maxVol) maxVol = p.volume;
  }

  const pad = (maxPrice - minPrice) * 0.1 || Math.max(1, maxPrice * 0.001);
  minPrice -= pad;
  maxPrice += pad;
  const priceRange = Math.max(1e-9, maxPrice - minPrice);
  const timeRange = Math.max(1, maxTs - minTs);
  const priceSpanY = Math.max(1, priceBottom - top);
  const volSpanY = Math.max(1, volBottom - volTop);
  const volRange = Math.max(1e-9, maxVol);

  ctx.strokeStyle = 'rgba(148, 199, 229, 0.22)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = top + (priceSpanY * i) / 3;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  for (let i = 0; i < 4; i += 1) {
    const x = left + (spanX * i) / 3;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, volBottom);
    ctx.stroke();
  }

  const gradient = ctx.createLinearGradient(0, top, 0, priceBottom);
  gradient.addColorStop(0, 'rgba(72, 184, 255, 0.26)');
  gradient.addColorStop(1, 'rgba(72, 184, 255, 0.02)');
  ctx.fillStyle = gradient;
  ctx.beginPath();
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const x = left + ((p.ts - minTs) / timeRange) * spanX;
    const y = priceBottom - ((p.price - minPrice) / priceRange) * priceSpanY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.lineTo(right, priceBottom);
  ctx.lineTo(left, priceBottom);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = '#48b8ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const x = left + ((p.ts - minTs) / timeRange) * spanX;
    const y = priceBottom - ((p.price - minPrice) / priceRange) * priceSpanY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  const barWidth = Math.max(2, Math.floor(spanX / Math.min(points.length, 80)) - 1);
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const x = left + ((p.ts - minTs) / timeRange) * spanX;
    const hBar = (p.volume / volRange) * volSpanY;
    ctx.fillStyle = 'rgba(71, 204, 162, 0.42)';
    ctx.fillRect(x - barWidth * 0.5, volBottom - hBar, barWidth, hBar);
  }

  ctx.fillStyle = '#94bed3';
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  for (let i = 0; i < 4; i += 1) {
    const n = i / 3;
    const y = priceBottom - n * priceSpanY;
    const p = minPrice + n * priceRange;
    ctx.fillText(p.toFixed(2), right + 6, y + 3);
  }

  ctx.textAlign = 'center';
  for (let i = 0; i < 4; i += 1) {
    const n = i / 3;
    const x = left + n * spanX;
    const t = minTs + n * timeRange;
    ctx.fillText(fmtClock(t), x, h - 8);
  }

  const last = points[points.length - 1];
  const prev = points[points.length - 2];
  const delta = last.price - prev.price;
  ctx.fillStyle = delta >= 0 ? '#31cf97' : '#ff6b5e';
  ctx.textAlign = 'left';
  ctx.font = '12px "IBM Plex Mono", monospace';
  ctx.fillText(`last=${last.price.toFixed(2)} delta=${delta.toFixed(2)}`, left, h - 8);

  chartMetaEl.textContent = `window=${Math.round((last.ts - points[0].ts) / 1000)}s | spread=${last.spread.toFixed(2)} | volume=${last.volume.toFixed(5)}`;
}

function buildPredictPayload() {
  return {
    symbol: symbolEl.value || 'BTC-USDT',
    channel: 'books',
    modelType: modelTypeEl?.value || 'xgboost',
    horizonSec: 30,
    strategyMode: 'market_making',
    points: points.slice(-64).map((p) => ({
      ts: p.ts,
      price: p.price,
      bidPx: p.bidPx,
      askPx: p.askPx,
      bidSz: p.bidSz,
      askSz: p.askSz
    }))
  };
}

async function maybePredict(nowMs) {
  if (!gatewayModeEl.checked) return;
  if (nowMs - lastPredictMs < 800 || points.length < 16) return;
  lastPredictMs = nowMs;

  const base = gatewayUrlEl.value.trim().replace(/\/$/, '');
  const url = `${base}/predict`;
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(buildPredictPayload())
    });
    const json = await resp.json();
    if (!json.ok || !json.prediction) {
      appendLog(`predict error: ${json.error || 'unknown'}`);
      return;
    }
    const pred = json.prediction;
    lastSignal = pred.signal || '-';
    signalEl.textContent = lastSignal;
    predRetEl.textContent = Number(pred.predicted_return || 0).toFixed(6);
  } catch (error) {
    appendLog(`gateway unreachable: ${String(error.message || error)}`);
  }
}

async function fetchBackendTick() {
  const base = gatewayUrlEl.value.trim().replace(/\/$/, '');
  const symbol = encodeURIComponent(symbolEl.value || 'BTC-USDT');
  const url = `${base}/market/latest?symbol=${symbol}&channel=books`;
  const resp = await fetch(url);
  const json = await resp.json();
  if (!json.ok || !json.tick) {
    throw new Error(json.error || 'no market tick yet');
  }
  return json.tick;
}

async function tick() {
  const now = Date.now();
  let nextPoint = null;

  if (gatewayModeEl.checked) {
    try {
      const tickData = await fetchBackendTick();
      const parsed = resolveTick(tickData);
      if (!parsed) {
        if (now - lastInvalidLogMs > 2200) {
          appendLog('stream waiting for valid price snapshot');
          lastInvalidLogMs = now;
        }
        return;
      }
      if (parsed.ts <= lastTickTs) {
        return;
      }
      lastTickTs = parsed.ts;
      nextPoint = parsed;
      price = parsed.price;
    } catch (error) {
      if (now - lastStreamWarnMs > 2500) {
        appendLog(`stream unavailable: ${String(error.message || error)}`);
        lastStreamWarnMs = now;
      }
      return;
    }
  } else {
    const shock = (Math.random() - 0.5) * 18;
    const drift = Math.sin(now / 2200) * 0.5;
    price = Math.max(100, price + shock + drift);
    nextPoint = {
      ts: now,
      price,
      bidPx: price - 0.2,
      askPx: price + 0.2,
      bidSz: 1.2,
      askSz: 1.4,
      spread: 0.4,
      volume: 0.01 + Math.random() * 0.05
    };
  }

  if (!nextPoint) return;
  points.push(nextPoint);
  if (points.length > 320) points.shift();

  priceEl.textContent = price.toFixed(2);
  signalEl.textContent = lastSignal;
  drawChart();
  void maybePredict(nextPoint.ts);
}

function start() {
  if (timer) return;
  setState(gatewayModeEl.checked ? 'running (gateway)' : 'running (simulated)');
  appendLog('stream started');
  timer = setInterval(() => {
    void tick();
  }, 150);
}

function stop() {
  if (!timer) return;
  clearInterval(timer);
  timer = null;
  setState('stopped');
  appendLog('stream stopped');
}

async function checkGateway() {
  const base = gatewayUrlEl.value.trim().replace(/\/$/, '');
  const url = `${base}/health`;
  try {
    const resp = await fetch(url);
    const json = await resp.json();
    appendLog(`gateway ok: ${JSON.stringify(json)}`);
  } catch (error) {
    appendLog(`gateway health failed: ${String(error.message || error)}`);
  }
}

startBtn.addEventListener('click', start);
stopBtn.addEventListener('click', stop);
healthBtn.addEventListener('click', () => {
  void checkGateway();
});

initCanvas();
setState('idle');
appendLog('ready');
drawChart();
