// ═══════════════════════ PRICE CHART (Canvas) — v3.3 ═══════════════════════
function drawPriceChart() {
  const canvas = $('priceCanvas');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const needsResize = canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr);
  if (needsResize) {
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.scale(dpr, dpr);
  }
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);

  // ── Build data array ──
  const all = [];
  priceHistory.forEach(h => all.push({ t: new Date(h.t).getTime(), p: h.p }));
  const lastHistT = all.length ? all[all.length - 1].t : 0;
  livePrices.forEach(lp => { if (lp.t > lastHistT) all.push(lp); });

  if (all.length < 2) {
    ctx.fillStyle = '#6b7280'; ctx.font = '12px Inter,sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Loading chart data...', W / 2, H / 2);
    return;
  }

  // ── Market mode: fixed 0-5min window ──
  let fixedMinT, fixedMaxT;
  if (_marketMode) {
    const now = Date.now();
    // Current 5-min market window: floor to nearest 5min
    fixedMinT = Math.floor(now / 300000) * 300000;
    fixedMaxT = fixedMinT + 300000;
  }

  // ── Scale ──
  const dataMinT = all[0].t, dataMaxT = all[all.length - 1].t;
  const minT = _marketMode ? fixedMinT : dataMinT;
  const maxT = _marketMode ? fixedMaxT : dataMaxT;

  // Filter data to visible range for price scale
  const visible = _marketMode ? all.filter(d => d.t >= minT && d.t <= maxT) : all;
  if (visible.length < 1) {
    ctx.fillStyle = '#6b7280'; ctx.font = '12px Inter,sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Waiting for market data...', W / 2, H / 2);
    return;
  }

  let minP = Infinity, maxP = -Infinity;
  visible.forEach(d => { if (d.p < minP) minP = d.p; if (d.p > maxP) maxP = d.p; });
  // Include strike price in scale if it's valid
  if (window._strikePrice > 0) {
    minP = Math.min(minP, window._strikePrice);
    maxP = Math.max(maxP, window._strikePrice);
  }
  // Include Chainlink prices in scale
  const clInRange = _marketMode
    ? clPrices.filter(d => d.t >= minT && d.t <= maxT)
    : clPrices.filter(d => d.t >= minT);
  clInRange.forEach(d => { if (d.p < minP) minP = d.p; if (d.p > maxP) maxP = d.p; });
  const priceRange = maxP - minP || 50;
  const pad = priceRange * 0.10;
  minP -= pad; maxP += pad;

  const LM = 64, RM = 12, TM = 8, BM = 22;
  const plotW = W - LM - RM;
  const plotH = H - TM - BM;
  const x = t => LM + ((t - minT) / (maxT - minT || 1)) * plotW;
  const y = p => TM + plotH - ((p - minP) / (maxP - minP || 1)) * plotH;

  // ── Grid lines (horizontal) ──
  ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const gy = TM + (i / 4) * plotH;
    ctx.beginPath(); ctx.moveTo(LM, gy); ctx.lineTo(W - RM, gy); ctx.stroke();
    const pv = maxP - (i / 4) * (maxP - minP);
    ctx.fillStyle = '#6b7280'; ctx.font = '10px Inter,sans-serif'; ctx.textAlign = 'right';
    ctx.fillText('$' + pv.toLocaleString('en-US', { maximumFractionDigits: 0 }), LM - 6, gy + 3);
  }

  // ── Vertical grid ──
  let vInterval;
  const spanMs = maxT - minT;
  if (spanMs <= 120000) vInterval = 15000;
  else if (spanMs <= 600000) vInterval = 60000;
  else if (spanMs <= 3600000) vInterval = 300000;
  else if (spanMs <= 28800000) vInterval = 3600000;
  else vInterval = 14400000;

  const vLabelFmt = spanMs <= 120000
    ? t => { const d = new Date(t); return d.getMinutes() + ':' + String(d.getSeconds()).padStart(2,'0'); }
    : t => fmtTime(t);

  // Market mode: show minute marks (0:00 to 5:00)
  if (_marketMode) {
    ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    for (let s = 60000; s < 300000; s += 60000) {
      const xi = x(minT + s);
      ctx.beginPath(); ctx.moveTo(xi, TM); ctx.lineTo(xi, TM + plotH); ctx.stroke();
    }
    ctx.setLineDash([]);
    // Minute labels: 0:00 through 5:00
    ctx.fillStyle = '#6b7280'; ctx.font = '10px Inter,sans-serif'; ctx.textAlign = 'center';
    for (let s = 0; s <= 300000; s += 60000) {
      const xi = x(minT + s);
      if (xi >= LM && xi <= W - RM) ctx.fillText(Math.floor(s/60000) + ':00', xi, H - 4);
    }
  } else {
    // 5-min market boundaries on 1m/5m
    if (currentRangeSeconds <= 300) {
      ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      const mStart = Math.ceil(minT / 300000) * 300000;
      for (let t = mStart; t <= maxT; t += 300000) {
        const xi = x(t); if (xi < LM + 2) continue;
        ctx.beginPath(); ctx.moveTo(xi, TM); ctx.lineTo(xi, TM + plotH); ctx.stroke();
      }
      ctx.setLineDash([]);
    }
    // Time axis labels
    ctx.fillStyle = '#6b7280'; ctx.font = '10px Inter,sans-serif'; ctx.textAlign = 'center';
    const vStart = Math.ceil(minT / vInterval) * vInterval;
    let lastLabelX = -100;
    for (let t = vStart; t <= maxT; t += vInterval) {
      const xi = x(t);
      if (xi < LM + 20 || xi > W - RM - 20 || xi - lastLabelX < 50) continue;
      lastLabelX = xi;
      ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(xi, TM + plotH); ctx.lineTo(xi, TM + plotH + 4); ctx.stroke();
      ctx.fillText(vLabelFmt(t), xi, H - 4);
    }
  }

  // ── STRIKE PRICE LINE (price to beat) ──
  if (window._strikePrice > 0 && window._strikePrice >= minP && window._strikePrice <= maxP) {
    const sy = y(window._strikePrice);
    // Dashed line
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(LM, sy); ctx.lineTo(W - RM, sy); ctx.stroke();
    ctx.setLineDash([]);
    // Label
    ctx.font = 'bold 10px Inter,sans-serif'; ctx.textAlign = 'left';
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.fillText('STRIKE $' + window._strikePrice.toLocaleString('en-US', {maximumFractionDigits:2}), LM + 4, sy - 5);
  }


  // ── CHAINLINK PRICE LINE (settlement line) ──
  const clVisible = _marketMode
    ? clPrices.filter(d => d.t >= minT && d.t <= maxT)
    : clPrices.filter(d => d.t >= minT);
  if (clVisible.length >= 2) {
    const clPts = clVisible.map(d => ({ px: x(d.t), py: y(d.p) }));
    // Gradient fill (purple, subtle)
    ctx.beginPath();
    ctx.moveTo(clPts[0].px, clPts[0].py);
    for (let i = 1; i < clPts.length; i++) ctx.lineTo(clPts[i].px, clPts[i].py);
    const clLast = clPts[clPts.length - 1];
    ctx.lineTo(clLast.px, TM + plotH);
    ctx.lineTo(clPts[0].px, TM + plotH);
    ctx.closePath();
    const clGrad = ctx.createLinearGradient(0, TM, 0, TM + plotH);
    clGrad.addColorStop(0, 'rgba(52, 211, 153, 0.06)');
    clGrad.addColorStop(1, 'rgba(52, 211, 153, 0)');
    ctx.fillStyle = clGrad;
    ctx.fill();
    // Line
    ctx.beginPath();
    ctx.moveTo(clPts[0].px, clPts[0].py);
    for (let i = 1; i < clPts.length; i++) ctx.lineTo(clPts[i].px, clPts[i].py);
    ctx.strokeStyle = '#34d399';
    ctx.lineWidth = 2;
    ctx.stroke();
    // Current Chainlink dot
    const lastCl = clVisible[clVisible.length - 1];
    const clx = x(lastCl.t), cly = y(lastCl.p);
    ctx.beginPath(); ctx.arc(clx, cly, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#34d399'; ctx.fill();
    // Chainlink price label (left side)
    ctx.font = 'bold 10px Inter,sans-serif'; ctx.textAlign = 'left'; ctx.fillStyle = '#34d399';
    ctx.fillText('CL $' + lastCl.p.toLocaleString('en-US', {maximumFractionDigits:2}), LM + 4, cly + 14);
  }

  // ── Price line: use lineTo for speed, bezier only for <500 points ──
  const pts = visible.map(d => ({ px: x(d.t), py: y(d.p) }));
  if (pts.length < 2) return;

  const useBezier = pts.length < 1200; // smooth bezier for all practical ranges
  const lastPt = pts[pts.length - 1];
  // Always use consistent blue (no red/blue color flip)

  // Gradient fill
  ctx.beginPath();
  ctx.moveTo(pts[0].px, pts[0].py);
  if (useBezier) {
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i-1], curr = pts[i];
      const cpx = (prev.px + curr.px) / 2;
      ctx.quadraticCurveTo(prev.px, prev.py, cpx, (prev.py + curr.py) / 2);
    }
  } else {
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].px, pts[i].py);
  }
  ctx.lineTo(lastPt.px, lastPt.py);
  ctx.lineTo(lastPt.px, TM + plotH);
  ctx.lineTo(pts[0].px, TM + plotH);
  ctx.closePath();
  const gradColor = '56, 189, 248'; // cyan accent (v5.0 Onlook-style)
  const grad = ctx.createLinearGradient(0, TM, 0, TM + plotH);
  grad.addColorStop(0, `rgba(${gradColor}, 0.12)`);
  grad.addColorStop(0.6, `rgba(${gradColor}, 0.03)`);
  grad.addColorStop(1, `rgba(${gradColor}, 0)`);
  ctx.fillStyle = grad;
  ctx.fill();

  // Price line
  ctx.beginPath();
  ctx.moveTo(pts[0].px, pts[0].py);
  if (useBezier) {
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i-1], curr = pts[i];
      const cpx = (prev.px + curr.px) / 2;
      ctx.quadraticCurveTo(prev.px, prev.py, cpx, (prev.py + curr.py) / 2);
    }
  } else {
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].px, pts[i].py);
  }
  ctx.lineTo(lastPt.px, lastPt.py);
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 2;
  ctx.stroke();

  // ── Current price dot + label ──
  const last = visible[visible.length - 1];
  const lx = x(last.t), ly = y(last.p);

  // Dashed horizontal at current price
  ctx.strokeStyle = 'rgba(56,189,248,0.22)';
  ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
  ctx.beginPath(); ctx.moveTo(LM, ly); ctx.lineTo(W - RM, ly); ctx.stroke();
  ctx.setLineDash([]);

  // Glow dot
  ctx.beginPath(); ctx.arc(lx, ly, 5, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(56,189,248,0.16)'; ctx.fill();
  ctx.beginPath(); ctx.arc(lx, ly, 3, 0, Math.PI * 2);
  ctx.fillStyle = '#38bdf8'; ctx.fill();

  // Price badge
  const priceStr = '$' + last.p.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  ctx.font = 'bold 10px Inter,sans-serif';
  const tw = ctx.measureText(priceStr).width;
  const bx = W - RM - tw - 10, by = ly - 9;
  ctx.fillStyle = '#38bdf8';
  ctx.beginPath(); ctx.roundRect(bx, by, tw + 10, 18, 4); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.textAlign = 'left';
  ctx.fillText(priceStr, bx + 5, ly + 4);

  // ── Market timer (bot WS authoritative, signal arrival fallback) ──
  const botElapsed = window._botElapsed || 0;
  const sigElapsed = window._signalArrivalTime > 0 ? Math.floor((Date.now() - window._signalArrivalTime) / 1000) : 0;
  const useElapsed = botElapsed > 0 ? botElapsed : sigElapsed;
  if (useElapsed > 0) {
    const elapsed = Math.min(300, Math.floor(useElapsed));
    const timerText = 'Market: ' + elapsed + 's / 300s';
    ctx.fillStyle = '#6b7280'; ctx.font = '600 11px Inter,sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(timerText, W - RM, TM + 14);
  }

  // ── Tick latency ──
  if (window._lastTickMs > 0) {
    const tickAge = Date.now() - window._lastTickMs;
    const tickColor = tickAge < 500 ? '#12B76A' : tickAge < 2000 ? '#F79009' : '#F04438';
    ctx.fillStyle = tickColor; ctx.font = '10px Inter,sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(tickAge < 1000 ? 'LIVE' : tickAge < 5000 ? (tickAge/1000).toFixed(1)+'s ago' : 'STALE', LM + 4, TM + 12);
  }

  // ── Market mode: progress bar at bottom ──
  if (_marketMode) {
    const now = Date.now();
    const progress = Math.min(1, (now - minT) / 300000);
    const barY = TM + plotH + 2;
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.fillRect(LM, barY, plotW, 3);
    ctx.fillStyle = progress < 0.8 ? '#38bdf8' : '#fbbf24';
    ctx.fillRect(LM, barY, plotW * progress, 3);
  }
}

// ═══════════════════════ SIGNAL ACTIVITY CHART ═══════════════════════
let signalData = [];
function drawSignalChart() {
  const canvas = $('signalCanvas');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);
  if (!signalData.length) return;

  const maxSig = Math.max(...signalData.map(d => d.signals)) || 1;
  const barW = (W - 40) / signalData.length - 2;

  signalData.forEach((d, i) => {
    const bx = 40 + i * ((W - 40) / signalData.length);
    const bh = (d.signals / maxSig) * (H - 28);

    // Signal bar (dark)
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.fillRect(bx, H - 20 - bh, barW, bh);

    // Fired overlay (cyan accent)
    if (d.fired > 0) {
      const fh = (d.fired / maxSig) * (H - 28);
      ctx.fillStyle = '#38bdf8';
      ctx.fillRect(bx, H - 20 - fh, barW, fh);
    }

    // Time label (every 4th)
    if (i % 4 === 0) {
      ctx.fillStyle = '#6b7280'; ctx.font = '9px Inter,sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(fmtTime(d.hour), bx + barW/2, H - 4);
    }
  });
}

// ═══════════════════════ VOL & EDGE RADAR ═══════════════════════
let latestSignal = null;
function drawVolRadar() {
  if (!latestSignal) return;
  
  const canvas = $('volCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);

  // Extract signal data
  const realVol = (latestSignal.sigma_realized || 0) * 100;
  const implVol = (latestSignal.implied_vol || 0) * 100;
  const termEdge = (latestSignal.terminal_edge || 0) * 100;
  const condsMet = latestSignal.conditions_met || 0;
  const condsTotal = 15; // Changed from 12 to 15
  const strikeDelta = latestSignal.strike_delta || 0;

  // Bar dimensions
  const barHeight = 30;
  const barGap = 8;
  const startY = 10;
  const labelWidth = 90;
  const barX = labelWidth + 10;
  const barWidth = W - barX - 20;

  ctx.font = '11px Inter,sans-serif';
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'right';

  // Helper: draw horizontal bar (no value text — stats panel shows values)
  const drawBar = (y, label, value, max, color) => {
    ctx.fillStyle = '#6b7280'; ctx.textAlign = 'right';
    ctx.fillText(label, labelWidth - 5, y + 10);
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.fillRect(barX, y, barWidth, 12);
    const fillW = Math.max(0, Math.min((value / max) * barWidth, barWidth));
    ctx.fillStyle = color;
    ctx.fillRect(barX, y, fillW, 12);
  };

  // Draw bars
  let currentY = startY;
  
  // Realized Vol (orange, 0-300%)
  drawBar(currentY, 'Realized Vol', realVol, 300, '#F79009');
  currentY += barHeight + barGap;
  
  // Implied Vol (purple, 0-300%)
  drawBar(currentY, 'Implied Vol', implVol, 300, '#0891B2');
  currentY += barHeight + barGap;
  
  // Terminal Edge (dark background, with green zone > 3%)
  ctx.fillStyle = 'rgba(255,255,255,0.05)';
  ctx.fillRect(barX, currentY, barWidth, 12);
  // Green "fire zone" (3% to 20%)
  const fireStart = Math.max(0, (3 / 30) * barWidth);
  const fireEnd = Math.min(barWidth, (20 / 30) * barWidth);
  ctx.fillStyle = 'rgba(52, 211, 153, 0.12)';
  ctx.fillRect(barX + fireStart, currentY, fireEnd - fireStart, 12);
  // Actual edge bar
  const edgeMin = -10, edgeMax = 20;
  const edgeNorm = Math.max(0, Math.min((termEdge - edgeMin) / (edgeMax - edgeMin), 1));
  ctx.fillStyle = termEdge >= 3 ? '#34d399' : '#38bdf8';
  ctx.fillRect(barX, currentY, edgeNorm * barWidth, 12);
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'right';
  ctx.fillText('Terminal Edge', labelWidth - 5, currentY + 10);
  currentY += barHeight + barGap;

  // Conditions Met (0-15, turns green at 15)
  drawBar(currentY, 'Conditions', condsMet, condsTotal, condsMet === condsTotal ? '#34d399' : '#38bdf8');
}

// ═══════════════════════ EQUITY CURVE ═══════════════════════
let tradeData = [];
function drawEquityCurve() {
  const canvas = $('equityCanvas');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);
  if (!tradeData.length) return;

  // Build cumulative
  let cum = 0;
  const pts = tradeData.map(t => { cum += t.pnl; return { t: new Date(t.ts).getTime(), v: cum }; });

  let minV = Math.min(0, ...pts.map(p => p.v));
  let maxV = Math.max(0, ...pts.map(p => p.v));
  const pad = (maxV - minV) * 0.15 || 5;
  minV -= pad; maxV += pad;

  const x = (t,i) => 30 + (i / (pts.length - 1 || 1)) * (W - 40);
  const y = v => H - 16 - ((v - minV) / (maxV - minV)) * (H - 28);

  // Zero line
  ctx.strokeStyle = 'rgba(255,255,255,0.05)'; ctx.lineWidth = 1; ctx.setLineDash([4,4]);
  ctx.beginPath(); ctx.moveTo(30, y(0)); ctx.lineTo(W, y(0)); ctx.stroke();
  ctx.setLineDash([]);

  // Line
  ctx.beginPath(); ctx.strokeStyle = cum >= 0 ? '#34d399' : '#f87171'; ctx.lineWidth = 2;
  pts.forEach((p,i) => { i === 0 ? ctx.moveTo(x(p.t,i), y(p.v)) : ctx.lineTo(x(p.t,i), y(p.v)); });
  ctx.stroke();

  // Fill
  ctx.lineTo(x(pts[pts.length-1].t, pts.length-1), y(0));
  ctx.lineTo(x(pts[0].t, 0), y(0));
  ctx.closePath();
  ctx.fillStyle = cum >= 0 ? 'rgba(52,211,153,0.08)' : 'rgba(248,113,113,0.08)';
  ctx.fill();

  // End label
  ctx.fillStyle = cum >= 0 ? '#34d399' : '#f87171';
  ctx.font = 'bold 11px Inter,sans-serif'; ctx.textAlign = 'right';
  ctx.fillText(fmtUsd(cum), W - 4, y(cum) - 6);
}
