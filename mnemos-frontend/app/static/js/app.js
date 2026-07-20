// Mnemos UI wiring (HTMX + WebSocket bridge)

(function () {
  // ---- Alpine re-init on HTMX swap ------------------------------------
  //
  // Alpine walks the DOM once on page load to wire up `x-data`,
  // `x-show`, etc. When HTMX swaps a new fragment in (e.g. the
  // identify result card), Alpine does not notice by default. We
  // explicitly call `Alpine.initTree` on the swapped subtree so the
  // new `x-data="faceAction()"` directives become live.
  //
  // The catch: if the target already had Alpine components (e.g. a
  // previous identify result that's about to be replaced), we have
  // to destroy them first — otherwise their reactive `x-for`
  // templates keep rendering alongside the new ones, which manifests
  // as a dropdown list that gets a duplicate entry on every rerun.
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const target = e.target;
    if (target && window.Alpine && typeof window.Alpine.destroyTree === 'function') {
      try { window.Alpine.destroyTree(target); } catch (_) { /* ignore */ }
    }
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const target = e.target;
    if (target && window.Alpine && typeof window.Alpine.initTree === 'function') {
      try { window.Alpine.initTree(target); } catch (_) { /* ignore */ }
    }
  });

  // ---- WebSocket bridge -------------------------------------------------
  //
  // The HTMX `ws` extension reads `ws-connect` on page load. We initially
  // render the element without a target, fetch the correct URL from
  // /partials/ws-target, set `ws-connect`, and then process incoming
  // frames as DOM CustomEvents so `from:body` triggers in templates fire.
  async function setupWebSocket() {
    const wsEl = document.querySelector('[hx-ext="ws"]');
    if (!wsEl || wsEl.dataset.mnemosWsReady === '1') return;
    // Don't try to connect to /ws/events until the user has a session
    // cookie — otherwise the WS proxy returns 403/4401 and floods the
    // console with errors during the onboarding / login flow. We probe
    // /healthz which is session-independent: 200 = we're at least past
    // the unauthenticated splash. (The actual session check still
    // happens inside the WS upgrade.)
    try {
      const probe = await fetch('/healthz', { credentials: 'same-origin' });
      if (!probe.ok) return;
      // Only connect if the response indicates a logged-in user. The
      // JSON payload includes a `user` field when authenticated.
      const j = await probe.json().catch(() => null);
      if (!j || !j.user) return;
    } catch (_) {
      return;
    }
    let wsUrl;
    try {
      const r = await fetch('/partials/ws-target', { credentials: 'same-origin' });
      if (!r.ok) return;
      const j = await r.json();
      wsUrl = j.ws_url;
    } catch (_) {
      return;
    }
    if (!wsUrl) return;
    wsEl.setAttribute('ws-connect', wsUrl);
    try { htmx.process(wsEl); } catch (_) { /* ignore */ }
    wsEl.dataset.mnemosWsReady = '1';

    // The htmx WS extension fires `htmx:wsBeforeMessage` BEFORE it
    // tries to parse the frame as an HTML fragment, and
    // `htmx:wsAfterMessage` after. We listen to `BeforeMessage` so we
    // can intercept the raw frame and re-broadcast it as a
    // `body` CustomEvent for Alpine components and htmx `from:body`
    // triggers. (We previously listened for `htmx:wsMessage` which
    // doesn't exist on the upstream htmx 1.9 WS extension — the
    // extension handles the message itself, expecting it to be an
    // HTML fragment, and fires `wsBeforeMessage` / `wsAfterMessage`.)
    wsEl.addEventListener('htmx:wsBeforeMessage', (ev) => {
      let payload = null;
      try { payload = JSON.parse(ev.detail.message); } catch (_) { return; }
      if (!payload || !payload.type) return;
      // Re-broadcast as a CustomEvent on `body` so `hx-trigger` rules
      // like `inbox.new_face from:body` fire correctly.
      document.body.dispatchEvent(new CustomEvent(payload.type, { detail: payload }));
      // Also emit a `ws:TYPE` variant so Alpine components that
      // listen via `document.addEventListener('ws:reindex.progress',
      // ...)` don't have to share the same event namespace as htmx's
      // `from:body` triggers (which use the bare type).
      document.body.dispatchEvent(new CustomEvent('ws:' + payload.type, { detail: payload }));
    });

    // Reconnect is automatic; on close, force a counter refresh so
    // we don't get stuck on a stale number. We dispatch on
    // `document.body` (not `window`) so htmx's `from:body` modifier
    // picks the event up.
    wsEl.addEventListener('htmx:wsClose', () => {
      try { document.body.dispatchEvent(new Event('inbox.bulk_changed')); } catch (_) {}
    });
  }

  // Re-probe periodically so we connect as soon as the user signs in
  // (e.g. on the dashboard after a fresh login from a different tab).
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupWebSocket);
  } else {
    setupWebSocket();
  }
  setInterval(setupWebSocket, 5 * 1000);

  // ---- Inbox counter via WebSocket ------------------------------------
  //
  // The backend publishes `inbox.new_face` whenever a new face is
  // identified. We bump the counter locally (no HTTP roundtrip) and
  // also fall back to an htmx refresh on `inbox.bulk_changed` and on
  // 30s poll as a safety net in case the WS missed a frame.
  let _inboxTotal = null;
  function setInboxCount(n) {
    const link = document.getElementById('inbox-counter');
    if (!link) return;
    const pill = link.querySelector('.pill');
    if (!pill) return;
    pill.innerHTML = '<span class="dot"></span> Inbox ' + (n | 0);
  }

  async function refreshInboxCount() {
    try {
      const r = await fetch('/partials/inbox-count', { credentials: 'same-origin' });
      if (!r.ok) return;
      const tmp = document.createElement('div');
      tmp.innerHTML = await r.text();
      // The partial renders `<span class="pill"><span class="dot"></span> Inbox N</span>`.
      const txt = (tmp.textContent || '').replace(/[^\d]/g, '');
      const n = parseInt(txt, 10);
      if (Number.isFinite(n)) {
        _inboxTotal = n;
        setInboxCount(n);
      }
    } catch (_) { /* ignore */ }
  }

  // Seed the counter on first paint and on every inbox.bulk_changed.
  document.addEventListener('DOMContentLoaded', refreshInboxCount);
  document.body.addEventListener('inbox.bulk_changed', refreshInboxCount);

  // On a new face event, optimistically bump the visible counter.
  document.body.addEventListener('inbox.new_face', () => {
    if (_inboxTotal === null) {
      refreshInboxCount();
      return;
    }
    _inboxTotal = _inboxTotal + 1;
    setInboxCount(_inboxTotal);
  });

  // On a bulk removal (assign/ignore/mark-non-face), refresh — we
  // don't try to compute the exact delta from the WS frame because
  // the user might have done the action themselves locally and the
  // number going down is easier to read after a single refresh.
  document.body.addEventListener('inbox.bulk_changed', refreshInboxCount);

  // Periodic safety net: if the WS missed something, this catches up.
  setInterval(refreshInboxCount, 30 * 1000);

  // ---- Dedicated raw WebSocket for reindex events --------------------
  //
  // htmx's WS extension is great for `from:body` triggers (e.g. the
  // inbox counter) but its internal event flow is opaque — we kept
  // fighting `htmx:wsMessage` vs `htmx:wsBeforeMessage` and
  // addEventListener-vs-htmx.process races. For the reindex banner we
  // just want raw JSON frames to land in Alpine. So we open a
  // *second* WebSocket in parallel to the htmx one. The backend's
  // `websocket_hub.publish` fan-out is happy to serve any number of
  // clients — there's no extra cost.
  let _reindexWs = null;
  let _reindexWsBackoff = 1000;
  function connectReindexWs() {
    fetch('/partials/ws-target', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j || !j.ws_url) return;
        try { _reindexWs && _reindexWs.close(); } catch (_) { /* ignore */ }
        const ws = new WebSocket(j.ws_url);
        _reindexWs = ws;
        ws.addEventListener('open', () => { _reindexWsBackoff = 1000; });
        ws.addEventListener('message', (ev) => {
          let payload = null;
          try { payload = JSON.parse(ev.data); } catch (_) { return; }
          if (!payload || !payload.type) return;
          // Re-broadcast under the same names the Alpine component
          // already listens for: the bare type and a `ws:` prefixed
          // variant. We dispatch on `document` (not `body`) and set
          // `bubbles: true` so listeners on `document` / `window`
          // (which is what the Alpine `init()` uses) actually see
          // the event. Dispatching on body alone does not bubble to
          // the document or window.
          const opts = { detail: payload, bubbles: true };
          try { document.dispatchEvent(new CustomEvent(payload.type, opts)); } catch (_) { /* ignore */ }
          try { document.dispatchEvent(new CustomEvent('ws:' + payload.type, opts)); } catch (_) { /* ignore */ }
        });
        ws.addEventListener('close', () => {
          _reindexWs = null;
          setTimeout(connectReindexWs, _reindexWsBackoff);
          _reindexWsBackoff = Math.min(_reindexWsBackoff * 2, 30000);
        });
        ws.addEventListener('error', () => { /* close will retry */ });
      })
      .catch(() => {
        setTimeout(connectReindexWs, _reindexWsBackoff);
        _reindexWsBackoff = Math.min(_reindexWsBackoff * 2, 30000);
      });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connectReindexWs);
  } else {
    connectReindexWs();
  }
  // Keep-alive reconnect in case the first connect raced sign-in.
  setInterval(() => {
    if (!_reindexWs || _reindexWs.readyState === WebSocket.CLOSED) {
      connectReindexWs();
    }
  }, 5000);
})();
