// ═══════════════════════ MODE ROUTER ═══════════════════════
// Hash-based tabs for Live vs Analytics. Preserves `?secret=...` because
// it only touches `location.hash`, never `location.search`. Default view
// is `live` when the hash is empty or unrecognized.

(function () {
  const VIEWS = ['live', 'analytics'];
  const DEFAULT_VIEW = 'live';

  function parseView() {
    // Accept "#/live", "#live", "#/analytics?...", etc.
    const raw = (location.hash || '').replace(/^#\/?/, '').split(/[?&]/)[0].toLowerCase();
    return VIEWS.includes(raw) ? raw : DEFAULT_VIEW;
  }

  function applyView(view) {
    VIEWS.forEach((v) => {
      const section = document.getElementById('view-' + v);
      if (!section) return;
      if (v === view) section.removeAttribute('hidden');
      else section.setAttribute('hidden', '');
    });
    document.querySelectorAll('.tab[data-view]').forEach((tab) => {
      tab.classList.toggle('is-active', tab.dataset.view === view);
    });
    // Nudge canvas-based charts so they pick up the now-visible size.
    // Fire after the browser has a chance to layout the unhidden section.
    requestAnimationFrame(() => {
      if (typeof scheduleChartDraw === 'function') scheduleChartDraw();
      if (typeof drawSignalChart  === 'function') drawSignalChart();
      if (typeof drawEquityCurve  === 'function') drawEquityCurve();
      if (typeof drawVolRadar     === 'function') drawVolRadar();
    });
  }

  function onHashChange() {
    applyView(parseView());
  }

  function initMode() {
    // If no hash at all, set one (reload-safe, sharable URL).
    if (!location.hash) {
      history.replaceState(null, '', '#/' + DEFAULT_VIEW + location.search);
    }
    applyView(parseView());
    window.addEventListener('hashchange', onHashChange);
    // Tab clicks: let the anchor hash-update fire, we just ensure no
    // page reload and that we keep `?secret=...` intact.
    document.querySelectorAll('.tab[data-view]').forEach((tab) => {
      tab.addEventListener('click', (e) => {
        const v = tab.dataset.view;
        if (!v) return;
        e.preventDefault();
        // `history.pushState` avoids polluting back-button with trivial hash
        // swaps; `hashchange` won't fire for pushState so we apply directly.
        history.pushState(null, '', '#/' + v + location.search);
        applyView(v);
      });
    });
  }

  // Expose for init.js to call after session-tag bootstrap, but also
  // safe to call on DOMContentLoaded for first paint.
  window.initMode = initMode;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMode, { once: true });
  } else {
    initMode();
  }
})();
