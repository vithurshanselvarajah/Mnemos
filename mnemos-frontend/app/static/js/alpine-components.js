// Global Alpine.js components for Mnemos.
//
// These are registered as plain functions on `window` so that templates
// swapped in by HTMX can reference them via `x-data="name()"`. The Alpine
// runtime needs the function to be available *before* it walks the new
// DOM, which is why we keep these definitions in a script loaded
// alongside Alpine itself (see base.html).
//
// All components here also expose a `destroy()` method that Alpine will
// call when the host element is removed (via `Alpine.destroyTree`).
// The destroy hook is the only place we can remove document-level
// listeners we add during `init()`; without it, repeated HTMX swaps on
// the identify / inbox pages stack duplicate listeners and duplicate
// rendered DOM — manifesting as a "triplicated" suggestion dropdown
// when the user types a name.
//
// To avoid Alpine's known issue where `<template x-for>` rendered
// children aren't always cleaned up by `Alpine.destroyTree`, the
// `nameSuggest` component renders its dropdown into a single `<ul>`
// via `x-html` (manual DOM render in `renderList()`), and `destroy()`
// wipes the `<ul>` and removes all listeners. This is the most
// reliable pattern for HTMX-swapped subtrees.

// ---- faceAction: per-unknown-face card on the identify result page. -----
window.faceAction = function faceAction() {
  return {
    mode: 'existing',
    newName: '',
    existingId: '',
    busy: false,
    get cropId() {
      let el = this.$el;
      while (el) {
        if (el.dataset && el.dataset.cropId) return el.dataset.cropId;
        el = el.parentElement;
      }
      return null;
    },
    get cropIdsJson() { return JSON.stringify([this.cropId]); },
    init() {
      const sel = this.$el.querySelector('select');
      if (sel && sel.options.length && !this.existingId) {
        this.existingId = sel.value;
      }
    },
    get target() {
      if (this.mode === 'new') return 'new';
      return this.existingId || '';
    },
    get canSubmit() {
      if (this.mode === 'new') return this.newName.trim().length > 0;
      return this.target !== '' && this.target !== 'new';
    },
    get label() { return this.canSubmit ? 'Assign' : 'Pick a target'; },
    setMode(m) { this.mode = m; },
    async markNonFace() {
      if (this.busy) return;
      this.busy = true;
      const r = await fetch('/backend/faces/mark-non-face', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crop_ids: [this.cropId] }),
        credentials: 'same-origin',
      });
      this.busy = false;
      this.fadeOut(r.ok);
    },
    async ignoreFace() {
      if (this.busy) return;
      this.busy = true;
      const r = await fetch('/backend/faces/ignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crop_ids: [this.cropId] }),
        credentials: 'same-origin',
      });
      this.busy = false;
      this.fadeOut(r.ok);
    },
    onAfter(e) {
      this.fadeOut(e.detail && e.detail.successful);
    },
    fadeOut(ok) {
      if (!ok) return;
      this.$el.style.transition = 'opacity .3s, transform .3s';
      this.$el.style.opacity = '0.4';
      this.$el.style.transform = 'scale(0.98)';
      try { document.body.dispatchEvent(new Event('inbox.bulk_changed')); } catch (_) {}
      setTimeout(() => { this.$el.remove(); }, 600);
    },
  };
};

// ---- nameSuggest: typeahead combobox that also offers "create new". -----
//
// Lives in a single `<ul>` rendered via `x-html` so destroy() can
// fully wipe the rendered children. Nested x-data has a tendency to
// stack its `<template x-for>` output across HTMX swaps; this pattern
// sidesteps that entirely.
window.nameSuggest = function nameSuggest() {
  return {
    value: '',
    open: false,
    activeIndex: -1,
    persons: [],
    _listeners: [],
    _renderToken: 0,
    init() {
      const root = this.$el.closest('[data-suggest-list]') || this.$el;
      const raw = root.getAttribute('data-suggest-list');
      if (raw) {
        try { this.persons = JSON.parse(raw) || []; } catch (_) { this.persons = []; }
      }
      const onDocClick = (ev) => {
        if (!this.$el.contains(ev.target)) this.open = false;
      };
      document.addEventListener('mousedown', onDocClick);
      this._listeners.push([document, 'mousedown', onDocClick]);
    },
    destroy() {
      for (const entry of this._listeners) {
        const t = entry && entry[0];
        const ev = entry && entry[1];
        const fn = entry && entry[2];
        if (t && typeof t.removeEventListener === 'function' && ev && fn) {
          try { t.removeEventListener(ev, fn); } catch (_) { /* ignore */ }
        }
      }
      this._listeners = [];
      this._renderToken++;
      const list = this.$el.querySelector('.suggest-list');
      if (list) {
        list.innerHTML = '';
        list.style.display = 'none';
      }
    },
    get query() { return (this.value || '').trim().toLowerCase(); },
    get matches() {
      if (!this.query) {
        return this.persons.slice(0, 8);
      }
      const q = this.query;
      const prefix = [];
      const sub = [];
      for (const p of this.persons) {
        const n = (p.name || '').toLowerCase();
        if (n.startsWith(q)) prefix.push(p);
        else if (n.includes(q)) sub.push(p);
      }
      return prefix.concat(sub).slice(0, 8);
    },
    get showCreate() {
      if (!this.query) return null;
      const exact = this.persons.find((p) => (p.name || '').toLowerCase() === this.query);
      return exact ? null : this.value.trim();
    },
    get activeMatch() {
      if (this.activeIndex < 0) return null;
      return this.matches[this.activeIndex] || null;
    },
    get canSubmit() {
      return this.value.trim().length > 0;
    },
    onInput(ev) {
      this.value = ev.target.value;
      this.open = true;
      this.activeIndex = this.matches.length > 0 ? 0 : -1;
      this.renderList();
    },
    onFocus() {
      this.open = true;
      this.activeIndex = this.matches.length > 0 ? 0 : -1;
      this.renderList();
    },
    onBlur() {
      setTimeout(() => { this.open = false; this.renderList(); }, 120);
    },
    pickMatch(p) {
      if (!p) return;
      this.value = p.name || '';
      this.open = false;
      this.activeIndex = -1;
      this.renderList();
    },
    pickCreate() {
      this.open = false;
      this.renderList();
    },
    onKey(ev) {
      if (!this.open && ev.key.length === 1) this.open = true;
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        if (!this.open) this.open = true;
        const max = this.matches.length - 1;
        this.activeIndex = Math.min(max, this.activeIndex + 1);
        this.renderList();
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        const max = this.matches.length - 1;
        this.activeIndex = Math.max(0, this.activeIndex - 1);
        this.renderList();
      } else if (ev.key === 'Enter') {
        if (this.open && this.activeIndex >= 0 && this.matches[this.activeIndex]) {
          ev.preventDefault();
          this.pickMatch(this.matches[this.activeIndex]);
        }
      } else if (ev.key === 'Escape') {
        if (this.open) { ev.preventDefault(); this.open = false; this.renderList(); }
      } else if (ev.key === 'Tab' && this.open && this.activeIndex >= 0) {
        this.pickMatch(this.matches[this.activeIndex]);
      }
    },
    highlight(name) {
      const q = this.query;
      const n = name || '';
      if (!q) return escapeHtml(n);
      const idx = n.toLowerCase().indexOf(q);
      if (idx < 0) return escapeHtml(n);
      return (
        escapeHtml(n.slice(0, idx)) +
        '<span class="suggest-match">' + escapeHtml(n.slice(idx, idx + q.length)) + '</span>' +
        escapeHtml(n.slice(idx + q.length))
      );
    },
    renderList() {
      const token = ++this._renderToken;
      const list = this.$el.querySelector('.suggest-list');
      if (!list) return;
      if (!this.open) {
        list.innerHTML = '';
        list.style.display = 'none';
        return;
      }
      const matches = this.matches;
      const create = this.showCreate;
      const parts = [];
      for (let i = 0; i < matches.length; i++) {
        const p = matches[i];
        const faceCount = (p.face_count != null) ? p.face_count : null;
        const tag = faceCount != null
          ? ` <span class="suggest-tag">${faceCount} face${faceCount === 1 ? '' : 's'}</span>`
          : '';
        const cls = 'suggest-item' + (this.activeIndex === i ? ' active' : '');
        parts.push(
          `<li class="${cls}" data-action="pick" data-idx="${i}">` +
            `<span>${this.highlight(p.name || '')}</span>${tag}` +
          `</li>`
        );
      }
      if (create) {
        const idx = matches.length;
        const cls = 'suggest-item' + (this.activeIndex === idx ? ' active' : '');
        parts.push(
          `<li class="${cls}" data-action="create">` +
            `<span><span class="suggest-match">${escapeHtml(create)}</span></span>` +
            `<span class="suggest-tag new">create new</span>` +
          `</li>`
        );
      }
      if (matches.length === 0 && !create) {
        parts.push(
          `<li class="suggest-empty">No matching people yet — typing a new name will create one.</li>`
        );
      }
      const self = this;
      list.innerHTML = parts.join('');
      list.style.display = 'block';
      list.onmousedown = function (ev) {
        if (token !== self._renderToken) return;
        const li = ev.target.closest('li.suggest-item');
        if (!li) return;
        ev.preventDefault();
        const action = li.getAttribute('data-action');
        const idx = parseInt(li.getAttribute('data-idx') || '-1', 10);
        if (action === 'pick' && idx >= 0) {
          self.pickMatch(matches[idx]);
        } else if (action === 'create') {
          self.pickCreate();
        }
      };
      list.onmouseover = function (ev) {
        if (token !== self._renderToken) return;
        const li = ev.target.closest('li.suggest-item');
        if (!li) return;
        const idx = parseInt(li.getAttribute('data-idx') || '-1', 10);
        if (idx >= 0) self.activeIndex = idx;
        else if (li.getAttribute('data-action') === 'create') self.activeIndex = matches.length;
        self.renderList();
      };
    },
  };
};

// ---- bulkAssign: shared by Identify and Inbox pages. -----
//
// One source of truth for the "tick crops, then assign to name" UI.
// Templates include it via `x-data="bulkAssign()"` and supply the
// initial `persons` list via `data-suggest-list` (consumed by
// `nameSuggest`).
//
// All state lives in the closure created by `bulkAssign()`. The
// `init()` method installs document-level listeners, and `destroy()`
// removes them and resets reactive state. Alpine calls `destroy()`
// when the host element is removed by `Alpine.destroyTree`, which
// is invoked from `htmx:beforeSwap` in app.js for the Identify
// result card.
window.bulkAssign = function bulkAssign() {
  return {
    selected: [],
    nameInput: '',
    persons: [],
    _listeners: [],
    _timeouts: [],
    _toggle(id, on) {
      const i = this.selected.indexOf(id);
      if (on && i === -1) this.selected.push(id);
      if (!on && i !== -1) this.selected.splice(i, 1);
    },
    init() {
      const root = this.$el;
      const raw = root.getAttribute('data-suggest-list');
      if (raw) {
        try {
          const arr = JSON.parse(raw) || [];
          this.persons = arr.map((p) => ({
            id: p.id,
            name: p.name,
            face_count: p.face_count,
            nameLower: (p.name || '').toLowerCase(),
          }));
        } catch (_) { this.persons = []; }
      }
      const onChange = (e) => {
        if (e.target.matches('.crop-select')) {
          this._toggle(e.target.dataset.crop, e.target.checked);
        } else if (e.target.matches('.select-all')) {
          const checks = document.querySelectorAll('.crop-select');
          checks.forEach((c) => {
            c.checked = e.target.checked;
            this._toggle(c.dataset.crop, e.target.checked);
          });
        }
      };
      document.addEventListener('change', onChange);
      this._listeners.push([document, 'change', onChange]);

      const onAfterSwap = (e) => {
        if (e.target.id !== 'inbox-gallery') return;
        const stillThere = [];
        document.querySelectorAll('#inbox-gallery .crop-select').forEach((c) => {
          if (c.checked) stillThere.push(c.dataset.crop);
        });
        this.selected = stillThere;
      };
      document.body.addEventListener('htmx:afterSwap', onAfterSwap);
      this._listeners.push([document.body, 'htmx:afterSwap', onAfterSwap]);

      const onAfterRequest = (e) => {
        const form = this.$el.closest('form');
        if (!form || !form.contains(e.target)) return;
        if (e.detail.successful !== true) return;
        try { document.body.dispatchEvent(new Event('inbox.bulk_changed')); } catch (_) {}
        const xhr = e.detail.xhr;
        if (!xhr) return;
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) { return; }
        if (!data || !data.person || !data.person.id) return;
        const person = {
          id: data.person.id,
          name: data.person.name,
          nameLower: (data.person.name || '').toLowerCase(),
        };
        const next = (this.persons || []).filter((p) => p.id !== person.id);
        next.push(person);
        this.persons = next;
        this.nameInput = person.name;
        this.selected = [];
        const toRemove = Array.from(document.querySelectorAll('.crop-select'))
          .filter((cb) => cb.checked)
          .map((cb) => cb.closest('.crop'))
          .filter(Boolean);
        toRemove.forEach((lbl) => {
          lbl.style.transition = 'opacity .3s, transform .3s';
          lbl.style.opacity = '0.4';
          lbl.style.transform = 'scale(0.98)';
        });
        const t = setTimeout(() => {
          toRemove.forEach((lbl) => { try { lbl.remove(); } catch (_) {} });
          const card = document.getElementById('identify-unknown-card');
          if (card) {
            const remaining = card.querySelectorAll('.crop').length;
            const heading = card.querySelector('h3');
            if (heading) {
              const span = heading.querySelector('span');
              if (span) span.textContent = String(remaining);
              else heading.textContent = 'Unknown (' + remaining + ')';
            }
            if (remaining === 0) {
              card.style.transition = 'opacity .3s';
              card.style.opacity = '0';
              setTimeout(() => { try { card.remove(); } catch (_) {} }, 350);
            }
          }
          try {
            if (typeof window.__mnemosRerunIdentify === 'function') {
              window.__mnemosRerunIdentify();
            }
          } catch (_) { /* ignore */ }
        }, 400);
        this._timeouts.push(t);
      };
      document.body.addEventListener('htmx:afterRequest', onAfterRequest);
      this._listeners.push([document.body, 'htmx:afterRequest', onAfterRequest]);
    },
    destroy() {
      for (const entry of this._listeners) {
        const t = entry && entry[0];
        const ev = entry && entry[1];
        const fn = entry && entry[2];
        if (t && typeof t.removeEventListener === 'function' && ev && fn) {
          try { t.removeEventListener(ev, fn); } catch (_) { /* ignore */ }
        }
      }
      this._listeners = [];
      for (const t of this._timeouts) {
        try { clearTimeout(t); } catch (_) { /* ignore */ }
      }
      this._timeouts = [];
      this.selected = [];
      this.nameInput = '';
      const lists = this.$el.querySelectorAll('.suggest-list');
      lists.forEach((l) => { l.innerHTML = ''; l.style.display = 'none'; });
    },
    get selectedCount() { return this.selected.length; },
    get cropIdsJson() { return JSON.stringify(this.selected); },
    get matchedPerson() {
      const q = this.nameInput.trim().toLowerCase();
      if (!q) return null;
      return this.persons.find((p) => p.nameLower === q) || null;
    },
    get canSubmit() {
      return this.selectedCount > 0 && this.nameInput.trim().length > 0;
    },
    get submitLabel() {
      const n = this.selectedCount;
      if (n === 0) return 'Select faces to assign';
      const name = this.nameInput.trim();
      if (!name) return 'Assign ' + n + ' face(s)';
      const matched = this.matchedPerson;
      if (matched) return 'Assign ' + n + ' to ' + matched.name;
      return 'Assign ' + n + ' to new "' + name + '"';
    },
  };
};

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
