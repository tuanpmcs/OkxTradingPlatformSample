(function initPulseSimulator(global) {
  function asNumber(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function parseMoneyInput(inputEl, fallback = 0) {
    const raw = String(inputEl?.value || '').trim();
    const cleaned = raw.replace(/[^0-9.]/g, '');
    const numeric = Number(cleaned);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function parsePositiveNumber(inputEl, fallback) {
    const n = Number(inputEl?.value);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  function formatUsd(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  }

  function formatUsdSigned(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    const sign = n >= 0 ? '+' : '-';
    return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  }

  function setPnlColor(el, value) {
    if (!el) return;
    const n = Number(value);
    if (!Number.isFinite(n)) {
      el.style.color = '';
      return;
    }
    el.style.color = n >= 0 ? 'var(--good)' : 'var(--bad)';
  }

  function parseBookStatsFromPoint(point) {
    const fields = point?.fields || {};
    // Support both payload shapes:
    // 1) raw stream payload: point.fields.bidPx/askPx
    // 2) normalized series point: point.bidPx/askPx
    const bid = Number(point?.bidPx ?? point?.bid_px ?? fields.bidPx ?? fields.bid_px);
    const ask = Number(point?.askPx ?? point?.ask_px ?? fields.askPx ?? fields.ask_px);
    const bidSz = Number(point?.bidSz ?? point?.bid_sz ?? fields.bidSz ?? fields.bid_sz);
    const askSz = Number(point?.askSz ?? point?.ask_sz ?? fields.askSz ?? fields.ask_sz);
    if (!Number.isFinite(bid) || !Number.isFinite(ask) || bid <= 0 || ask <= bid) {
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

  function normalizeDecisionAction(action) {
    if (!action) return 'HOLD';
    const value = String(action).toUpperCase();
    if (value === 'BUY' || value === 'LONG') return 'LONG';
    if (value === 'SELL' || value === 'SHORT') return 'SHORT';
    return 'HOLD';
  }

  function pickNumber(...values) {
    for (const value of values) {
      const n = Number(value);
      if (Number.isFinite(n)) return n;
    }
    return NaN;
  }

  function predictionLastPrice(prediction) {
    return pickNumber(prediction?.lastPrice, prediction?.last_price);
  }

  function predictionPrice(prediction) {
    return pickNumber(prediction?.predictedPrice, prediction?.predicted_price);
  }

  function predictionSignedReturn(prediction) {
    const direct = pickNumber(
      prediction?.predictedReturn,
      prediction?.predicted_return,
      prediction?.score
    );
    if (Number.isFinite(direct)) return direct;
    const last = predictionLastPrice(prediction);
    const pred = predictionPrice(prediction);
    if (Number.isFinite(last) && last > 0 && Number.isFinite(pred)) {
      return (pred - last) / last;
    }
    return 0;
  }

  function predictionAction(prediction) {
    const signalAction = normalizeDecisionAction(prediction?.signal);
    if (signalAction !== 'HOLD') return signalAction;
    const ret = predictionSignedReturn(prediction);
    if (ret > 0) return 'LONG';
    if (ret < 0) return 'SHORT';
    return 'HOLD';
  }

  function predictionReasonText(prediction) {
    const detail = prediction?.detail;
    if (typeof detail !== 'string') {
      return '';
    }
    const raw = detail.trim();
    if (!raw) return '';
    return raw.length > 140 ? `${raw.slice(0, 137)}...` : raw;
  }

  function formatReturnBps(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    const bps = n * 10000;
    const sign = bps >= 0 ? '+' : '';
    const rawSign = n >= 0 ? '+' : '';
    return `${sign}${bps.toFixed(4)} bps (${rawSign}${n.toFixed(8)})`;
  }

  function formatModelLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'xgboost' || normalized === 'xgb') return 'XGBoost';
    if (normalized === 'lightgbm' || normalized === 'lgbm') return 'LightGBM';
    return value ? String(value) : 'Unknown';
  }

  function formatRatio(value, digits = 5) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return n.toFixed(digits);
  }

  function formatBpsValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return `${n.toFixed(2)} bps`;
  }

  const EXECUTION_COST = {
    feeBpsPerSide: 0.0,
    slippageBpsPerSide: 0.0,
    spreadImpactRatio: 0.0,
    fallbackSpreadBps: 1.0
  };

  function bpsToRatio(bps) {
    return Number(bps) / 10000;
  }

  function toMidPrice(point, fallbackPrice) {
    const book = parseBookStatsFromPoint(point);
    if (book && Number.isFinite(book.mid) && book.mid > 0) {
      return book.mid;
    }
    const px = Number(fallbackPrice);
    if (Number.isFinite(px) && px > 0) return px;
    return NaN;
  }

  function estimateExecutionPrice(side, phase, point, fallbackPrice) {
    const mid = toMidPrice(point, fallbackPrice);
    if (!Number.isFinite(mid) || mid <= 0) return NaN;
    const book = parseBookStatsFromPoint(point);
    const spreadBps = book ? book.spreadBps : EXECUTION_COST.fallbackSpreadBps;
    const spreadHalfRatio = bpsToRatio(spreadBps * 0.5 * EXECUTION_COST.spreadImpactRatio);
    const slipRatio = bpsToRatio(EXECUTION_COST.slippageBpsPerSide);
    const plus = 1 + spreadHalfRatio + slipRatio;
    const minus = 1 - spreadHalfRatio - slipRatio;
    const isLong = side === 'LONG';

    if (phase === 'entry') {
      return isLong ? mid * plus : mid * minus;
    }
    return isLong ? mid * minus : mid * plus;
  }

  function computeNetPnl(side, qty, entryExecPrice, exitExecPrice) {
    const gross = side === 'SHORT'
      ? (entryExecPrice - exitExecPrice) * qty
      : (exitExecPrice - entryExecPrice) * qty;
    const feeRatio = bpsToRatio(EXECUTION_COST.feeBpsPerSide);
    const entryFee = qty * entryExecPrice * feeRatio;
    const exitFee = qty * exitExecPrice * feeRatio;
    const net = gross - entryFee - exitFee;
    return {
      gross,
      entryFee,
      exitFee,
      totalFee: entryFee + exitFee,
      net
    };
  }

  function computeExpectedPnlFromExecutableReturn(side, capital, predRet) {
    const signed = Number(predRet);
    const notional = Number(capital);
    if (!Number.isFinite(signed) || !Number.isFinite(notional) || notional <= 0) {
      return { gross: 0, entryFee: 0, exitFee: 0, totalFee: 0, net: 0 };
    }
    const directionalRet = side === 'SHORT' ? -signed : signed;
    const gross = notional * directionalRet;
    const feeRatio = bpsToRatio(EXECUTION_COST.feeBpsPerSide);
    const entryFee = notional * feeRatio;
    const exitFee = Math.max(0, notional + gross) * feeRatio;
    const totalFee = entryFee + exitFee;
    return {
      gross,
      entryFee,
      exitFee,
      totalFee,
      net: gross - totalFee
    };
  }

  function create(options) {
    const {
      elements,
      modelOptions,
      configProfiles,
      callbacks
    } = options;

    const state = {
      position: {
        open: false,
        side: 'LONG',
        strategy: 'market_making',
        seriesKey: '',
        capital: 0,
        qty: 0,
        entryExecPrice: 0,
        entryPrice: 0,
        predictedPrice: 0,
        expectedPnl: 0,
        openedAt: 0,
        holdMs: 500,
        pendingDecision: false,
        holdCycles: 0
      },
      auto: {
        running: false,
        endTs: 0,
        totalPnl: 0,
        sessionStartEquity: 0,
        trades: 0,
        wins: 0,
        losses: 0,
        lastEntryTs: 0
      },
      account: {
        initialized: false,
        cash: 0,
        equity: 0,
        lastAction: '-'
      }
    };

    function parseCapitalInput() {
      return parseMoneyInput(elements.simCapitalInput, 0);
    }

    function parseAccountInput() {
      return parseMoneyInput(elements.simAccountInput, 0);
    }

    function formatCapitalInput() {
      const capital = parseCapitalInput();
      if (!Number.isFinite(capital) || capital <= 0 || !elements.simCapitalInput) {
        return;
      }
      elements.simCapitalInput.value = Math.round(capital).toLocaleString();
    }

    function formatAccountInput() {
      const balance = parseAccountInput();
      if (!Number.isFinite(balance) || balance <= 0 || !elements.simAccountInput) {
        return;
      }
      elements.simAccountInput.value = Math.round(balance).toLocaleString();
    }

    function readStrategyConfig() {
      const profileKey = String(elements.simConfigSelect?.value || 'market_maker');
      const profile = configProfiles[profileKey] || configProfiles.market_maker;
      const adverseThreshold = parsePositiveNumber(elements.simAdverseInput, profile.adverseThreshold);
      const minSpreadBps = parsePositiveNumber(elements.simMinSpreadInput, profile.minSpreadBps);

      return {
        modelType: String(elements.simModelSelect?.value || 'xgboost'),
        profile: profileKey,
        strategy: String(elements.simStrategySelect?.value || profile.strategy),
        holdMs: Math.max(50, Math.round(parsePositiveNumber(elements.simHoldMsInput, profile.holdMs))),
        horizonMs: Math.max(50, Math.round(asNumber(elements.simHorizonInput?.value, profile.horizonMs || profile.holdMs))),
        rangeSec: Math.max(10, Math.round(asNumber(elements.simRangeInput?.value, profile.autoRangeSec))),
        imbalanceThreshold: parsePositiveNumber(elements.simImbalanceInput, profile.imbalanceThreshold),
        adverseThreshold,
        minSpreadBps,
        alphaPredRetThreshold: Math.max(0.00001, adverseThreshold * 0.2),
        maxEntrySpreadBps: Math.max(3, minSpreadBps * 3),
        alphaCooldownMs: profile.alphaCooldownMs
      };
    }

    function refreshStrategyUi() {
      const cfg = readStrategyConfig();
      const profile = configProfiles[cfg.profile] || configProfiles.market_maker;
      const isMM = cfg.strategy === 'market_making';
      const lastPrediction = callbacks.getLastPrediction ? callbacks.getLastPrediction() : null;
      const lastError = callbacks.getPredictionError ? callbacks.getPredictionError() : '';
      const requestedModel = callbacks.getLastRequestedModelType
        ? callbacks.getLastRequestedModelType()
        : cfg.modelType;
      const runtimeModel = lastPrediction?.modelName || '';

      if (elements.simModelBadge) {
        const requestedLabel = modelOptions[cfg.modelType] || formatModelLabel(requestedModel);
        const runtimeLabel = runtimeModel || (lastError ? 'Fallback / unavailable' : 'Waiting');
        elements.simModelBadge.textContent = `Requested: ${requestedLabel} | Runtime: ${runtimeLabel}`;
      }
      if (elements.simModeBadge) {
        elements.simModeBadge.textContent = `Mode: ${profile.label}${lastError ? ' | Source: fallback' : runtimeModel ? ' | Source: server' : ''}`;
      }
      if (elements.simRuleHint) {
        elements.simRuleHint.textContent = isMM
          ? 'Quote both sides, skip adverse windows.'
          : cfg.profile === 'alpha_ultra'
            ? 'Ultra fast alpha entries with tight confirmation.'
            : 'Fast alpha entries on imbalance and model confirmation.';
      }
      if (elements.simAdverseTitle) {
        elements.simAdverseTitle.textContent = isMM ? 'Adverse Filter' : 'Model Confirm Threshold';
      }
      if (elements.simAdverseHelp) {
        elements.simAdverseHelp.textContent = isMM
          ? 'Skip quotes when predicted return magnitude is too directional.'
          : 'Minimum model edge before alpha entries are allowed.';
      }
      elements.simMinSpreadWrap?.classList.toggle('input-muted', !isMM);
      elements.simAdverseWrap?.classList.toggle('input-muted', false);
      if (elements.simMmOneSidedValue) {
        elements.simMmOneSidedValue.textContent = formatRatio(cfg.imbalanceThreshold, 3);
      }
      if (elements.simAlphaConfirmValue) {
        elements.simAlphaConfirmValue.textContent = formatRatio(cfg.alphaPredRetThreshold, 8);
      }
      if (elements.simMaxEntrySpreadValue) {
        elements.simMaxEntrySpreadValue.textContent = formatBpsValue(cfg.maxEntrySpreadBps);
      }
      if (elements.simAlphaCooldownValue) {
        elements.simAlphaCooldownValue.textContent = `${Math.round(cfg.alphaCooldownMs)} ms`;
      }
      if (elements.simDecisionBasis) {
        elements.simDecisionBasis.textContent = isMM
          ? `MM quotes only when spread stays above ${formatBpsValue(cfg.minSpreadBps)}, imbalance stays inside ${formatRatio(cfg.imbalanceThreshold, 3)}, and |pred_ret| stays below ${formatRatio(cfg.adverseThreshold, 8)}.`
          : `Alpha entries require |pred_ret| above ${formatRatio(cfg.alphaPredRetThreshold, 8)}, spread below ${formatBpsValue(cfg.maxEntrySpreadBps)}, and respect a ${Math.round(cfg.alphaCooldownMs)} ms cooldown.`;
      }
    }

    function refreshAutoBadge() {
      if (!elements.simAutoBadge) return;
      elements.simAutoBadge.classList.toggle('sim-badge-live', state.auto.running);
      elements.simAutoBadge.classList.toggle('sim-badge-idle', !state.auto.running);
      elements.simAutoBadge.textContent = state.auto.running ? 'Auto: RUNNING' : 'Auto: OFF';
    }

    function applyConfigProfile(profileKey = 'market_maker') {
      const profile = configProfiles[profileKey] || configProfiles.market_maker;
      if (elements.simConfigSelect) elements.simConfigSelect.value = profileKey;
      if (elements.simStrategySelect) elements.simStrategySelect.value = profile.strategy;
      if (elements.simCapitalInput) elements.simCapitalInput.value = profile.capital;
      if (elements.simHoldMsInput) elements.simHoldMsInput.value = String(profile.holdMs);
      if (elements.simHorizonInput) elements.simHorizonInput.value = String(profile.horizonMs || profile.holdMs);
      if (elements.simRangeInput) elements.simRangeInput.value = String(profile.autoRangeSec);
      if (elements.simImbalanceInput) elements.simImbalanceInput.value = String(profile.imbalanceThreshold);
      if (elements.simAdverseInput) elements.simAdverseInput.value = String(profile.adverseThreshold);
      if (elements.simMinSpreadInput) elements.simMinSpreadInput.value = String(profile.minSpreadBps);
      if (elements.simSummary) elements.simSummary.textContent = profile.summary;
      formatCapitalInput();
      refreshStrategyUi();
    }

    function initializeAccountIfNeeded() {
      if (state.account.initialized) return;
      const init = parseAccountInput();
      state.account.cash = Number.isFinite(init) && init > 0 ? init : 20000;
      state.account.equity = state.account.cash;
      state.account.lastAction = 'INIT';
      state.account.initialized = true;
      renderAccountStats();
    }

    function renderAccountStats(marketPoint = null, fallbackPrice = null) {
      if (!state.account.initialized) {
        elements.simAccountCash.textContent = '-';
        elements.simAccountEquity.textContent = '-';
        elements.simAccountAction.textContent = '-';
        return;
      }

      let positionValue = 0;
      if (state.position.open) {
        const markFallback = Number.isFinite(Number(fallbackPrice))
          ? Number(fallbackPrice)
          : state.position.entryPrice;
        const markExit = estimateExecutionPrice(state.position.side, 'exit', marketPoint, markFallback);
        if (Number.isFinite(markExit) && markExit > 0) {
          const live = computeNetPnl(
            state.position.side,
            state.position.qty,
            state.position.entryExecPrice || state.position.entryPrice,
            markExit
          );
          positionValue = state.position.capital + live.net;
        } else {
          positionValue = state.position.capital;
        }
      }

      state.account.equity = state.account.cash + positionValue;
      elements.simAccountCash.textContent = formatUsd(state.account.cash);
      elements.simAccountEquity.textContent = formatUsd(state.account.equity);
      elements.simAccountAction.textContent = state.account.lastAction || '-';
      setPnlColor(elements.simAccountCash, state.account.cash);
      setPnlColor(elements.simAccountEquity, state.account.equity);
    }

    function renderAutoSessionStats() {
      elements.simTradeCount.textContent = String(state.auto.trades);
      elements.simTotalPnl.textContent = formatUsdSigned(state.auto.totalPnl);
      setPnlColor(elements.simTotalPnl, state.auto.totalPnl);
    }

    function updateSessionProfitFromEquity(marketPoint = null, fallbackPrice = null) {
      if (!state.auto.running || !state.account.initialized) return;
      renderAccountStats(marketPoint, fallbackPrice);
      state.auto.totalPnl = state.account.equity - state.auto.sessionStartEquity;
      renderAutoSessionStats();
    }

    function resetAccount() {
      if (state.position.open) {
        closePosition('Account reset -> close executed');
      }
      const init = parseAccountInput();
      state.account.cash = Number.isFinite(init) && init > 0 ? init : 20000;
      state.account.equity = state.account.cash;
      state.account.lastAction = 'RESET';
      state.account.initialized = true;
      renderAccountStats();
      elements.simSummary.textContent = `Account reset to ${formatUsd(state.account.cash)}.`;
    }

    function shouldEnterAuto(decision) {
      if (!decision || decision.action === 'HOLD') return false;
      const cfg = readStrategyConfig();
      if (cfg.strategy === 'short_term_alpha') {
        const now = Date.now();
        if (now - state.auto.lastEntryTs < cfg.alphaCooldownMs) {
          return false;
        }
      }
      return true;
    }

    function deriveAutoEntryDecision(baseDecision, prediction, point) {
      const cfg = readStrategyConfig();
      const baseAction = normalizeDecisionAction(baseDecision?.action);
      const action = baseAction !== 'HOLD' ? baseAction : predictionAction(prediction);
      const predRet = predictionSignedReturn(prediction);
      const absRet = Math.abs(predRet);
      const book = parseBookStatsFromPoint(point);
      if (book && book.spreadBps > cfg.maxEntrySpreadBps) {
        return { action: 'HOLD', reason: `Auto wait: spread too wide (${book.spreadBps.toFixed(2)}bps)` };
      }

      const threshold = cfg.alphaPredRetThreshold;
      if (action === 'HOLD' || absRet < threshold) {
        return { action: 'HOLD', reason: `Auto wait: |pred_ret| ${absRet.toFixed(8)} < ${threshold.toFixed(8)}` };
      }
      const capital = parseCapitalInput() || 0;
      const expected = computeExpectedPnlFromExecutableReturn(action, capital, predRet);
      if (expected.net <= 0) {
        return { action: 'HOLD', reason: `Auto wait: net edge ${formatUsdSigned(expected.net)} <= $0` };
      }

      const reason = predictionReasonText(prediction);
      const sourceReason = baseDecision?.reason || reason;
      return {
        action,
        reason: sourceReason
          ? `Auto entry ${action} (${formatReturnBps(predRet)}, net ${formatUsdSigned(expected.net)}) | ${sourceReason}`
          : `Auto entry by prediction ${action} (${formatReturnBps(predRet)}, net ${formatUsdSigned(expected.net)})`
      };
    }

    function decideTradeByStrategy(prediction, point) {
      if (!prediction || !point) {
        return { action: 'HOLD', reason: 'No prediction/point' };
      }

      const cfg = readStrategyConfig();
      const predRet = predictionSignedReturn(prediction);
      const absPredRet = Math.abs(predRet);
      const serverDecision = predictionAction(prediction);
      const detailText = predictionReasonText(prediction);
      const book = parseBookStatsFromPoint(point);

      // Use prediction server decision as primary source of truth.
      if (serverDecision !== 'HOLD') {
        if (book && book.spreadBps > cfg.maxEntrySpreadBps) {
          return { action: 'HOLD', reason: `Spread too wide (${book.spreadBps.toFixed(2)}bps)` };
        }
        return {
          action: serverDecision,
          reason: detailText ? `Server signal: ${serverDecision} | ${detailText}` : `Server signal: ${serverDecision}`
        };
      }

      if (cfg.strategy === 'market_making') {
        if (book && book.spreadBps < cfg.minSpreadBps) {
          return { action: 'HOLD', reason: `Spread ${book.spreadBps.toFixed(2)}bps below min` };
        }
        if (absPredRet >= cfg.adverseThreshold) {
          return { action: 'HOLD', reason: `Adverse filter hit (|pred_ret|=${absPredRet.toFixed(8)})` };
        }
        if (book && book.imbalance >= cfg.imbalanceThreshold) {
          return { action: 'SHORT', reason: `MM one-sided risk (imb=${book.imbalance.toFixed(2)})` };
        }
        if (book && book.imbalance <= -cfg.imbalanceThreshold) {
          return { action: 'LONG', reason: `MM one-sided risk (imb=${book.imbalance.toFixed(2)})` };
        }
        if (absPredRet >= cfg.alphaPredRetThreshold) {
          return {
            action: predRet > 0 ? 'LONG' : 'SHORT',
            reason: `MM prediction drift (${predRet.toFixed(8)})`
          };
        }
        return { action: 'HOLD', reason: 'MM neutral conditions' };
      }

      if (book && book.spreadBps > cfg.maxEntrySpreadBps) {
        return { action: 'HOLD', reason: `Spread too wide (${book.spreadBps.toFixed(2)}bps)` };
      }
      if (absPredRet < cfg.alphaPredRetThreshold) {
        return {
          action: 'HOLD',
          reason: `Prediction weak (|pred_ret|=${absPredRet.toFixed(8)} < ${cfg.alphaPredRetThreshold.toFixed(8)})`
        };
      }
      return {
        action: predRet > 0 ? 'LONG' : 'SHORT',
        reason: `Alpha by predicted return (${predRet.toFixed(8)})`
      };
    }

    function openPosition(pred, seriesKey, mode, side, reasonText = '') {
      if (!pred) {
        elements.simSummary.textContent = 'Prediction not available.';
        return false;
      }
      const capital = parseCapitalInput();
      if (!Number.isFinite(capital) || capital <= 0) {
        elements.simSummary.textContent = 'Capital must be greater than 0.';
        return false;
      }
      initializeAccountIfNeeded();
      if (state.account.cash < capital) {
        elements.simSummary.textContent = `Insufficient account cash. Need ${formatUsd(capital)}, available ${formatUsd(state.account.cash)}.`;
        return false;
      }

      const action = normalizeDecisionAction(side);
      const lastPrice = predictionLastPrice(pred);
      const predPrice = predictionPrice(pred);
      const predRet = predictionSignedReturn(pred);
      const activeSeries = callbacks.getSeriesByKey(seriesKey || callbacks.getActiveSeriesKey());
      const latestPoint = Array.isArray(activeSeries) && activeSeries.length > 0
        ? activeSeries[activeSeries.length - 1]
        : null;
      const entryExecPrice = estimateExecutionPrice(action, 'entry', latestPoint, lastPrice);
      if (!Number.isFinite(entryExecPrice) || entryExecPrice <= 0) {
        elements.simSummary.textContent = 'Cannot open position: invalid entry price.';
        return false;
      }
      const qty = capital / entryExecPrice;
      const expected = computeExpectedPnlFromExecutableReturn(action, capital, predRet);
      if (mode === 'auto' && expected.net <= 0) {
        elements.simSummary.textContent = `Auto skipped: expected net edge ${formatUsdSigned(expected.net)} is not positive.`;
        return false;
      }
      const cfg = readStrategyConfig();

      state.position.open = true;
      state.position.side = action;
      state.position.strategy = cfg.strategy;
      state.position.seriesKey = seriesKey || callbacks.getActiveSeriesKey();
      state.position.capital = capital;
      state.position.qty = qty;
      state.position.entryExecPrice = entryExecPrice;
      state.position.entryPrice = lastPrice;
      state.position.predictedPrice = predPrice;
      state.position.predictedReturn = predRet;
      state.position.expectedPnl = expected.net;
      state.position.openedAt = Date.now();
      state.position.holdMs = cfg.holdMs;
      state.position.pendingDecision = false;
      state.position.holdCycles = 0;

      state.account.cash -= capital;
      state.account.lastAction = action === 'SHORT' ? 'SHORT' : 'BUY';
      if (mode === 'auto') {
        state.auto.lastEntryTs = Date.now();
      }

      renderAccountStats(latestPoint, lastPrice);
      const reason = reasonText ? ` | Reason: ${reasonText}` : '';
      elements.simSummary.textContent = `${action} opened on ${state.position.seriesKey} with ${formatUsd(capital)} | Mid: ${lastPrice.toFixed(2)} | Exec: ${entryExecPrice.toFixed(2)} | Predicted: ${predPrice.toFixed(2)} | Return: ${formatReturnBps(predRet)} | Expected: ${formatUsdSigned(expected.net)} | Hold: ${state.position.holdMs}ms${reason}`;
      return true;
    }

    function closePosition(reason = 'Closed', options = {}) {
      const { recordInSession = false } = options;
      if (!state.position.open) return;

      const activeSeries = callbacks.getSeriesByKey(state.position.seriesKey);
      const lastPoint = Array.isArray(activeSeries) && activeSeries.length > 0
        ? activeSeries[activeSeries.length - 1]
        : null;
      const markExit = Number(lastPoint?.price) || state.position.entryPrice;
      const exitExecPrice = estimateExecutionPrice(state.position.side, 'exit', lastPoint, markExit);
      const exitPrice = Number.isFinite(exitExecPrice) ? exitExecPrice : markExit;
      const isShort = state.position.side === 'SHORT';
      const pnl = computeNetPnl(state.position.side, state.position.qty, state.position.entryExecPrice || state.position.entryPrice, exitPrice);
      const realizedPnl = pnl.net;
      const settlement = state.position.capital + realizedPnl;
      state.account.cash += settlement;
      state.account.lastAction = isShort ? 'COVER' : 'SELL';

      state.position.open = false;
      state.position.pendingDecision = false;
      state.position.holdCycles = 0;

      elements.simLivePnl.textContent = formatUsdSigned(realizedPnl);
      elements.simLiveEquity.textContent = formatUsd(state.account.cash);
      elements.simPosition.textContent = `CLOSED (${isShort ? 'SHORT' : 'LONG'})`;
      setPnlColor(elements.simLivePnl, realizedPnl);
      setPnlColor(elements.simLiveEquity, realizedPnl);
      renderAccountStats(lastPoint, exitPrice);

      if (recordInSession) {
        state.auto.trades += 1;
        if (realizedPnl >= 0) state.auto.wins += 1;
        else state.auto.losses += 1;
        updateSessionProfitFromEquity(lastPoint, exitPrice);
      }

      elements.simSummary.textContent = `${reason}. ${isShort ? 'SHORT' : 'LONG'} @ ${state.position.entryExecPrice.toFixed(2)} -> CLOSE @ ${exitPrice.toFixed(2)} | Net PnL: ${formatUsdSigned(realizedPnl)} | Fees: ${formatUsd(pnl.totalFee)} | Equity: ${formatUsd(state.account.cash)}`;
    }

    async function evaluateCloseDecision(series) {
      if (!state.position.open || state.position.pendingDecision) return;
      state.position.pendingDecision = true;

      try {
        const pred = await callbacks.requestPrediction(series, true);
        const lastPoint = Array.isArray(series) && series.length > 0 ? series[series.length - 1] : null;
        const currentPrice = Number(lastPoint?.price) || state.position.entryPrice;
        const isAlpha = state.position.strategy === 'short_term_alpha';

        let shouldHold = false;
        if (!isAlpha && pred && Number.isFinite(currentPrice)) {
          const predPrice = predictionPrice(pred);
          shouldHold = state.position.side === 'SHORT'
            ? predPrice < currentPrice
            : predPrice > currentPrice;
        }

        if (shouldHold) {
          const predPrice = predictionPrice(pred);
          const predRet = predictionSignedReturn(pred);
          state.position.openedAt = Date.now();
          state.position.predictedPrice = predPrice;
          state.position.predictedReturn = predRet;
          const expectedExit = estimateExecutionPrice(state.position.side, 'exit', lastPoint, predPrice);
          const expected = computeNetPnl(
            state.position.side,
            state.position.qty,
            state.position.entryExecPrice || state.position.entryPrice,
            Number.isFinite(expectedExit) ? expectedExit : predPrice
          );
          state.position.expectedPnl = expected.net;
          state.position.holdCycles += 1;
          elements.simSummary.textContent = `Hold window reached -> EXTEND (${state.position.holdCycles}) | Side: ${state.position.side} | Predicted: ${predPrice.toFixed(2)} | Return: ${formatReturnBps(predRet)} | Expected: ${formatUsdSigned(expected.net)}`;
          return;
        }

        closePosition(isAlpha ? 'Alpha quick exit at hold limit' : 'Hold window reached -> CLOSE by prediction', {
          recordInSession: state.auto.running
        });

        if (!state.auto.running || Date.now() >= state.auto.endTs) {
          return;
        }

        const resolved = callbacks.resolveActiveSeries();
        const refreshedSeries = resolved?.series || series;
        const nextPred = await callbacks.requestPrediction(refreshedSeries, true);
        if (!nextPred) return;

        const latest = Array.isArray(refreshedSeries) && refreshedSeries.length > 0
          ? refreshedSeries[refreshedSeries.length - 1]
          : null;
        if (!latest) return;

        const decision = decideTradeByStrategy(nextPred, latest);
        if (decision.action === 'HOLD' || !shouldEnterAuto(decision)) {
          return;
        }

        const opened = openPosition(
          nextPred,
          resolved?.key || callbacks.getActiveSeriesKey(),
          'auto',
          decision.action,
          decision.reason
        );
        if (opened) {
          elements.simSummary.textContent = `Re-entry ${decision.action} after close | ${resolved?.key || callbacks.getActiveSeriesKey()} | ${decision.reason}`;
        }
      } finally {
        state.position.pendingDecision = false;
      }
    }

    function startAutoTradingSession() {
      const cfg = readStrategyConfig();
      if (!Number.isFinite(cfg.rangeSec) || cfg.rangeSec < 10) {
        elements.simSummary.textContent = 'Auto range must be at least 10 seconds.';
        return;
      }

      state.auto.running = true;
      state.auto.endTs = Date.now() + cfg.rangeSec * 1000;
      state.auto.totalPnl = 0;
      state.auto.trades = 0;
      state.auto.wins = 0;
      state.auto.losses = 0;

      initializeAccountIfNeeded();
      renderAccountStats();
      state.auto.sessionStartEquity = state.account.equity;

      renderAutoSessionStats();
      refreshAutoBadge();
      const profile = configProfiles[cfg.profile] || configProfiles.market_maker;
      elements.simSummary.textContent = `Auto trading started for ${cfg.rangeSec}s | Config: ${profile.label} | Model: ${modelOptions[cfg.modelType] || cfg.modelType} | Hold: ${cfg.holdMs}ms`;
      if (typeof callbacks.onAutoTradingChange === 'function') {
        callbacks.onAutoTradingChange(true);
      }
    }

    function stopAutoTradingSession(reason = 'Auto trading stopped') {
      if (!state.auto.running) return;
      if (state.position.open) {
        closePosition('Auto session ended - close executed', { recordInSession: true });
      }
      updateSessionProfitFromEquity();
      state.auto.running = false;
      refreshAutoBadge();
      const winRate = state.auto.trades > 0
        ? ((state.auto.wins / state.auto.trades) * 100).toFixed(1)
        : '0.0';
      elements.simSummary.textContent = `${reason}. Trades: ${state.auto.trades} | Total Profit: ${formatUsdSigned(state.auto.totalPnl)} | Win rate: ${winRate}%`;
      if (typeof callbacks.onAutoTradingChange === 'function') {
        callbacks.onAutoTradingChange(false);
      }
    }

    async function update(series, activeSeriesKey) {
      if (!Array.isArray(series) || series.length === 0) {
        elements.simSummary.textContent = 'No active series data yet. Connect stream and wait for ticks.';
        return;
      }

      const prediction = callbacks.getLastPrediction();
      const predictionError = callbacks.getPredictionError();

      if (!prediction) {
        const latestPoint = series[series.length - 1];
        const latestPrice = Number(latestPoint?.price);
        elements.simSignal.textContent = 'WAIT';
        elements.simPredPrice.textContent = Number.isFinite(latestPrice)
          ? `$${latestPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
          : '-';
        if (elements.simPredRet) {
          elements.simPredRet.textContent = formatReturnBps(0);
          setPnlColor(elements.simPredRet, 0);
        }
        elements.simExpPnl.textContent = formatUsdSigned(0);
        setPnlColor(elements.simExpPnl, 0);
        elements.simLivePnl.textContent = formatUsdSigned(0);
        setPnlColor(elements.simLivePnl, 0);
        elements.simLiveEquity.textContent = formatUsd(state.account.equity);
        elements.simPosition.textContent = state.position.open ? elements.simPosition.textContent : 'FLAT';
        if (predictionError) {
          elements.simSummary.textContent = `Prediction service unavailable: ${predictionError}.`;
        } else {
          elements.simSummary.textContent = 'Collecting enough points for inference...';
        }
        renderAccountStats(null, Number.isFinite(latestPrice) ? latestPrice : null);
        return;
      }

      const latest = series[series.length - 1];
      const decision = decideTradeByStrategy(prediction, latest);
      const displayAction = state.auto.running && !state.position.open
        ? deriveAutoEntryDecision(decision, prediction, latest).action
        : decision.action;
      const capitalPreview = parseCapitalInput() || 5000;
      let expectedPreview = 0;
      const lastPrice = predictionLastPrice(prediction);
      const predPrice = predictionPrice(prediction);
      const predRet = predictionSignedReturn(prediction);
      if (state.position.open) {
        expectedPreview = computeExpectedPnlFromExecutableReturn(
          state.position.side,
          state.position.capital,
          predRet
        ).net;
      } else if (displayAction !== 'HOLD') {
        expectedPreview = computeExpectedPnlFromExecutableReturn(displayAction, capitalPreview, predRet).net;
      }

      elements.simSignal.textContent = displayAction;
      elements.simPredPrice.textContent = Number.isFinite(predPrice)
        ? `$${predPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
        : '-';
      if (elements.simPredRet) {
        elements.simPredRet.textContent = formatReturnBps(predRet);
        setPnlColor(elements.simPredRet, predRet);
      }
      elements.simExpPnl.textContent = formatUsdSigned(expectedPreview);
      setPnlColor(elements.simExpPnl, expectedPreview);

      if (!state.position.open) {
        elements.simLivePnl.textContent = formatUsdSigned(0);
        setPnlColor(elements.simLivePnl, 0);
        elements.simLiveEquity.textContent = formatUsd(state.account.equity);
        elements.simPosition.textContent = 'FLAT';

        if (!state.auto.running) {
          elements.simSummary.textContent = `Model ${prediction.modelName || 'PredictionService'} on ${activeSeriesKey || '-'}: ${decision.action} | ${decision.reason}`;
        }

        renderAccountStats(latest, lastPrice);
        updateSessionProfitFromEquity(latest, lastPrice);

        if (state.auto.running) {
          const now = Date.now();
          if (now >= state.auto.endTs) {
            stopAutoTradingSession('Auto trading time range ended');
          } else {
            const autoDecision = deriveAutoEntryDecision(decision, prediction, latest);
            if (shouldEnterAuto(autoDecision)) {
              openPosition(prediction, activeSeriesKey, 'auto', autoDecision.action, autoDecision.reason);
            } else {
              const secondsLeft = Math.max(0, Math.ceil((state.auto.endTs - now) / 1000));
              elements.simSummary.textContent = `${autoDecision.reason} | Session left: ${secondsLeft}s`;
            }
          }
        }
        return;
      }

      const activeSeries = callbacks.getSeriesByKey(state.position.seriesKey);
      const lastPoint = Array.isArray(activeSeries) && activeSeries.length > 0
        ? activeSeries[activeSeries.length - 1]
        : null;
      if (!lastPoint) return;

      const liveExit = estimateExecutionPrice(state.position.side, 'exit', lastPoint, lastPoint.price) || lastPoint.price;
      const livePnl = computeNetPnl(
        state.position.side,
        state.position.qty,
        state.position.entryExecPrice || state.position.entryPrice,
        liveExit
      ).net;
      const liveEquity = state.position.capital + livePnl;
      const elapsedMs = Date.now() - state.position.openedAt;
      const leftMs = Math.max(0, state.position.holdMs - elapsedMs);

      elements.simLivePnl.textContent = formatUsdSigned(livePnl);
      elements.simLiveEquity.textContent = formatUsd(liveEquity);
      elements.simPosition.textContent = `${state.position.side} ${state.position.qty.toFixed(4)} (${leftMs}ms left)`;
      setPnlColor(elements.simLivePnl, livePnl);
      setPnlColor(elements.simLiveEquity, livePnl);
      renderAccountStats(lastPoint, lastPoint.price);
      updateSessionProfitFromEquity(lastPoint, lastPoint.price);

      if (leftMs <= 0) {
        elements.simPosition.textContent = `${state.position.side} ${state.position.qty.toFixed(4)} (decision...)`;
        evaluateCloseDecision(activeSeries);
      }

      if (state.position.open && state.position.strategy === 'short_term_alpha') {
        const flip =
          (state.position.side === 'LONG' && decision.action === 'SHORT') ||
          (state.position.side === 'SHORT' && decision.action === 'LONG');
        if (flip) {
          closePosition(`Alpha protective exit on signal flip (${decision.action})`, {
            recordInSession: state.auto.running
          });
          return;
        }
      }

      if (state.auto.running && Date.now() >= state.auto.endTs) {
        stopAutoTradingSession('Auto trading time range ended');
      }
    }

    function onStreamStopped() {
      if (state.auto.running) {
        stopAutoTradingSession('Auto trading stopped because stream stopped');
      } else {
        closePosition('Position closed because stream stopped');
      }
    }

    function bootstrap() {
      formatCapitalInput();
      formatAccountInput();
      initializeAccountIfNeeded();
      renderAutoSessionStats();
      refreshStrategyUi();
      refreshAutoBadge();
    }

    return {
      bootstrap,
      update,
      refreshStrategyUi,
      refreshAutoBadge,
      applyConfigProfile,
      formatCapitalInput,
      formatAccountInput,
      resetAccount,
      startAutoTradingSession,
      stopAutoTradingSession,
      onStreamStopped,
      isPositionOpen: () => state.position.open
    };
  }

  global.PulseSimulator = { create };
})(window);
