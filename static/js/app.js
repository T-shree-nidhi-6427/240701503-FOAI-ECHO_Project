/* ECHO - shared front-end helpers: API calls, toasts, modal, navigation, greeting, due reminders. */
(function () {
  'use strict';

  const ICONS = { success: 'check', error: 'alert', warn: 'alert', info: 'info' };

  function svg(name) {
    return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /** Reusable toast notification. type: success | error | warn | info */
  function toast(message, type = 'success', timeout = 3600) {
    const region = document.getElementById('toasts');
    if (!region) return;
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `${svg(ICONS[type] || 'info')}<span>${escapeHtml(message)}</span>`;
    region.appendChild(el);
    setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 260); }, timeout);
  }

  /** fetch wrapper: JSON in/out, friendly errors, never throws. */
  async function api(url, options = {}, config = {}) {
    const opts = { method: options.method || 'GET', headers: {} };
    if (options.body instanceof FormData) {
      opts.body = options.body;
    } else if (options.body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(options.body);
    }
    try {
      const res = await fetch(url, opts);
      let data;
      try { data = await res.json(); } catch (e) { data = { ok: false, error: 'Unexpected response from ECHO.' }; }
      if (!res.ok && data.ok !== false) data.ok = false;
      if (data.ok === false && !config.quiet) toast(data.error || 'Something went wrong.', 'error', 5200);
      return data;
    } catch (err) {
      if (!config.quiet) toast('ECHO is not reachable. Is the server still running?', 'error', 5200);
      return { ok: false, error: 'network' };
    }
  }

  /* ---------------------------------------------------------------- modal */
  const modal = document.getElementById('modal');
  let lastFocus = null;

  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    if (lastFocus) lastFocus.focus();
  }

  /** buttons: [{label, cls, close, action(modalEl) -> Promise<bool>}] */
  function openModal(title, bodyContent, buttons = []) {
    if (!modal) return;
    lastFocus = document.activeElement;
    modal.querySelector('#modalTitle').textContent = title;
    const body = modal.querySelector('#modalBody');
    body.innerHTML = '';
    if (typeof bodyContent === 'string') body.innerHTML = `<p>${escapeHtml(bodyContent)}</p>`;
    else body.appendChild(bodyContent);
    const foot = modal.querySelector('#modalFoot');
    foot.innerHTML = '';
    buttons.forEach(b => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `btn ${b.cls || ''}`;
      btn.textContent = b.label;
      btn.addEventListener('click', async () => {
        if (b.close) return closeModal();
        btn.disabled = true;
        const ok = b.action ? await b.action(modal) : true;
        btn.disabled = false;
        if (ok !== false) closeModal();
      });
      foot.appendChild(btn);
    });
    modal.hidden = false;
    const first = body.querySelector('input, select, textarea') || foot.querySelector('button:last-child');
    if (first) first.focus();
  }

  function confirmDialog(title, text, confirmLabel, onConfirm, danger = false) {
    openModal(title, text, [
      { label: 'Cancel', cls: 'btn-ghost', close: true },
      { label: confirmLabel, cls: danger ? 'btn-danger' : 'btn-primary', action: async () => { await onConfirm(); return true; } },
    ]);
  }

  if (modal) {
    modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('[data-modal-close]')) closeModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });
  }

  /* ------------------------------------------------------- mobile drawer */
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('scrim');
  const menuBtn = document.getElementById('menuBtn');
  function setDrawer(open) {
    if (!sidebar) return;
    sidebar.classList.toggle('open', open);
    scrim.hidden = !open;
    menuBtn && menuBtn.setAttribute('aria-expanded', String(open));
  }
  menuBtn && menuBtn.addEventListener('click', () => setDrawer(!sidebar.classList.contains('open')));
  scrim && scrim.addEventListener('click', () => setDrawer(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') setDrawer(false); });

  /* ------------------------------------------------------------- greeting */
  const greeting = document.getElementById('greeting');
  if (greeting) {
    const h = new Date().getHours();
    const part = h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    const name = document.body.dataset.profileName;
    greeting.textContent = name ? `${part}, ${name}.` : `${part}.`;
  }

  /* ------------------------------------ NOTIFY: due reminders on app open */
  async function checkDueReminders() {
    const inApp = document.body.dataset.notifInapp === 'true';
    const browser = document.body.dataset.notifBrowser === 'true';
    if (!inApp && !browser) return;
    let seen = null;
    try { seen = sessionStorage.getItem('echo-due-checked'); } catch (e) {}
    if (seen) return;
    const data = await api('/api/reminders/due', {}, { quiet: true });
    try { sessionStorage.setItem('echo-due-checked', '1'); } catch (e) {}
    if (!data.ok || !data.due.length) return;
    const first = data.due[0];
    const text = data.due.length === 1 ? first.phrase : `${data.due.length} reminders need attention. ${first.phrase}`;
    if (inApp) toast(text, 'warn', 6500);
    if (browser && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification('ECHO reminder', { body: text, icon: '/static/images/logo.svg' }); } catch (e) {}
    }
  }
  checkDueReminders();

  window.Echo = { api, toast, openModal, closeModal, confirm: confirmDialog, escapeHtml, svg };
})();
