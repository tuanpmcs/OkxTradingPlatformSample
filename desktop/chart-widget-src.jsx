import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AdvancedRealTimeChart } from 'react-ts-tradingview-widgets';

function normalizeSymbol(input) {
  const value = String(input || 'BTC-USDT').trim().toUpperCase();
  return value.replace('-', '');
}

function App() {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const tvSymbol = useMemo(() => `OKX:${symbol}`, [symbol]);

  useEffect(() => {
    const onSymbolChange = (event) => {
      setSymbol(normalizeSymbol(event?.detail?.symbol));
    };
    window.addEventListener('stream:symbol-change', onSymbolChange);
    return () => window.removeEventListener('stream:symbol-change', onSymbolChange);
  }, []);

  return (
    <AdvancedRealTimeChart
      symbol={tvSymbol}
      interval="1"
      theme="dark"
      autosize
      hide_top_toolbar={false}
      hide_side_toolbar={false}
      allow_symbol_change
      withdateranges
      container_id="tradingview_chart_container"
    />
  );
}

const mount = document.getElementById('tv-chart-root');
if (mount) {
  const root = createRoot(mount);
  root.render(<App />);
}
