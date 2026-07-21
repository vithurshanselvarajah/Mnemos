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

  (function () {
    // Guard: Prevent script from running twice if included in multiple templates
    if (window.__inboxCounterActive) return;
    window.__inboxCounterActive = true;

    let _abortController = null;

    async function refreshInboxCount() {
      // Cancel any previous in-flight request so slow network responses never overwrite fresh ones
      if (_abortController) _abortController.abort();
      _abortController = new AbortController();

      try {
        const r = await fetch('/partials/inbox-count', {
          credentials: 'same-origin',
          signal: _abortController.signal
        });
        if (!r.ok) return;

        const rawText = await r.text(); // e.g., "Inbox 3"

        // Targeted Regex: Extract ONLY the number immediately following "Inbox"
        const match = rawText.match(/Inbox\s*(\d+)/i) || rawText.match(/\d+/);

        if (match && match[1]) {
          const count = parseInt(match[1], 10);
          if (Number.isFinite(count)) {
            const link = document.getElementById('inbox-counter');
            if (link) {
              // Re-render the pill cleanly with the exact server count
              link.innerHTML = `<span class="pill"><span class="dot"></span> Inbox ${count}</span>`;
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.error('Failed to update inbox count:', err);
      }
    }

    // 1. Initial Load
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', refreshInboxCount);
    } else {
      refreshInboxCount();
    }

    // 2. Re-fetch on WebSocket events (No local +1 math = zero risk of duplication!)
    document.body.addEventListener('inbox.bulk_changed', refreshInboxCount);
    document.body.addEventListener('inbox.new_face', refreshInboxCount);

    // 3. Fallback Poll (30 seconds)
    setInterval(refreshInboxCount, 30000);
  })();

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
