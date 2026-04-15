// ═══════════════════════ SUPABASE POLLING ═══════════════════════
async function pollFast() {
  // Latest signal
  const sig = await sq('signal_log', `${tagFilter()}order=ts.desc&limit=1`);
  if (sig.length) {
    const s = sig[0];
    
    // Store globally for drawVolRadar
    latestSignal = s;
    
    // Chainlink price
    const prevCl = clPrice;
    clPrice = s.chainlink_price || 0;
    const clEl = $('clPrice');
    clEl.textContent = '$' + clPrice.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    flashEl(clEl, clPrice, prevCl);

    // Edge + Prob KPIs
    const prevEdge = $('kEdge').textContent;
    $('kEdge').textContent = fmtPct(s.terminal_edge);
    flashEl($('kEdge'), s.terminal_edge, parseFloat(prevEdge));
    $('kProb').textContent = 'prob ' + fmtPct(s.terminal_probability);

    // Live signal card updates
    const dirEl = document.getElementById('liveDirection');
    if (dirEl && s.entry_side) {
      dirEl.textContent = s.entry_side === 'up' ? '▲  UP' : '▼  DOWN';
      dirEl.style.color = s.entry_side === 'up' ? 'var(--green)' : 'var(--red)';
      dirEl.style.borderColor = s.entry_side === 'up' ? 'oklch(0.696 0.17 162 / 40%)' : 'oklch(0.704 0.191 22.216 / 40%)';
      dirEl.style.background = s.entry_side === 'up' ? 'oklch(0.696 0.17 162 / 10%)' : 'oklch(0.704 0.191 22.216 / 10%)';
    }
    const bar = document.getElementById('elapsedBar');
    if (bar && s.elapsed_seconds != null) {
      const pct = Math.min(100, (s.elapsed_seconds / 300) * 100);
      bar.style.width = pct + '%';
      bar.style.background = pct < 50 ? 'var(--green)' : pct < 80 ? 'var(--amber)' : 'var(--red)';
    }
    const mq = document.getElementById('currentMarketQ');
    if (mq && s.market_question) mq.textContent = s.market_question.length > 45 ? s.market_question.slice(0,45)+'…' : s.market_question;
    const dot = document.getElementById('sigFreshDot');
    if (dot) dot.style.opacity = (Date.now() - (window._signalArrivalTime||0) < 5000) ? '1' : '0.2';
    const reqEl = document.getElementById('kEdgeRequired');
    if (reqEl) reqEl.textContent = s.required_edge != null ? fmtPct(s.required_edge) : '3.0%'; // BUG FIX 5: column doesn't exist yet, show Phase 0 default
    const deltaEl = document.getElementById('kDelta');
    if (deltaEl && s.strike_delta != null) deltaEl.textContent = (s.strike_delta >= 0 ? '+' : '') + s.strike_delta.toFixed(2);
    const depthEl = document.getElementById('kDepth');
    if (depthEl && s.depth_at_ask != null) depthEl.textContent = s.depth_at_ask.toFixed(0);
    const clAgeEl2 = document.getElementById('kClAge');
    if (clAgeEl2 && s.chainlink_age_seconds != null) {
      clAgeEl2.textContent = s.chainlink_age_seconds.toFixed(0) + 's';
      clAgeEl2.style.color = s.chainlink_age_seconds > 30 ? 'var(--amber)' : 'var(--fg)';
    }
    // CS edge live value
    if (s.complete_set_edge != null) {
      const csEl = document.getElementById('csEdgeLive');
      if (csEl) {
        csEl.textContent = (s.complete_set_edge >= 0 ? '+' : '') + (s.complete_set_edge * 100).toFixed(2) + '¢';
        csEl.style.color = s.complete_set_edge >= 0.01 ? 'var(--green)' : 'var(--muted-fg)';
      }
    }

    // Mode
    if (s.mode) {
      const b = $('modeBadge');
      b.textContent = s.mode.toUpperCase();
      b.className = 'badge ' + (s.mode === 'live' ? 'badge-live' : 'badge-dry');
    }

    // Update YES/NO prices from signal
    updateYesNo(s.yes_price, s.no_price, s.entry_side, s.spread);

    // Update strike price (price to beat)
    if (s.btc_price != null && s.strike_delta != null) {
      window._strikePrice = s.btc_price - s.strike_delta;
    }

    // BUG-2 fix: detect new signal arrival for smooth timer
    const sigId = s.id || s.ts;
    if (sigId !== window._lastSignalId) {
      window._lastSignalId = sigId;
      window._signalArrivalTime = Date.now();
    }

    // FIX-3: Chainlink age subscript
    const clAgeSeconds = s.chainlink_age_seconds;
    const clAgeEl = $('clAge');
    if (clAgeEl && clAgeSeconds != null) {
      clAgeEl.textContent = clAgeSeconds < 10 ? `·${clAgeSeconds.toFixed(0)}s` : `·${clAgeSeconds.toFixed(0)}s ⚠️`;
      clAgeEl.style.color = clAgeSeconds > 30 ? 'var(--red)' : 'var(--text-3)';
    }
    // FIX-3: Signal data age
    const sigAge = s.ts ? ((Date.now() - new Date(s.ts).getTime()) / 1000).toFixed(0) : '?';
    const sigAgeEl = $('sigAge');
    if (sigAgeEl) sigAgeEl.textContent = `signal ${sigAge}s ago`;

    // FIX-5: Live blocking conditions + AESTHETIC-3 blocking count
    const ALL_CONDITIONS = [
      'terminal_edge','delta_magnitude','edge','spread','depth',
      'clob_consensus','has_position','cooldown','daily_loss','balance',
      'position_limit','price_feed','chainlink_stale','time_of_day','entry_price','direction'
    ];
    const blocking = s.blocking_conditions
      ? s.blocking_conditions.split(',').map(b => b.trim()).filter(Boolean)
      : [];
    // AESTHETIC-3: update blocking count
    const bcEl = document.getElementById('blockingCount');
    if (bcEl) bcEl.textContent = blocking.length > 0 ? blocking.length + ' blocking' : '';
    const lb = $('blockerList');
    if (lb) {
      lb.innerHTML = ALL_CONDITIONS.map(c => {
        const isBlocking = blocking.includes(c);
        return `<div class="blocker-pill ${isBlocking ? 'block' : 'pass'}">
          <span class="bp-icon">${isBlocking ? '✗' : '✓'}</span>${c}
        </div>`;
      }).join('');
    }

    // FIX-6: Bot state badge
    const stateMap = {
      scanning:      {label:'● scanning',      bg:'var(--green-bg)',  color:'var(--green)',  border:'#A9EFC5'},
      entry_pending: {label:'⏳ entry pending', bg:'var(--amber-bg)', color:'var(--amber)',  border:'#FEDF89'},
      in_trade:      {label:'🔵 in trade',      bg:'#EFF6FF',         color:'#3B82F6',        border:'#BFDBFE'},
      trade_fired:   {label:'🟢 TRADE FIRED',   bg:'var(--green-bg)', color:'var(--green)',  border:'#A9EFC5'},
    };
    const botState = s.trade_fired ? 'trade_fired' : (s.in_trade ? 'in_trade' : 'scanning');
    const bs = stateMap[botState] || stateMap.scanning;
    const botEl = $('botStatus');
    botEl.textContent = bs.label;
    Object.assign(botEl.style, {background:bs.bg, color:bs.color, borderColor:bs.border});

    // Update radar stats div with key metrics
    const radarStats = $('radarStats');
    if (radarStats) {
      const realVol = (s.sigma_realized || 0) * 100;
      const implVol = (s.implied_vol || 0) * 100;
      const ivRvRatio = realVol > 0 ? implVol / realVol : 0;
      const termEdge = (s.terminal_edge || 0) * 100;
      const condsMet = s.conditions_met || 0;
      const strikeDelta = s.strike_delta || 0;
      
      // Status indicator
      let statusText = '';
      if (s.all_conditions_met && termEdge >= 3) {
        statusText = '🟢 READY TO FIRE';
      } else if (termEdge < 0) {
        statusText = '🔴 Edge negative';
      } else if (condsMet < 15) {
        statusText = '🟡 ' + (15 - condsMet) + ' blocking';
      } else {
        statusText = '🟡 Waiting edge';
      }
      
      radarStats.innerHTML = `
        <div><strong>Realized Vol:</strong> ${realVol.toFixed(1)}%</div>
        <div><strong>Implied Vol:</strong> ${implVol > 0 ? implVol.toFixed(1) + '%' : 'N/A'}</div>
        <div><strong>IV/RV Ratio:</strong> <span style="color:${ivRvRatio > 1.2 ? '#12B76A' : '#64748B'}">${ivRvRatio.toFixed(2)}</span></div>
        <div><strong>Terminal Edge:</strong> ${termEdge.toFixed(1)}%</div>
        <div><strong>Strike Delta:</strong> $${strikeDelta.toFixed(2)}</div>
        <div><strong>Conditions:</strong> ${condsMet}/15</div>
        <div style="margin-top:4px; padding-top:4px; border-top:1px solid #E2E8F0;"><strong>Status:</strong> ${statusText}</div>
      `;
    }
  }

  // FIX-4: track poll time for relative counter
  lastPollTime = Date.now();
  $('lastUpdate').textContent = 'just now';
  
  // ── Complete-set edge (live, from latest signal row) ──
    if (s.complete_set_edge != null) {
      const cse = s.complete_set_edge;
      const csEl = $('csEdgeVal');
      const csBadge = $('csEdgeBadge');
      if (csEl) {
        const prevCse = parseFloat(csEl.textContent) || 0;
        csEl.textContent = (cse * 100).toFixed(2) + '%';
        csEl.style.color = cse >= 0.01 ? 'var(--green)' : cse > 0 ? 'var(--amber)' : 'var(--text-3)';
        flashEl(csEl, cse, prevCse);
      }
      if (csBadge) {
        if (cse >= 0.01) { csBadge.textContent = 'EDGE'; csBadge.style.background = 'var(--green-bg)'; csBadge.style.color = 'var(--green)'; }
        else if (cse > 0) { csBadge.textContent = 'LOW'; csBadge.style.background = 'var(--amber-bg)'; csBadge.style.color = 'var(--amber)'; }
        else { csBadge.textContent = 'NONE'; csBadge.style.background = 'var(--border)'; csBadge.style.color = 'var(--text-2)'; }
      }
    }

  // Draw the vol radar
  drawVolRadar();
}

async function pollSlow() {
  // ── Balance (from rolling_stats) ──
  const rs = await sq('rolling_stats', 'id=eq.singleton&select=data');
  if (rs.length && rs[0].data) {
    const bal = rs[0].data.simulated_balance;
    if (bal != null) {
      $('kBalance').textContent = '$' + Number(bal).toFixed(2);
      const isDryBal = $('modeBadge') && $('modeBadge').textContent.includes('DRY');
      $('kBalance').className = 'val ' + (isDryBal ? '' : (bal >= 100 ? 'positive' : 'negative'));
    }
    // FIX-10: show balance age from rolling_stats updated_at
    const updatedAt = rs[0].data.updated_at;
    if (updatedAt) {
      const ageSeconds = Math.floor((Date.now() - new Date(updatedAt).getTime()) / 1000);
      const ageTxt = ageSeconds < 60 ? `${ageSeconds}s ago` : `${Math.floor(ageSeconds/60)}m ago`;
      const balSub = $('kBalance').parentElement.querySelector('.sub');
      if (balSub) balSub.textContent = `simulated USDC · ${ageTxt}`;
    }
  }

  // ── Trades (direct, small table) ──
  const trades = await sq('trade_log', `${tagFilter()}order=ts.desc&limit=20`);
  tradeData = [...trades].reverse();

  // ── Trade KPIs (from view — accurate) ──
  const tSum = await sq('dashboard_trade_summary', 'limit=1');
  if (tSum.length) {
    const t = tSum[0];
    const totalPnl = parseFloat(t.total_pnl);
    const prevPnl = $('kTotalPnl').textContent;
    $('kTotalPnl').textContent = fmtUsd(totalPnl);
    // AESTHETIC-1: mute P&L in dry-run
    const isDryRun = $('modeBadge') && $('modeBadge').textContent.includes('DRY');
    $('kTotalPnl').className = 'val ' + (isDryRun ? 'val-muted' : (totalPnl >= 0 ? 'positive' : 'negative'));
    let simTag = document.getElementById('simTag');
    if (isDryRun) {
      if (!simTag) { simTag = document.createElement('div'); simTag.id = 'simTag'; simTag.className = 'simulated-tag'; $('kTotalPnl').parentElement.appendChild(simTag); }
      simTag.textContent = '(simulated)'; simTag.style.display = '';
    } else if (simTag) { simTag.style.display = 'none'; }
    flashEl($('kTotalPnl'), totalPnl, parseFloat(prevPnl.replace(/[^-\d.]/g,'')));
    $('kTotalTrades').textContent = t.total_trades + ' trades';
    $('kWinRate').textContent = t.win_rate_pct + '%';
    $('kWinRate').className = 'val ' + (t.wins > t.losses ? 'positive' : t.wins < t.losses ? 'negative' : '');
    $('kWL').textContent = t.wins + ' wins \u00B7 ' + (t.wins + t.losses) + ' closed';
  }

  // ── Trade table ──
  const tbody = $('tradeBody');
  // FIX-8: expandable trade rows with LLM reason on click
  tbody.innerHTML = trades.slice(0, 8).map(t => {
    const side = t.side === 'up' ? '▲ UP' : '▼ DOWN';
    const sideColor = t.side === 'up' ? 'var(--green)' : 'var(--red)';
    const pnlClass = t.pnl >= 0 ? 'positive' : 'negative';
    const pill = t.outcome === 'win' ? '<span class="pill pill-win">WIN</span>'
      : t.outcome === 'loss' ? '<span class="pill pill-loss">LOSS</span>'
      : '<span class="pill" style="background:#F2F4F7;color:var(--text-2)">OPEN</span>';
    const q = t.market_question || '';
    const short = q.length > 30 ? q.slice(0,30)+'…' : q;
    return `<tr style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'table-row':'none'">
      <td>${fmtTimeFull(t.ts)}</td>
      <td title="${q}" style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${short}</td>
      <td style="color:${sideColor};font-weight:600">${side}</td>
      <td>${fmt(t.entry_price, 3)}</td>
      <td>$${fmt(t.size_usdc, 0)}</td>
      <td class="${pnlClass}" style="font-weight:600">${fmtUsd(t.pnl)}</td>
      <td>${(function(v){if(!v||v==='--')return '--';const vl=v.toUpperCase();if(vl==='GO')return '<span class="llm-go">GO</span>';if(vl==='SKIP')return '<span class="llm-skip">SKIP</span>';if(vl==='ABORT')return '<span class="llm-abort">ABORT</span>';return v;})(t.llm_verdict)}</td>
      <td>${(function(t){
        if (t.total_latency_ms != null) {
          const ms = Math.round(t.total_latency_ms);
          const color = ms < 400 ? 'var(--green)' : ms < 1000 ? 'var(--amber)' : 'var(--red)';
          return `<span style="font-size:10px;font-weight:600;color:${color}">${ms}ms</span>`;
        }
        return '<span style="color:var(--text-3)">--</span>';
      })(t)}</td>
      <td>${pill}</td>
    </tr>
    <tr style="display:none">
      <td colspan="9" style="padding:8px 12px;background:#FAFBFC;font-size:11px;color:var(--text-2);border-bottom:1px solid var(--border)">
        <strong>Provider:</strong> ${t.llm_provider||'--'} &nbsp;·&nbsp;
        <strong>Edge:</strong> ${t.terminal_edge != null ? (t.terminal_edge*100).toFixed(1)+'%' : '--'} &nbsp;·&nbsp;
        <strong>Duration:</strong> ${t.duration_seconds != null ? t.duration_seconds.toFixed(0)+'s' : '--'} &nbsp;·&nbsp;
        <strong>LLM:</strong> ${t.llm_response_ms != null ? Math.round(t.llm_response_ms)+'ms' : '--'} &nbsp;·&nbsp;
        <strong>Order:</strong> ${t.order_submit_ms != null ? Math.round(t.order_submit_ms)+'ms' : '--'}<br>
        <em style="color:var(--text-1);margin-top:4px;display:block">${t.llm_reason||'No reason recorded'}</em>
      </td>
    </tr>`;
  }).join('');

  drawEquityCurve();

  // ── Shadow summary (from view — aggregates all 2K+ rows server-side) ──
  const shArr = await sq('dashboard_shadow_summary', 'limit=1');
  if (shArr.length) {
    const sh = shArr[0];
    const shPnl = parseFloat(sh.total_pnl);
    $('shTotal').textContent = fmtK(sh.total);
    // AESTHETIC-4: zero state for shadow scoreboard
    const zeroMsg = document.getElementById('shadowZeroMsg');
    if (sh.settled === 0) {
      $('shSettled').textContent = '0';
      $('shWins').textContent = '--'; $('shLosses').textContent = '--';
      $('shPnl').textContent = '--'; $('shPnl').className = 'sv';
      if (!zeroMsg) {
        const msg = document.createElement('div'); msg.id = 'shadowZeroMsg';
        msg.style.cssText = 'grid-column:span 2;text-align:center;padding:12px;color:var(--text-3);font-size:12px;font-style:italic';
        msg.textContent = 'No settled trades yet';
        $('shPnl').closest('.shadow-grid').appendChild(msg);
      } else { zeroMsg.style.display = ''; }
    } else {
      if (zeroMsg) zeroMsg.style.display = 'none';
      $('shSettled').textContent = fmtK(sh.settled);
      $('shWins').textContent = sh.wins;
      $('shLosses').textContent = sh.losses;
      const prevShPnl = $('shPnl').textContent;
      $('shPnl').textContent = fmtUsd(shPnl);
      $('shPnl').className = 'sv ' + (shPnl >= 0 ? 'positive' : 'negative');
      flashEl($('shPnl'), shPnl, parseFloat(prevShPnl.replace(/[^-\d.]/g,'')));
    }

    $('kShadowPnl').textContent = fmtUsd(shPnl);
    $('kShadowPnl').className = 'val ' + (shPnl >= 0 ? 'positive' : 'negative');
    $('kShadowCount').textContent = sh.settled + ' settled';
    const shWR = sh.settled > 0 ? ((sh.wins / sh.settled) * 100).toFixed(1) : '0.0';
    $('kShadowWR').textContent = shWR + '%';
    $('kShadowWR').className = 'val ' + (sh.wins > sh.losses ? 'positive' : 'negative');
    $('kShadowWL').textContent = sh.settled > 0 ? sh.wins + ' wins \u00B7 ' + sh.settled + ' closed' : '--';
  }

  // Complete-set edge 24h frequency
  try {
    const csData = await sq('signal_log',
      `${tagFilter()}select=complete_set_edge&complete_set_edge=not.is.null&ts=gte.${new Date(Date.now()-86400000).toISOString()}&limit=5000`
    );
    if (csData && csData.length > 0) {
      const total = csData.length;
      const withEdge = csData.filter(r => r.complete_set_edge >= 0.01).length;
      const pct = (withEdge / total * 100).toFixed(1);
      const freqEl = document.getElementById('csFreqPct');
      if (freqEl) {
        freqEl.textContent = pct + '%';
        freqEl.style.color = parseFloat(pct) >= 10 ? 'var(--green)' : parseFloat(pct) >= 5 ? 'var(--amber)' : 'var(--red)';
      }
      const ctEl = document.getElementById('csFreqCount');
      if (ctEl) ctEl.textContent = withEdge + ' / ' + total + ' cycles';
    }
  } catch(e) {}

  // ── Blockers 24h (from signal_log — unbiased; replaces the old
  // shadow-based render that was stomping on live blocker pills) ──
  // Render into the dedicated `blocker24hList` card added to dashboard.html
  // so the live pass/block pill grid in `blockerList` (pollFast) is never
  // overwritten by this aggregate view.
  try {
    const [blockers24h, counts24hArr] = await Promise.all([
      sq('dashboard_signal_blockers_24h', 'order=cnt.desc&limit=10'),
      sq('dashboard_signal_counts_24h', 'limit=1'),
    ]);
    const counts24h = counts24hArr && counts24hArr[0] ? counts24hArr[0] : null;
    const lb24 = $('blocker24hList');
    if (lb24) {
      if (!blockers24h || blockers24h.length === 0) {
        lb24.innerHTML = '<div style="color:var(--muted-fg);padding:8px 0">no blocked signals in last 24h</div>';
      } else {
        const maxCnt24 = blockers24h[0].cnt || 1;
        lb24.innerHTML = blockers24h.map(d => {
          const pct = d.pct_of_blocked_signals != null ? parseFloat(d.pct_of_blocked_signals).toFixed(1) + '%' : '';
          return `<div class="blocker-row" style="display:grid;grid-template-columns:1fr 2fr auto auto;gap:8px;align-items:center">
            <span class="blocker-name" title="${d.name}" style="color:var(--text-2)">${d.name}</span>
            <div class="blocker-bar-bg" style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
              <div class="blocker-bar-fill" style="height:100%;width:${(d.cnt/maxCnt24)*100}%;background:var(--amber)"></div>
            </div>
            <span class="blocker-cnt" style="color:var(--text-1);min-width:32px;text-align:right">${d.cnt}</span>
            <span class="blocker-pct" style="color:var(--muted-fg);min-width:44px;text-align:right">${pct}</span>
          </div>`;
        }).join('');
      }
    }
    const hdr = $('blocker24hCount');
    if (hdr && counts24h) {
      const total = counts24h.total_signals || 0;
      const met   = counts24h.all_met || 0;
      const fired = counts24h.trades_fired || 0;
      const metPct = total ? ((met/total)*100).toFixed(1) : '0.0';
      hdr.textContent = `${total} signals · ${met} met (${metPct}%) · ${fired} fired`;
    }
  } catch (e) { /* view may not exist yet on first deploy */ }

  // FIX-9: Markets Scanned KPI (HEAD count — no row transfer)
  const scannedCount = await sqCount('signal_log', tagFilter());
  if ($('kScanned')) {
    $('kScanned').textContent = fmtK(scannedCount);
    $('kScannedSub').textContent = SESSION_TAG ? `session ${SESSION_TAG}` : 'this session';
  }

  // ── Hourly signals (from view — pre-aggregated) ──
  signalData = await sq('dashboard_signals_hourly', 'order=hour.asc');
  const totalSigs = signalData.reduce((a,d) => a + d.signals, 0);
  const totalFired = signalData.reduce((a,d) => a + d.fired, 0);
  $('kSignals').textContent = fmtK(totalSigs);
  $('kFired').textContent = totalFired + ' fired';
  drawSignalChart();

  // ── Complete-set edge 24h stats ──
  try {
    const since24h = new Date(Date.now() - 86400000).toISOString();
    const csRows = await sq('signal_log', `select=complete_set_edge&${tagFilter()}ts=gte.${since24h}&complete_set_edge=not.is.null&limit=5000`);
    if (csRows.length > 0) {
      const vals = csRows.map(r => r.complete_set_edge).filter(v => v != null);
      const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
      const pctAbove = (vals.filter(v => v >= 0.01).length / vals.length) * 100;
      const avgEl = $('csEdge24hAvg');
      const pctEl = $('csEdge24hPct');
      if (avgEl) avgEl.textContent = (avg * 100).toFixed(3) + '%';
      if (pctEl) pctEl.textContent = pctAbove.toFixed(1) + '%';
    }
  } catch(e) {}
}

// ═══════════════════════ HISTORICAL PRICE LOAD — Binance Klines ═══════════════════════
let currentRangeSeconds = 300;
const RANGE_LABELS = { 60: '1 min', 300: '5 min', 21600: '6h', 86400: '24h' };

// Map range → Binance kline interval + limit
function binanceKlineParams(rangeSec) {
  if (rangeSec <= 60)    return { interval: '1s', limit: 60 };     // 60 x 1s candles
  if (rangeSec <= 300)   return { interval: '1s', limit: 300 };    // 300 x 1s candles
  if (rangeSec <= 21600) return { interval: '1m', limit: 360 };    // 360 x 1m candles = 6h
  return                          { interval: '5m', limit: 288 };   // 288 x 5m candles = 24h
}

async function fetchBinanceKlines(rangeSec) {
  const { interval, limit } = binanceKlineParams(rangeSec);
  const startTime = Date.now() - rangeSec * 1000;
  try {
    const url = `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=${interval}&startTime=${startTime}&limit=${limit}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('Binance API ' + resp.status);
    const data = await resp.json();
    // Kline format: [openTime, open, high, low, close, volume, closeTime, ...]
    return data.map(k => ({
      t: k[0],              // open time ms
      p: parseFloat(k[4]),  // close price
      h: parseFloat(k[2]),  // high
      l: parseFloat(k[3]),  // low
    }));
  } catch (e) {
    console.warn('[Chart] Binance klines failed, falling back to signal_log:', e);
    return null;
  }
}

async function loadPriceHistory(rangeSeconds) {
  if (rangeSeconds === 'market') {
    _marketMode = true;
    currentRangeSeconds = 300;
  } else if (rangeSeconds != null) {
    _marketMode = false;
    currentRangeSeconds = rangeSeconds;
  }

  // Try Binance klines first (continuous data, no gaps)
  const klines = await fetchBinanceKlines(currentRangeSeconds);
  if (klines && klines.length > 0) {
    priceHistory = klines.map(k => ({ t: k.t, p: k.p }));
  } else {
    // Fallback: signal_log (sparse, has gaps)
    const since = new Date(Date.now() - currentRangeSeconds * 1000).toISOString();
    const rows = await sq('signal_log', `select=ts,btc_price&${tagFilter()}ts=gte.${since}&order=ts.asc&limit=5000`);
    const step = Math.max(1, Math.floor(rows.length / 500));
    priceHistory = rows.filter((_, i) => i % step === 0).map(r => ({ t: r.ts, p: r.btc_price }));
  }

  // Update chart title
  const titleEl = document.getElementById('btcChartTitle');
  if (titleEl) {
    const liveSpan = document.getElementById('chartLive');
    const label = _marketMode ? 'This Market' : (RANGE_LABELS[currentRangeSeconds] || currentRangeSeconds + 's');
    titleEl.textContent = 'BTC Price \u2014 ' + label;
    if (liveSpan) { titleEl.appendChild(document.createTextNode(' ')); titleEl.appendChild(liveSpan); }
  }
  drawPriceChart();
}


// BUG FIX 2: setRange function (was missing — onclick="setRange(...)" did nothing;
// querySelectorAll('.tr-btn') targeted wrong class). Button listeners wired in init.js.
function setRange(r) {
  ['btn5m','btn15m','btn1h'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.classList.remove('active');
  });
  const idMap = {'5m':'btn5m','15m':'btn15m','1h':'btn1h'};
  if (idMap[r]) document.getElementById(idMap[r]).classList.add('active');
  const secMap = {'5m':300,'15m':900,'1h':3600};
  loadPriceHistory(secMap[r] || 300);
}
