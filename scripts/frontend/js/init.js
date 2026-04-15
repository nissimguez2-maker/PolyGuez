// ═══════════════════════ INIT ═══════════════════════
(async function init() {
  connectBinance();
  connectBotWs();
  await initSessionTag();
  initRealtime();
  await Promise.all([loadPriceHistory(), pollFast(), pollSlow()]);
  setInterval(pollFast, POLL_FAST);
  setInterval(pollSlow, POLL_SLOW);

  // BUG FIX 2: wire chart button listeners here (after DOM ready)
  document.getElementById('btn5m').addEventListener('click',  () => setRange('5m'));
  document.getElementById('btn15m').addEventListener('click', () => setRange('15m'));
  document.getElementById('btn1h').addEventListener('click',  () => setRange('1h'));

  // 1-second tick: timer countdown + CL age + relative "last updated"
  setInterval(() => {
    // Relative last-updated label
    if (lastPollTime > 0) {
      const secs = Math.floor((Date.now() - lastPollTime) / 1000);
      $('lastUpdate').textContent = secs < 5 ? 'just now' : 'updated ' + secs + 's ago';
    }

    // BUG FIX 4: live market countdown (client-side tick between WS frames)
    if (window._timeToExpiry != null && window._timeToExpiry >= 0) {
      window._timeToExpiry = Math.max(0, window._timeToExpiry - 1);
      const t = Math.floor(window._timeToExpiry);
      const mm = String(Math.floor(t / 60)).padStart(2, '0');
      const ss = String(t % 60).padStart(2, '0');
      const timerEl = $('liveMarketTimer');
      if (timerEl) {
        timerEl.textContent = mm + ':' + ss;
        timerEl.style.color = t > 120 ? 'var(--fg)' : t > 30 ? 'var(--amber)' : 'var(--red)';
      }
      // Update progress bar
      const total = window._entryWindowTotal || 300;
      const elapsed = total - window._timeToExpiry;
      const pct = Math.min(100, Math.max(0, (elapsed / total) * 100));
      const fill = $('liveMarketBarFill');
      if (fill) {
        fill.style.width = pct + '%';
        fill.style.background = pct < 60 ? 'var(--green)' : pct < 90 ? 'var(--amber)' : 'var(--red)';
      }
    } else {
      const timerEl = $('liveMarketTimer');
      if (timerEl) { timerEl.textContent = '--:--'; timerEl.style.color = 'var(--muted-fg)'; }
    }

    // BUG FIX 3: live CL age (recalculate client-side, not from stale logged value)
    if (window._lastClPriceTime > 0) {
      const clAgeLive = Math.floor((Date.now() - window._lastClPriceTime) / 1000);
      const clAgeEl = document.getElementById('kClAge');
      if (clAgeEl) {
        clAgeEl.textContent = clAgeLive + 's';
        clAgeEl.style.color = clAgeLive > 30 ? 'var(--amber)' : 'var(--fg)';
      }
    }

    // Redraw chart on tick if signal arrived recently
    if (window._signalArrivalTime > 0) scheduleChartDraw();
  }, 1000);

  // Background kline refresh every 60s
  setInterval(() => loadPriceHistory(), 60000);

  window.addEventListener('resize', () => {
    scheduleChartDraw();
    drawSignalChart();
    drawEquityCurve();
  });
})();
