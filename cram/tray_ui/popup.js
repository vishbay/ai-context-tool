/* popup.js — cram-ai tray popup logic */

const app        = document.getElementById('app');
const badge      = document.getElementById('badge');
const output     = document.getElementById('output');
const outputWrap = document.getElementById('output-wrap');

// Window size constants
const HEIGHT_COMPACT = 52;
const WIDTH_DEFAULT  = 320;
const WIDTH_MIN      = 280;
const WIDTH_MAX      = 800;

let _currentWidth = WIDTH_DEFAULT;

// Model pricing — base input $/MTok; write=1.25×, read=0.10× for all models
const MODEL_PRICING = {
  haiku45:  { label: 'Haiku 4.5',  base: 1.0 },
  sonnet46: { label: 'Sonnet 4.6', base: 3.0 },
  opus4:    { label: 'Opus 4',     base: 5.0 },
};

let _selectedModel = localStorage.getItem('selectedModel') || 'sonnet46';
let _rawMetrics    = null;

// ── state helpers ─────────────────────────────────────────

function setState(state) {
  const compact = app.classList.contains('compact');
  app.className = `state-${state}${compact ? ' compact' : ''}`;
}

function setBadge(text) {
  badge.textContent = text;
}

function setHint(text, style = '') {
  const bar = document.getElementById('hint-bar');
  bar.textContent = text;
  bar.className = 'hint-bar collapsible' + (style ? ` hint-${style}` : '');
}

function updateHint(state, hasRecentTask) {
  if (state === 'not-init') {
    setHint('Run cram init to set up this repo');
  } else if (state === 'stale') {
    setHint('ARCHITECTURE.md is outdated — hit Sync before your next session', 'warn');
  } else if (hasRecentTask) {
    setHint('Open your AI tool — context is pre-loaded', 'ready');
  } else {
    setHint('Set your task above, then open your AI tool');
  }
}

const _MAX_LOG_LINES = 12;

function showOutput(text, isError = false) {
  const trimmed = text.trim();
  if (!trimmed) return;

  const now = new Date();
  const ts  = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

  // Build line elements
  trimmed.split('\n').forEach((line, i) => {
    if (!line.trim()) return;
    const span  = document.createElement('span');
    span.className = 'log-line' + (isError ? ' err' : '');
    if (i === 0) {
      const tsEl = document.createElement('span');
      tsEl.className   = 'log-ts';
      tsEl.textContent = ts;
      span.appendChild(tsEl);
    }
    span.appendChild(document.createTextNode(line));
    output.appendChild(span);
  });

  // Trim to max lines
  const lines = output.querySelectorAll('.log-line');
  if (lines.length > _MAX_LOG_LINES) {
    Array.from(lines).slice(0, lines.length - _MAX_LOG_LINES).forEach(el => el.remove());
  }

  outputWrap.classList.remove('hidden');
  output.scrollTop = output.scrollHeight;
}

function cramCopyLog() {
  const text = Array.from(output.querySelectorAll('.log-line'))
    .map(el => el.textContent)
    .join('\n');
  navigator.clipboard.writeText(text).catch(() => {
    // Fallback: select all text in the output div
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(output);
    sel.removeAllRanges();
    sel.addRange(range);
  });
}

function setLoading(btn, loading) {
  if (btn) {
    btn.disabled    = loading;
    btn.textContent = loading
      ? (btn.dataset.loadingText || '…')
      : (btn.dataset.idleText    || btn.textContent);
  }
}

// ── window size helpers ───────────────────────────────────

function _resizeTo(h, w) {
  if (w !== undefined) _currentWidth = Math.max(WIDTH_MIN, Math.min(WIDTH_MAX, w));
  if (window.pywebview?.api?.set_size) {
    window.pywebview.api.set_size(Math.max(HEIGHT_COMPACT, h), _currentWidth);
  }
}

let _autoHeightTimer = null;
function _autoHeight() {
  if (app.classList.contains('compact')) return;
  clearTimeout(_autoHeightTimer);
  _autoHeightTimer = setTimeout(() => {
    const h = Math.round(app.getBoundingClientRect().height) + 1;
    _resizeTo(h);
  }, 50);
}

// ── minimize / expand ─────────────────────────────────────

function cramMinimize() {
  app.classList.add('compact');
  _resizeTo(HEIGHT_COMPACT);
}

function cramExpand() {
  app.classList.remove('compact');
  _autoHeight();
}

function cramExpandIfCompact() {
  if (app.classList.contains('compact')) cramExpand();
}

function toggleCompact() {
  if (app.classList.contains('compact')) cramExpand();
  else cramMinimize();
}

// ── help panel ────────────────────────────────────────────

async function toggleHelp() {
  if (app.classList.contains('compact')) {
    cramExpand();
    return;
  }
  const panel  = document.getElementById('help-panel');
  const isOpen = !panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  _autoHeight();
  if (!isOpen) {
    // Sync the auto-suggest toggle with persisted setting
    try {
      const res = await fetch('/settings');
      const s   = await res.json();
      const tog = document.getElementById('auto-suggest-toggle');
      if (tog) tog.checked = s.auto_suggest !== false;
    } catch {}
  }
}

// ── repo selector ─────────────────────────────────────────

async function fetchRepo() {
  try {
    const res  = await fetch('/repo');
    const data = await res.json();
    document.getElementById('repo-name').textContent = data.name || '—';
    if (data.default_target) {
      document.getElementById('target-select').value = data.default_target;
    }
  } catch {
    document.getElementById('repo-name').textContent = '—';
  }
}

async function loadRecentRepos() {
  try {
    const res   = await fetch('/recent-repos');
    const repos = await res.json();
    const list  = document.getElementById('recent-repos-list');
    list.innerHTML = '';
    repos.forEach(r => {
      const btn = document.createElement('button');
      btn.className = 'repo-item' + (r.active ? ' active' : '');
      btn.innerHTML = `<span class="repo-item-name">${r.name}</span>`;
      btn.title = r.path;
      btn.onclick = () => setRepo(r.path);
      list.appendChild(btn);
    });
  } catch { /* ignore */ }
}

function toggleRepoDropdown() {
  const bar      = document.getElementById('repo-bar');
  const dropdown = document.getElementById('repo-dropdown');
  const isOpen   = !dropdown.classList.contains('hidden');

  if (isOpen) {
    dropdown.classList.add('hidden');
    bar.classList.remove('open');
    _autoHeight();
  } else {
    loadRecentRepos();
    dropdown.classList.remove('hidden');
    bar.classList.add('open');
    _autoHeight();
  }
}

async function setRepo(path) {
  // Close dropdown
  document.getElementById('repo-dropdown').classList.add('hidden');
  document.getElementById('repo-bar').classList.remove('open');

  try {
    const res  = await fetch('/set-repo', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ path }),
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById('repo-name').textContent = data.name;
      _hasRecentTask = false;
      await refresh();
    } else {
      showOutput(data.error || 'Could not switch repo.', true);
    }
  } catch (e) {
    showOutput(String(e), true);
  }
}

async function cramBrowseRepo() {
  // Close dropdown first
  document.getElementById('repo-dropdown').classList.add('hidden');
  document.getElementById('repo-bar').classList.remove('open');
  _autoHeight();

  if (window.pywebview?.api?.browse_repo) {
    const path = await window.pywebview.api.browse_repo();
    if (path) await setRepo(path);
  }
}

// ── data fetching ─────────────────────────────────────────

// Shared state for hint coordination
let _lastState = 'loading';
let _hasRecentTask = false;

// Auto-suggest state
let _suggestionDismissed = false;
let _currentSuggestion   = '';

async function fetchStatus() {
  try {
    const res  = await fetch('/status');
    const data = await res.json();

    if (data.branch_alert) {
      showBranchAlert(data.branch_alert);
      _suggestionDismissed = false;  // new branch = fresh suggestion
    } else {
      hideBranchAlert();
    }

    if (data.state === 'not-init') {
      _lastState = 'not-init';
      setState('not-init');
      setBadge('not init');
      return;
    }

    _lastState = data.state;
    const band = data.staleness_band;
    if (band) {
      setState(band);
      const score = data.staleness_score;
      setBadge(band === 'fresh' ? 'fresh' : `${band} ${score}/10`);
    } else {
      setState(data.state);
      if (data.state === 'stale') {
        const archAge = data.files?.['ARCHITECTURE.md']?.age_label ?? '';
        setBadge(archAge ? `${archAge} stale` : 'stale');
      } else {
        setBadge('fresh');
      }
    }
  } catch {
    _lastState = 'loading';
    setState('loading');
    setBadge('…');
  }
}

function showBranchAlert(branch) {
  const el = document.getElementById('branch-alert');
  document.getElementById('branch-alert-text').textContent =
    `⎇ Switched to ${branch} — set your task`;
  el.classList.remove('hidden');
  document.getElementById('task-input')?.focus();
}

function hideBranchAlert() {
  document.getElementById('branch-alert').classList.add('hidden');
}

async function dismissBranchAlert() {
  hideBranchAlert();
  fetch('/dismiss-branch-alert', { method: 'POST' }).catch(() => {});
}

function _formatCost(val) {
  if (val < 0.01) return '<$0.01';
  return `~$${val.toFixed(2)}`;
}

function _formatTok(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000)      return `${Math.round(n / 1000)}k`;
  return String(n);
}

function _applyModelPricing() {
  if (!_rawMetrics) return;
  const ratio  = MODEL_PRICING[_selectedModel].base / MODEL_PRICING.sonnet46.base;
  const nocram = _rawMetrics.nocram_daily * ratio;
  const cram   = _rawMetrics.cram_daily   * ratio;
  const saving = Math.max(0, nocram - cram);

  document.getElementById('cost-saved').textContent   = _formatCost(saving);
  document.getElementById('nocram-daily').textContent = _formatCost(nocram);
  document.getElementById('cram-daily').textContent   = _formatCost(cram);

  const repoTok    = _formatTok(_rawMetrics.repo_tokens || 0);
  const orientFil  = _rawMetrics.orient_files || 8;
  const modelLabel = MODEL_PRICING[_selectedModel].label;
  document.getElementById('daily-est-line').textContent =
    `repo: ~${repoTok} tok · 4 sessions × 4 tasks/day · ~${orientFil} files to orient · ${modelLabel}`;

  if (_rawMetrics.savings_pct !== undefined) {
    const layerPct = 100 - _rawMetrics.savings_pct;
    document.getElementById('size-caption').textContent =
      `frozen layer is ${layerPct}% the size of the repo`;
  }
}

function onModelChange() {
  const sel = document.getElementById('model-select');
  _selectedModel = sel.value;
  localStorage.setItem('selectedModel', _selectedModel);
  _applyModelPricing();
}

async function fetchMetrics() {
  try {
    const res  = await fetch('/metrics');
    const data = await res.json();

    if (!data.initialized) {
      document.getElementById('savings-pct').textContent = '—';
      document.getElementById('cost-saved').textContent  = '—';
      document.getElementById('cram-tokens').textContent = '—';
      document.getElementById('last-task-line').textContent = '';
      _hasRecentTask = false;
      return;
    }

    document.getElementById('savings-pct').textContent =
      `${data.savings_pct}%`;

    _rawMetrics = data;
    _applyModelPricing();

    const parts = [];
    if (data.last_task_age) parts.push(`task: ${data.last_task_age} ago`);
    if (data.last_sync_age) parts.push(`sync: ${data.last_sync_age} ago`);
    document.getElementById('last-task-line').textContent = parts.join(' · ');

    const budgetEl = document.getElementById('budget-warnings');
    if (budgetEl && data.files) {
      const warnings = [];
      for (const [fname, info] of Object.entries(data.files)) {
        if (info.budget_status === 'over' || info.budget_status === 'near') {
          const label = info.budget_status === 'over' ? 'over budget' : 'near budget';
          warnings.push(`⚠ ${fname} ${info.tokens}/${info.budget} tok ${label}`);
        }
      }
      if (warnings.length > 0) {
        budgetEl.textContent = warnings.join(' · ');
        budgetEl.classList.remove('hidden');
      } else {
        budgetEl.classList.add('hidden');
      }
    }

    // "recent" = task set within the last hour
    _hasRecentTask = !!(data.last_task_age &&
      !data.last_task_age.includes('d') &&
      !(data.last_task_age.endsWith('h') && parseInt(data.last_task_age) > 1));
  } catch {
    // silently ignore metrics errors
  }
}

async function fetchMeasured() {
  try {
    const res  = await fetch('/measured');
    const data = await res.json();
    const panel = document.getElementById('measured-panel');
    if (!panel) return;
    if (!data.available) {
      panel.style.display = 'none';
      return;
    }
    panel.style.display = '';
    document.getElementById('measured-writes').textContent = _formatTok(data.writes || 0);
    document.getElementById('measured-reads').textContent  = _formatTok(data.reads  || 0);
    document.getElementById('measured-cost').textContent   = _formatCost(data.est_cost || 0);
    document.getElementById('measured-sessions-line').textContent =
      `${data.sessions} session${data.sessions !== 1 ? 's' : ''} · last ${data.days}d · Sonnet 4.6 est.`;
    _autoHeight();
  } catch {
    // silently ignore
  }
}

async function refresh() {
  await Promise.all([fetchStatus(), fetchMetrics(), fetchRepo()]);
  updateHint(_lastState, _hasRecentTask);
  fetchSuggestion();
  fetchMeasured();
}

// ── SSE stream reader ─────────────────────────────────────

async function _readStream(url, body, onLine, onDone) {
  const res = await fetch(url, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let   buffer  = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      let payload;
      try { payload = JSON.parse(part.slice(6)); } catch { continue; }
      if (payload.line !== undefined) onLine(payload.line);
      if (payload.done)               onDone(payload.success ?? false);
    }
  }
}

// ── actions ───────────────────────────────────────────────

async function cramTask() {
  const description = document.getElementById('task-input').value.trim();
  if (!description) {
    document.getElementById('task-input').focus();
    return;
  }

  const target = document.getElementById('target-select').value;
  const btn    = document.getElementById('cram-btn');
  btn.dataset.idleText    = 'Cram';
  btn.dataset.loadingText = 'Cramming…';
  setLoading(btn, true);

  try {
    await _readStream(
      '/task',
      { description, target },
      line => showOutput(line),
      async success => {
        if (success) {
          document.getElementById('task-input').value = '';
          _hasRecentTask = true;
          await fetchMetrics();
          updateHint(_lastState, _hasRecentTask);
        }
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

async function cramSync() {
  const btn = document.getElementById('sync-btn');
  btn.dataset.idleText    = '↺ Sync';
  btn.dataset.loadingText = '↺ …';
  setLoading(btn, true);

  try {
    await _readStream(
      '/sync',
      {},
      line => showOutput(line),
      async success => {
        if (!success) showOutput('Sync failed.', true);
        else await refresh();
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

async function cramInit() {
  const btn = document.getElementById('init-section').querySelector('button');
  btn.disabled    = true;
  btn.textContent = 'Initialising…';

  try {
    await _readStream(
      '/init',
      {},
      line => showOutput(line),
      async success => {
        if (success) {
          await refresh();
        } else {
          showOutput('Init failed.', true);
          btn.disabled    = false;
          btn.textContent = 'Run cram init';
        }
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    btn.disabled    = false;
    btn.textContent = 'Run cram init';
  }
}

// ── auto-suggest ──────────────────────────────────────────

async function fetchSuggestion() {
  if (_suggestionDismissed) return;
  if (document.getElementById('task-input').value.trim()) return;
  try {
    const res  = await fetch('/suggest');
    const data = await res.json();
    if (data.suggestion) showSuggestion(data.suggestion);
  } catch {}
}

function showSuggestion(text) {
  _currentSuggestion = text;
  document.getElementById('suggest-text').textContent = text;
  document.getElementById('suggest-bar').classList.remove('hidden');
  _autoHeight();
}

function hideSuggestion() {
  _suggestionDismissed = true;
  document.getElementById('suggest-bar').classList.add('hidden');
  _autoHeight();
}

function useSuggestion() {
  if (_currentSuggestion) {
    document.getElementById('task-input').value = _currentSuggestion;
    document.getElementById('task-input').focus();
  }
  hideSuggestion();
}

async function disableSuggestion() {
  hideSuggestion();
  try {
    await fetch('/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ auto_suggest: false }),
    });
    const tog = document.getElementById('auto-suggest-toggle');
    if (tog) tog.checked = false;
  } catch {}
}

async function toggleAutoSuggest(checkbox) {
  const enabled = checkbox.checked;
  try {
    await fetch('/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ auto_suggest: enabled }),
    });
  } catch {}
  if (!enabled) {
    hideSuggestion();
  } else {
    _suggestionDismissed = false;
    fetchSuggestion();
  }
}

async function cramContinue() {
  const btn = document.getElementById('continue-btn');
  btn.dataset.idleText    = '↩';
  btn.dataset.loadingText = '…';
  setLoading(btn, true);

  try {
    await _readStream(
      '/continue',
      {},
      line => showOutput(line),
      async success => {
        if (!success) showOutput('Continue failed.', true);
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

async function cramDecide() {
  const text = document.getElementById('decide-input').value.trim();
  if (!text) {
    document.getElementById('decide-input').focus();
    return;
  }

  const btn = document.getElementById('decide-btn');
  btn.dataset.idleText    = 'Log';
  btn.dataset.loadingText = '…';
  setLoading(btn, true);

  try {
    await _readStream(
      '/decide',
      { decision: text },
      line => showOutput(line),
      async success => {
        if (success) document.getElementById('decide-input').value = '';
        else showOutput('Decide failed.', true);
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

async function cramBenchmark() {
  const btn = document.getElementById('benchmark-btn');
  btn.dataset.idleText    = 'Bench';
  btn.dataset.loadingText = '…';
  setLoading(btn, true);

  try {
    await _readStream(
      '/benchmark',
      {},
      line => showOutput(line),
      async success => {
        if (!success) showOutput('Benchmark failed.', true);
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

async function cramStatus() {
  const btn = document.getElementById('status-run-btn');
  btn.dataset.idleText    = 'Status';
  btn.dataset.loadingText = '…';
  setLoading(btn, true);

  try {
    await _readStream(
      '/status-run',
      {},
      line => showOutput(line),
      async success => {
        if (!success) showOutput('Status failed.', true);
        setLoading(btn, false);
      },
    );
  } catch (e) {
    showOutput(String(e), true);
    setLoading(btn, false);
  }
}

function cramOpenFolder() {
  if (window.pywebview?.api?.open_folder) {
    window.pywebview.api.open_folder();
  } else {
    fetch('/open-folder', { method: 'POST' });
  }
}

function cramClose() {
  if (window.pywebview?.api?.hide) {
    window.pywebview.api.hide();
  }
}

function cramQuit() {
  if (window.pywebview?.api?.quit) {
    window.pywebview.api.quit();
  } else {
    fetch('/quit', { method: 'POST' });
  }
}

// ── boot ──────────────────────────────────────────────────

setState('loading');
setBadge('…');

// Restore saved width and model; auto-size height once pywebview API is ready
window.addEventListener('pywebviewready', () => {
  const saved = parseInt(localStorage.getItem('popupWidth') || '0', 10);
  if (saved >= WIDTH_MIN && saved <= WIDTH_MAX) _currentWidth = saved;

  const sel = document.getElementById('model-select');
  if (sel && MODEL_PRICING[_selectedModel]) sel.value = _selectedModel;

  _autoHeight();
});

// Auto-resize height whenever #app content changes
new ResizeObserver(_autoHeight).observe(app);

// ── left-edge drag to resize width ────────────────────────

(function () {
  const handle = document.getElementById('resize-handle');
  if (!handle) return;

  let drag = null;
  let raf  = null;

  handle.addEventListener('pointerdown', e => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    drag = { startX: e.screenX, startWidth: _currentWidth };
  });

  handle.addEventListener('pointermove', e => {
    if (!drag || raf) return;
    const sx = e.screenX;
    raf = requestAnimationFrame(() => {
      raf = null;
      if (!drag) return;
      const delta  = sx - drag.startX;
      const newW   = Math.max(WIDTH_MIN, Math.min(WIDTH_MAX, drag.startWidth - delta));
      if (newW !== _currentWidth) _resizeTo(window.innerHeight, newW);
    });
  });

  const endDrag = () => {
    drag = null;
    localStorage.setItem('popupWidth', String(_currentWidth));
  };
  handle.addEventListener('pointerup',     endDrag);
  handle.addEventListener('pointercancel', endDrag);
})();

refresh().then(_autoHeight);

setInterval(refresh, 30_000);
