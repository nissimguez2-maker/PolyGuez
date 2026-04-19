
// ═══════════════════════ CONFIG ═══════════════════════
const SB_URL = 'https://rapmxqnxsobvxqtfnwqh.supabase.co/rest/v1';
const SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJhcG14cW54c29idnhxdGZud3FoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUxNTAwMDgsImV4cCI6MjA5MDcyNjAwOH0.-U8g_V89_8ef0XopkDmlJhsKjGH_256uK_3muuFN1J0';
const SB_HDR = { apikey: SB_KEY, Authorization: 'Bearer ' + SB_KEY };
const BINANCE_WS = 'wss://stream.binance.com:9443/ws/btcusdt@trade';
const POLL_FAST = 5000;   // signal_log poll
const POLL_SLOW = 15000;  // trades + shadows poll

// ═══════════════════════ STATE ═══════════════════════
let btcPrice = 0, prevBtcPrice = 0;
let clPrice = 0;
let priceHistory = [];  // {t, p} for chart — last 24h from signal_log + live
let livePrices = [];    // recent Binance ticks for chart overlay
let SESSION_TAG = null; // FIX-1: dynamic session tag
let elapsedAtPoll = 0, elapsedPollTime = 0; // FIX-2: live market timer
window._signalArrivalTime = 0;
window._lastSignalId = null;
// rAF chart scheduler — coalesces multiple updates into one paint
let _chartDirty = false;
window._lastTickMs = 0;
window._botElapsed = 0;
let clPrices = []; // Chainlink price history from bot WS {t, p}
window._strikePrice = 0; // price to beat = btc_price - strike_delta
let _marketMode = false; // fixed 0-5min window mode
window._yesPrice = 0;
window._noPrice = 0;
window._entrySide = '';
window._prevYes = 0;
window._prevNo = 0;
function updateYesNo(yes, no, side, spread) {
  if (yes != null && yes > 0) {
    window._prevYes = window._yesPrice;
    window._yesPrice = yes;
    const el = $('ynYesVal');
    el.textContent = (yes * 100).toFixed(1) + '¢';
    if (window._prevYes && Math.abs(yes - window._prevYes) > 0.001) {
      el.parentElement.classList.remove('yn-flash');
      void el.parentElement.offsetWidth;
      el.parentElement.classList.add('yn-flash');
    }
  }
  if (no != null && no > 0) {
    window._prevNo = window._noPrice;
    window._noPrice = no;
    const el = $('ynNoVal');
    el.textContent = (no * 100).toFixed(1) + '¢';
    if (window._prevNo && Math.abs(no - window._prevNo) > 0.001) {
      el.parentElement.classList.remove('yn-flash');
      void el.parentElement.offsetWidth;
      el.parentElement.classList.add('yn-flash');
    }
  }
  if (spread != null) {
    $('ynSpread').textContent = 'spread ' + (spread * 100).toFixed(1) + '¢';
  }
  if (side) {
    const el = $('ynSide');
    window._entrySide = side;
    el.textContent = side === 'up' ? '▲ UP' : '▼ DOWN';
    el.className = 'yn-side ' + (side === 'up' ? 'yn-side-up' : 'yn-side-down');
  }
}

function scheduleChartDraw() {
  if (!_chartDirty) {
    _chartDirty = true;
    requestAnimationFrame(() => { _chartDirty = false; drawPriceChart(); });
  }
}
let lastPollTime = 0; // FIX-4: relative last-updated

// ═══════════════════════ HELPERS ═══════════════════════
// roundRect polyfill for older browsers
if (!CanvasRenderingContext2D.prototype.roundRect) {
  CanvasRenderingContext2D.prototype.roundRect = function(x, y, w, h, r) {
    if (typeof r === 'number') r = [r, r, r, r];
    this.moveTo(x + r[0], y);
    this.arcTo(x + w, y, x + w, y + h, r[1]);
    this.arcTo(x + w, y + h, x, y + h, r[2]);
    this.arcTo(x, y + h, x, y, r[3]);
    this.arcTo(x, y, x + w, y, r[0]);
  };
}
const $ = id => document.getElementById(id);
const fmt = (n, d=2) => n == null ? '--' : Number(n).toFixed(d);
const fmtUsd = n => n == null ? '--' : (n < 0 ? '-$' : '+$') + Math.abs(n).toFixed(2);
const fmtPct = n => n == null ? '--' : (n*100).toFixed(1) + '%';
const fmtK = n => n == null ? '--' : n >= 1000 ? (n/1000).toFixed(1)+'K' : String(n);
const fmtTime = ts => { const d = new Date(ts); return d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false}); };
const fmtTimeFull = ts => { const d = new Date(ts); return d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}); };

function flashEl(el, newVal, oldVal) {
  if (!el || newVal === oldVal) return;
  el.classList.remove('flash-green','flash-red');
  void el.offsetWidth;
  el.classList.add(typeof newVal === 'number' && newVal >= (typeof oldVal === 'number' ? oldVal : 0) ? 'flash-green' : 'flash-red');
}

async function sq(table, params='') {
  try {
    const r = await fetch(`${SB_URL}/${table}?${params}`, { headers: SB_HDR });
    return r.ok ? r.json() : [];
  } catch(e) { return []; }
}

async function sqCount(table, filterPrefix='') {
  try {
    const r = await fetch(`${SB_URL}/${table}?${filterPrefix}select=count`, {
      method: 'HEAD',
      headers: { ...SB_HDR, Prefer: 'count=exact' },
    });
    const range = r.headers.get('content-range'); // "0-0/12345"
    return range ? parseInt(range.split('/')[1], 10) || 0 : 0;
  } catch(e) { return 0; }
}

// ═══════════════════════ SESSION TAG (FIX-1) ═══════════════════════
// Read from the session_tag_current singleton (seeded with 'V6') so the
// dashboard stays in sync with dashboard views (which also filter on
// session_tag = (SELECT tag FROM session_tag_current)). Fall back to the
// latest signal_log row, then hardcoded 'V6', if the singleton is missing.
async function initSessionTag() {
  let tag = null;
  const singleton = await sq('session_tag_current', 'select=tag&id=eq.true&limit=1');
  if (singleton.length && singleton[0].tag) {
    tag = singleton[0].tag;
  } else {
    const latest = await sq('signal_log', 'select=session_tag&order=ts.desc&limit=1');
    tag = latest.length ? latest[0].session_tag : 'V6';
  }
  SESSION_TAG = tag;
  // v5.0: dashboard.html now ships an empty `#sessionTagEl` placeholder in
  // the topbar; fill it in place instead of creating floating spans. Still
  // supports old shells by falling back to the previous prepend.
  const slot = document.getElementById('sessionTagEl');
  if (slot) {
    slot.textContent = SESSION_TAG;
  } else {
    const tagEl = document.createElement('span');
    tagEl.id = 'sessionTag';
    tagEl.className = 'section-tag';
    tagEl.textContent = SESSION_TAG;
    const topRight = document.querySelector('.topbar-right');
    if (topRight) topRight.prepend(tagEl);
  }
}
function tagFilter() { return SESSION_TAG ? `session_tag=eq.${SESSION_TAG}&` : ''; }

// ═══════════════════════ SUPABASE REALTIME (FIX-3) ═══════════════════════
let _realtimeSignalCount = 0;
function initRealtime() {
  try {
    const sbClient = window.supabase.createClient(
      'https://rapmxqnxsobvxqtfnwqh.supabase.co', SB_KEY
    );
    sbClient
      .channel('signal_log_live')
      .on('postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'signal_log' },
        (payload) => {
          const row = payload.new;
          // Update signal age instantly
          const sigAgeEl = $('sigAge');
          if (sigAgeEl) sigAgeEl.textContent = 'signal 0s ago';
          // Increment scanned counter
          _realtimeSignalCount++;
          const ksc = $('kScanned');
          if (ksc && ksc.textContent !== '--') {
            const prev = parseInt(ksc.textContent.replace(/[^0-9]/g,''), 10) || 0;
            ksc.textContent = fmtK(prev + 1);
          }
          // Update YES/NO prices instantly from realtime
          if (row.yes_price || row.no_price) {
            updateYesNo(row.yes_price, row.no_price, row.entry_side, row.spread);
          }
          // Update blocking conditions in real time
          if (row.blocking_conditions != null) {
            const ALL_CONDITIONS = [
              'terminal_edge','delta_magnitude','edge','spread','depth',
              'clob_consensus','has_position','cooldown','daily_loss','balance',
              'position_limit','price_feed','chainlink_stale','time_of_day','entry_price','direction'
            ];
            const blocking = row.blocking_conditions
              ? row.blocking_conditions.split(',').map(b => b.trim()).filter(Boolean)
              : [];
            const lb = $('blockerList');
            if (lb) {
              lb.innerHTML = ALL_CONDITIONS.map(c => {
                const isBlocking = blocking.includes(c);
                return `<div class="blocker-pill ${isBlocking ? 'block' : 'pass'}">
                  <span class="bp-icon">${isBlocking ? '✗' : '✓'}</span>${c}
                </div>`;
              }).join('');
            }
          }
        }
      )
      .subscribe();
    console.log('[Realtime] Subscribed to signal_log');
  } catch(e) {
    console.warn('[Realtime] Failed to init:', e);
  }
}

// ═══════════════════════ BINANCE WEBSOCKET ═══════════════════════
let ws, wsRetry = 0;
function connectBinance() {
  ws = new WebSocket(BINANCE_WS);
  ws.onopen = () => { $('wsDot').className = 'conn-dot on'; wsRetry = 0; };
  ws.onclose = () => {
    $('wsDot').className = 'conn-dot off';
    setTimeout(connectBinance, Math.min(1000 * 2**wsRetry++, 30000));
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    prevBtcPrice = btcPrice;
    btcPrice = parseFloat(d.p);
    const el = $('btcPrice');
    el.textContent = '$' + btcPrice.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    flashEl(el, btcPrice, prevBtcPrice);

    // Update delta
    if (clPrice > 0) {
      const delta = btcPrice - clPrice;
      const box = $('deltaBox');
      box.textContent = 'Δ ' + (delta >= 0 ? '+' : '') + delta.toFixed(2);
      if (Math.abs(delta) < 20) { box.style.background = 'var(--green-bg)'; box.style.color = 'var(--green)'; }
      else if (Math.abs(delta) < 100) { box.style.background = 'var(--amber-bg)'; box.style.color = 'var(--amber)'; }
      else { box.style.background = 'var(--red-bg)'; box.style.color = 'var(--red)'; }
    }

    // Buffer for chart (throttled)
    const now = Date.now();
    if (!connectBinance._lastChart || now - connectBinance._lastChart > 200) {
      connectBinance._lastChart = now;
      window._lastTickMs = now;
      livePrices.push({ t: now, p: btcPrice });
      if (livePrices.length > 3600) livePrices.shift();
      scheduleChartDraw();
    }
  };
}


// ═══════════════════════ BOT WS — sub-100ms prices ═══════════════════════
let botWs, botWsRetry = 0;
function connectBotWs() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const params = new URLSearchParams(location.search);
  const secret = params.get('secret') || '';
  const url = `${proto}//${location.host}/ws?secret=${secret}`;
  try {
    botWs = new WebSocket(url);
  } catch(e) { return; }

  botWs.onopen = () => { botWsRetry = 0; };
  botWs.onclose = () => {
    setTimeout(connectBotWs, Math.min(1000 * 2 ** botWsRetry++, 15000));
  };
  botWs.onerror = () => { try { botWs.close(); } catch(e) {} };
  botWs.onmessage = (e) => {
    try {
      const snap = JSON.parse(e.data);
      if (snap.error) return;

      // ── Chainlink price buffer (100ms) — THE SETTLEMENT LINE ──
      if (snap.chainlink_price > 0) {
        const now = Date.now();
        clPrices.push({ t: now, p: snap.chainlink_price });
        if (clPrices.length > 3600) clPrices.shift();
        // Also update topbar instantly
        clPrice = snap.chainlink_price;
        window._lastClPriceTime = Date.now(); // BUG FIX 3: track CL price time for live age calc
        const clEl = $('clPrice');
        if (clEl) clEl.textContent = '$' + clPrice.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
        // Update delta
        if (btcPrice > 0) {
          const delta = btcPrice - clPrice;
          const box = $('deltaBox');
          if (box) {
            box.textContent = '\u0394 ' + (delta >= 0 ? '+' : '') + delta.toFixed(2);
            if (Math.abs(delta) < 20) { box.style.background = 'var(--green-bg)'; box.style.color = 'var(--green)'; }
            else if (Math.abs(delta) < 100) { box.style.background = 'var(--amber-bg)'; box.style.color = 'var(--amber)'; }
            else { box.style.background = 'var(--red-bg)'; box.style.color = 'var(--red)'; }
          }
        }
        scheduleChartDraw();
      }

      // ── YES/NO prices at 100ms ──
      if (snap.yes_price > 0 || snap.no_price > 0) {
        const side = snap.signal ? snap.signal.entry_side : window._entrySide;
        const spread = snap.clob_spread != null ? snap.clob_spread : null;
        updateYesNo(snap.yes_price, snap.no_price, side, spread);
      }

      // ── Price to beat (strike) — from bot's _price_to_beat ──
      if (snap.price_to_beat > 0) {
        window._strikePrice = snap.price_to_beat;
      }

      // ── Market timer from entry_window_elapsed (authoritative) ──
      if (snap.entry_window_elapsed != null && snap.entry_window_elapsed > 0) {
        // Override the signal-arrival-based timer with the bot's real elapsed
        window._botElapsed = snap.entry_window_elapsed;
      }

      // ── Mode badge ──
      if (snap.mode) {
        const b = $('modeBadge');
        if (b) {
          b.textContent = snap.mode.toUpperCase();
          b.className = 'badge ' + (snap.mode === 'live' ? 'badge-live' : 'badge-dry');
        }
      }

      // ── Kill state ──
      if (snap.killed) {
        const b = $('botStatus');
        if (b) { b.textContent = '🔴 KILLED'; b.style.background = 'var(--red-bg)'; b.style.color = 'var(--red)'; }
      }

      // ── Daily P&L from snapshot (100ms) ──
      if (snap.daily_pnl != null) {
        const dpEl = $('kDailyPnl');
        if (dpEl) {
          const prev = parseFloat(dpEl.textContent.replace(/[^-\d.]/g,''));
          dpEl.textContent = (snap.daily_pnl >= 0 ? '+$' : '-$') + Math.abs(snap.daily_pnl).toFixed(2);
          dpEl.className = 'val ' + (snap.daily_pnl >= 0 ? 'positive' : 'negative');
          flashEl(dpEl, snap.daily_pnl, prev);
        }
      }

      // ── CLOB connection dot in topbar ──
      if (snap.clob_connected != null) {
        const dot = $('wsDot');
        if (dot) {
          dot.className = 'conn-dot ' + (snap.clob_connected ? 'on' : 'off');
          dot.title = snap.clob_connected ? 'CLOB connected' : 'CLOB disconnected';
        }
      }

      // ── Cooldown indicator on botStatus badge ──
      if (snap.cooldown_active) {
        const b = $('botStatus');
        if (b && !snap.killed) {
          const secs = snap.cooldown_remaining_seconds != null ? Math.ceil(snap.cooldown_remaining_seconds) : '?';
          b.textContent = `⏸ cooldown ${secs}s`;
          b.style.background = 'var(--amber-bg)';
          b.style.color = 'var(--amber)';
        }
      }

      // ── LLM response time — store globally for display in trade table ──
      if (snap.llm_response_time != null) {
        window._lastLlmMs = snap.llm_response_time;
      }

      // ── Live market question + timer ──
      if (snap.current_market_question) {
        const qEl = $('liveMarketQ');
        if (qEl) qEl.textContent = snap.current_market_question;
      }
      if (snap.time_to_expiry != null) {
        window._timeToExpiry = snap.time_to_expiry;
        window._entryWindowTotal = snap.entry_window_total || 300; // BUG FIX 4: store total for init.js countdown
        const total = window._entryWindowTotal;
        const elapsed = total - snap.time_to_expiry;
        const pct = Math.min(100, Math.max(0, (elapsed / total) * 100));
        const fill = $('liveMarketBarFill');
        if (fill) fill.style.width = pct + '%';
        // Color: green → amber → red as time runs out
        const color = snap.time_to_expiry > 120 ? 'var(--green)' : snap.time_to_expiry > 30 ? 'var(--amber)' : 'var(--red)';
        if (fill) fill.style.background = color;
      }

    } catch(err) {}
  };
}