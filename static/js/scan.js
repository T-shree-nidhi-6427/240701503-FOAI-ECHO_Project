/* ECHO - Scan page: upload / camera / demo text -> AI result -> save. */
(function () {
  'use strict';
  const { api, toast, escapeHtml, svg } = window.Echo;
  const $ = id => document.getElementById(id);
  const ALLOWED = ['image/png', 'image/jpeg', 'image/webp'];
  const MAX_BYTES = 10 * 1024 * 1024;
  const CAT_ICON = { warranty: 'shield', food: 'food', document: 'doc', subscription: 'repeat', receipt: 'receipt', medicine: 'pill', other: 'box' };

  const state = { file: null, result: null, imageToken: null, text: '', source: 'image', editing: false, category: null };

  /* ------------------------------------------------------------- tabs */
  const tabs = { image: $('tabImage'), demo: $('tabDemo') };
  function showTab(which) {
    Object.entries(tabs).forEach(([key, tab]) => {
      const selected = key === which;
      tab.setAttribute('aria-selected', String(selected));
      $(tab.getAttribute('aria-controls')).hidden = !selected;
    });
  }
  tabs.image.addEventListener('click', () => showTab('image'));
  tabs.demo.addEventListener('click', () => showTab('demo'));
  document.querySelectorAll('[data-switch-demo]').forEach(b => b.addEventListener('click', () => { showTab('demo'); tabs.demo.focus(); }));

  /* ----------------------------------------------------- file handling */
  const dropzone = $('dropzone');
  function acceptFile(file, name) {
    if (!file) return;
    if (!ALLOWED.includes(file.type)) { toast('Please choose a PNG, JPG, JPEG or WEBP image.', 'error'); return; }
    if (file.size > MAX_BYTES) { toast('That image is larger than 10 MB. Please choose a smaller one.', 'error'); return; }
    state.file = file;
    state.fileName = name || file.name || 'capture.jpg';
    $('previewImg').src = URL.createObjectURL(file);
    $('previewName').textContent = state.fileName;
    $('preview').classList.add('show');
    dropzone.hidden = true;
    stopCamera();
    $('analyzeBtn').focus();
  }
  $('fileInput').addEventListener('change', e => acceptFile(e.target.files[0]));
  ['dragenter', 'dragover'].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.remove('dragover'); }));
  dropzone.addEventListener('drop', e => acceptFile(e.dataTransfer.files[0]));
  $('clearBtn').addEventListener('click', resetImage);

  function resetImage() {
    state.file = null;
    $('fileInput').value = '';
    $('preview').classList.remove('show');
    dropzone.hidden = false;
  }

  /* ------------------------------------------------------------ camera */
  let stream = null;
  $('cameraBtn').addEventListener('click', async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      toast('If camera access is unavailable, upload an image.', 'warn'); return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      $('video').srcObject = stream;
      $('camera').classList.add('show');
      dropzone.hidden = true;
    } catch (err) {
      toast('Camera access was blocked or unavailable. Please upload an image instead.', 'warn');
    }
  });
  function stopCamera() {
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null;
    $('camera').classList.remove('show');
  }
  $('closeCameraBtn').addEventListener('click', () => { stopCamera(); dropzone.hidden = false; });
  $('captureBtn').addEventListener('click', () => {
    const video = $('video'), canvas = $('canvas');
    if (!video.videoWidth) { toast('The camera is still starting. Try again in a moment.', 'warn'); return; }
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    canvas.toBlob(blob => acceptFile(new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' }), 'Camera capture'), 'image/jpeg', 0.92);
  });

  /* --------------------------------------------------------- demo text */
  const demos = JSON.parse($('demoData').textContent);
  document.querySelectorAll('[data-demo]').forEach(chip => chip.addEventListener('click', () => {
    $('demoText').value = demos[chip.dataset.demo].text;
    document.querySelectorAll('[data-demo]').forEach(c => c.setAttribute('aria-pressed', String(c === chip)));
  }));

  /* ------------------------------------------------ processing animation */
  let stepTimer = null;
  function startProcessing() {
    $('howPanel').hidden = true;
    $('processPanel').hidden = false;
    $('previewFrame').classList.add('scanning');
    const steps = Array.from(document.querySelectorAll('.step'));
    steps.forEach(s => s.classList.remove('active', 'done'));
    let i = 0;
    steps[0].classList.add('active');
    stepTimer = setInterval(() => {
      if (i < steps.length - 1) { steps[i].classList.replace('active', 'done'); i++; steps[i].classList.add('active'); }
    }, 380);
  }
  function finishProcessing(success) {
    clearInterval(stepTimer);
    $('previewFrame').classList.remove('scanning');
    document.querySelectorAll('.step').forEach(s => { s.classList.remove('active'); if (success) s.classList.add('done'); });
    if (!success) { $('processPanel').hidden = true; $('howPanel').hidden = false; }
  }
  const pause = ms => new Promise(r => setTimeout(r, ms));

  async function run(request) {
    const buttons = [$('analyzeBtn'), $('analyzeTextBtn')];
    buttons.forEach(b => b && (b.disabled = true));
    startProcessing();
    const started = Date.now();
    const data = await request();
    await pause(Math.max(0, 1400 - (Date.now() - started)));  // short, real, not a fake long wait
    buttons.forEach(b => b && (b.disabled = b.id === 'analyzeBtn' && !window.ECHO_OCR));
    finishProcessing(data.ok);
    if (!data.ok) {
      if (data.code === 'ocr_unavailable') {
        toast('Tesseract OCR is not installed or configured. Try the Demo text tab.', 'warn', 6000);
      }
      return;
    }
    state.imageToken = data.image_token;
    render(data.result);
    toast(state.source === 'image' ? 'Image processed.' : 'Demo text processed.', 'success');
    if (data.result.needs_confirmation.length) setTimeout(() => toast('Please confirm the highlighted information.', 'warn'), 400);
    $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $('analyzeBtn').addEventListener('click', () => {
    if (!state.file) { toast('Please choose an image first.', 'error'); return; }
    state.source = 'image';
    const form = new FormData();
    form.append('image', state.file, state.fileName.replace(/[^\w.\-]/g, '_') || 'capture.jpg');
    run(() => api('/api/scan', { method: 'POST', body: form }));
  });
  $('analyzeTextBtn').addEventListener('click', () => {
    const text = $('demoText').value.trim();
    if (!text) { toast('Paste some sample text or choose a sample first.', 'error'); return; }
    state.source = 'demo_text';
    state.imageToken = null;
    run(() => api('/api/scan', { method: 'POST', body: { text } }));
  });

  /* ------------------------------------------------------------ result */
  function render(r) {
    state.result = r;
    state.text = r.text;
    state.category = r.category;
    setEditing(false);
    $('result').classList.add('show');
    $('resultSource').textContent = r.source === 'image'
      ? 'Read from your image with OCR, then analysed locally.'
      : 'Analysed from demo text input (not from an image).';
    $('sourceBadge').innerHTML = r.source === 'image'
      ? '<span class="badge badge-ocr">Real image OCR</span>' : '<span class="badge badge-demo">Demo text input</span>';

    const icon = $('resCatIcon');
    icon.className = `cat-icon cat-${r.category}`;
    icon.innerHTML = svg(CAT_ICON[r.category] || 'box');
    $('resCategoryLabel').textContent = r.category_label;
    $('resTitle').textContent = r.title;
    $('resTitleInput').value = r.title;
    $('resCategory').textContent = r.category_label;
    $('resCategorySelect').value = r.category;

    const pct = Math.round(r.confidence * 100);
    $('resConfLevel').innerHTML = `<strong>${r.confidence_level}</strong>`;
    $('resConfPct').textContent = `${pct}%`;
    requestAnimationFrame(() => { $('resConfBar').style.width = `${pct}%`; });
    const b = r.confidence_breakdown;
    $('resConfBreakdown').textContent = `Classifier ${Math.round(b.classifier * 100)}% · fields found ${Math.round(b.field_coverage * 100)}% · date certainty ${Math.round(b.date_certainty * 100)}%`;

    $('resDateLabel').textContent = r.date_label;
    if (r.important_date) {
      $('resDate').textContent = r.important_date_display;
      $('resDateMethod').textContent = `${r.relative} · ${r.date_method}`;
    } else {
      $('resDate').textContent = 'Not found yet';
      $('resDateMethod').textContent = 'ECHO needs a little more information (see below).';
    }
    $('resWhy').textContent = r.why_it_matters;
    if (r.reminder) {
      $('resReminder').textContent = `${r.reminder.days_before} days before · ${r.reminder.reminder_date_display}` + (r.reminder.note ? ` (${r.reminder.note})` : '');
      $('resDaysBefore').value = r.reminder.days_before;
    } else {
      $('resReminder').textContent = r.important_date ? 'No reminder: this date has already passed.' : 'No reminder until a reliable date is known.';
      $('resDaysBefore').value = '';
    }

    const fields = Object.entries(r.extracted_fields || {});
    $('resFields').innerHTML = fields.length
      ? fields.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('')
      : '<dt>Details</dt><dd class="muted">No extra details were found.</dd>';
    $('resExplain').innerHTML = r.explanation.map(line => `<li>${escapeHtml(line)}</li>`).join('');
    $('rawSummary').textContent = r.source === 'image' ? 'Show the text ECHO read from the image' : 'Show the demo text';
    $('resText').textContent = r.text;

    const missing = r.needs_confirmation || [];
    $('confirmBox').hidden = !missing.length;
    $('confirmFields').innerHTML = missing.map(m => `
      <label class="field" for="cf-${m.key}">${escapeHtml(m.label)}
        <input class="input" id="cf-${m.key}" data-key="${m.key}" type="${m.type === 'date' ? 'date' : 'number'}" ${m.type === 'number' ? 'min="0" step="any"' : ''}>
        <span class="muted" style="font-size:12px">${escapeHtml(m.hint)}</span>
      </label>`).join('');
  }

  function setEditing(on) {
    state.editing = on;
    $('resTitle').hidden = on; $('resTitleInput').hidden = !on;
    $('resCategory').hidden = on; $('resCategorySelect').hidden = !on;
    $('resReminder').hidden = on && !!(state.result && state.result.reminder);
    $('resReminderEdit').hidden = !(on && state.result && state.result.reminder);
    $('editBtn').innerHTML = on ? `${svg('check')}Done editing` : `${svg('edit')}Edit`;
  }

  $('editBtn').addEventListener('click', async () => {
    if (!state.editing) { setEditing(true); $('resTitleInput').focus(); return; }
    const title = $('resTitleInput').value.trim();
    const category = $('resCategorySelect').value;
    if (category !== state.result.category) {
      await recompute({ title }, category);
    } else {
      state.result.title = title || state.result.title;
      $('resTitle').textContent = state.result.title;
      const d = parseInt($('resDaysBefore').value, 10);
      if (state.result.reminder && !Number.isNaN(d)) {
        state.result.reminder.days_before = d;
        $('resReminder').textContent = `${d} days before (you changed this)`;
      }
      setEditing(false);
    }
  });

  async function recompute(extra = {}, category = null) {
    const overrides = { ...extra };
    document.querySelectorAll('#confirmFields [data-key]').forEach(i => { if (i.value) overrides[i.dataset.key] = i.value; });
    const data = await api('/api/recompute', { method: 'POST', body: {
      text: state.text, source: state.source, category: category || state.category, overrides } });
    if (data.ok) { render(data.result); toast(data.result.important_date ? 'Updated with your information.' : 'Still missing something - please check the fields.', data.result.important_date ? 'success' : 'warn'); }
  }
  $('recalcBtn').addEventListener('click', () => {
    const filled = Array.from(document.querySelectorAll('#confirmFields [data-key]')).some(i => i.value);
    if (!filled) { toast('Fill in at least one highlighted field first.', 'warn'); return; }
    recompute({ title: state.result.title });
  });

  $('saveBtn').addEventListener('click', async () => {
    const r = state.result;
    if (!r) return;
    if (state.editing) { $('editBtn').click(); }
    const days = r.reminder ? r.reminder.days_before : null;
    $('saveBtn').disabled = true;
    const data = await api('/api/save-memory', { method: 'POST', body: {
      title: state.editing ? $('resTitleInput').value : r.title, category: r.category,
      important_date: r.important_date, date_type: r.date_type, date_method: r.date_method,
      confidence: r.confidence, extracted_fields: r.extracted_fields, explanation: r.explanation,
      text: r.text, source: r.source, image_token: state.imageToken, days_before: days,
    } });
    $('saveBtn').disabled = false;
    if (!data.ok) return;
    toast('Memory saved successfully.');
    if (data.reminder_created) setTimeout(() => toast('Reminder created.'), 350);
    setTimeout(() => { location.href = data.url; }, 1100);
  });

  $('discardBtn').addEventListener('click', async () => {
    if (state.imageToken) await api('/api/discard', { method: 'POST', body: { image_token: state.imageToken } }, { quiet: true });
    state.result = null; state.imageToken = null;
    $('result').classList.remove('show');
    $('processPanel').hidden = true; $('howPanel').hidden = false;
    resetImage();
    toast('Discarded. Nothing was saved.', 'info');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
})();
