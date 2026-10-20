/* ECHO - Ask ECHO chat interface. */
(function () {
  'use strict';
  const { api, escapeHtml, svg } = window.Echo;
  const chat = document.getElementById('chat');
  const form = document.getElementById('askForm');
  const input = document.getElementById('askInput');
  const CAT_ICON = { warranty: 'shield', food: 'food', document: 'doc', subscription: 'repeat', receipt: 'receipt', medicine: 'pill', other: 'box' };
  const LEVEL = { OVERDUE: 'Overdue', TODAY: 'Today', URGENT: 'Urgent', UPCOMING: 'Upcoming', LATER: 'Later', NONE: 'No date' };
  const logo = '/static/images/logo.svg';

  function add(html, who) {
    const wrap = document.createElement('div');
    wrap.className = `msg ${who === 'user' ? 'msg-user' : ''}`;
    wrap.innerHTML = who === 'user'
      ? `<span class="avatar" aria-hidden="true" style="font-size:13px;font-weight:600;color:var(--muted)">${escapeHtml((document.body.dataset.profileName || 'You').charAt(0).toUpperCase())}</span><div class="bubble"><p class="label">You</p>${html}</div>`
      : `<span class="avatar"><img src="${logo}" alt=""></span><div class="bubble"><p class="label">ECHO</p>${html}</div>`;
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function cardHtml(c) {
    return `<a class="answer-card card-link" href="/memory/${c.id}">
      <span class="cat-icon cat-${c.category}" aria-hidden="true">${svg(CAT_ICON[c.category] || 'box')}</span>
      <span class="answer-card-body">
        <span class="answer-card-title" style="display:block">${escapeHtml(c.title)}</span>
        <span class="answer-card-sub" style="display:block">${escapeHtml(c.phrase ? c.phrase.charAt(0).toUpperCase() + c.phrase.slice(1) : c.category_label)}</span>
        <span class="pill pill-${(c.urgency || 'none').toLowerCase()}" style="margin-top:6px"><span class="dot"></span>${LEVEL[c.urgency] || ''}</span>
        ${c.is_demo ? '<span class="demo-tag" style="margin-left:6px">Demo</span>' : ''}
      </span></a>`;
  }

  async function ask(question) {
    question = (question || '').trim();
    if (!question) { window.Echo.toast('Type a question for ECHO first.', 'warn'); return; }
    add(escapeHtml(question), 'user');
    const pending = add('<span class="typing" aria-label="ECHO is thinking"><span></span><span></span><span></span></span>', 'echo');
    const data = await api('/api/ask', { method: 'POST', body: { question } });
    pending.remove();
    if (!data.ok) { add(escapeHtml(data.error || 'Something went wrong.'), 'echo'); return; }
    let html = `<p>${escapeHtml(data.message)}</p>`;
    if (data.cards && data.cards.length) html += `<div class="answer-cards">${data.cards.map(cardHtml).join('')}</div>`;
    if ((!data.cards || !data.cards.length) && data.suggestions) {
      html += `<div class="chips">${data.suggestions.slice(0, 4).map(s => `<button class="chip" type="button" data-q="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join('')}</div>`;
    }
    add(html, 'echo');
  }

  form.addEventListener('submit', e => { e.preventDefault(); const q = input.value; input.value = ''; ask(q); });
  chat.addEventListener('click', e => { const chip = e.target.closest('[data-q]'); if (chip) ask(chip.dataset.q); });

  const initial = new URLSearchParams(location.search).get('q');
  if (initial) ask(initial);
  else input.focus();
})();
