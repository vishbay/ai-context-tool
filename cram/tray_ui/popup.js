/* popup.js — cram-ai tray popup logic */

const app        = document.getElementById('app');
const badge      = document.getElementById('badge');
const output     = document.getElementById('output');
const outputWrap = document.getElementById('output-wrap');

// Heights used when resizing via pywebview API
const HEIGHT_FULL    = 492;
const HEIGHT_COMPACT = 48;
const HEIGHT_HELP    = 632;

// ── state helpers ─────────────────────────────────────────

function setState(state) {
  const compact = app.classList.contains('compact');
  app.className = `state-${state}${compact ? ' compact' : ''}`;
}

function setBadge(text) {
  badge.textContent = `● ${text}`;
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

const _MAX_LOG_LINES = 6;

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

function _currentTargetHeight() {
  const helpOpen = !document.getElementById('help-panel').classList.contains('hidden');
  return helpOpen ? HEIGHT_HELP : HEIGHT_FULL;
}

function _resizeTo(h) {
  if (window.pywebview?.api?.set_size) {
    window.pywebview.api.set_size(h);
  }
}

// ── minimize / expand ─────────────────────────────────────

function cramMinimize() {
  app.classList.add('compact');
  _resizeTo(HEIGHT_COMPACT);
}

function cramExpand() {
  app.classList.remove('compact');
  _resizeTo(_currentTargetHeight());
}

function cramExpandIfCompact() {
  if (app.classList.contains('compact')) cramExpand();
}

// ── help panel ────────────────────────────────────────────

function toggleHelp() {
  if (app.classList.contains('compact')) {
    cramExpand();
    return;
  }
  const panel  = document.getElementById('help-panel');
  const isOpen = !panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  _resizeTo(isOpen ? HEIGHT_FULL : HEIGHT_HELP);
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
    _resizeTo(_currentTargetHeight());
  } else {
    loadRecentRepos();
    dropdown.classList.remove('hidden');
    bar.classList.add('open');
    _resizeTo(_currentTargetHeight() + 160);
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
  _resizeTo(_currentTargetHeight());

  if (window.pywebview?.api?.browse_repo) {
    const path = await window.pywebview.api.browse_repo();
    if (path) await setRepo(path);
  }
}

// ── data fetching ─────────────────────────────────────────

// Shared state for hint coordination
let _lastState = 'loading';
let _hasRecentTask = false;

async function fetchStatus() {
  try {
    const res  = await fetch('/status');
    const data = await res.json();

    if (data.state === 'not-init') {
      _lastState = 'not-init';
      setState('not-init');
      setBadge('not init');
      return;
    }

    _lastState = data.state;
    setState(data.state);
    if (data.state === 'stale') {
      const archAge = data.files?.['ARCHITECTURE.md']?.age_label ?? '';
      setBadge(archAge ? `${archAge} stale` : 'stale');
    } else {
      setBadge('fresh');
    }
  } catch {
    _lastState = 'loading';
    setState('loading');
    setBadge('…');
  }
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

    document.getElementById('cost-saved').textContent =
      `$${data.cost_saved.toFixed(3)}`;

    document.getElementById('cram-tokens').textContent =
      data.cram_tokens >= 1000
        ? `${(data.cram_tokens / 1000).toFixed(1)}k`
        : String(data.cram_tokens);

    const parts = [];
    if (data.last_task_age) parts.push(`task: ${data.last_task_age} ago`);
    if (data.last_sync_age) parts.push(`sync: ${data.last_sync_age} ago`);
    document.getElementById('last-task-line').textContent = parts.join(' · ');

    // "recent" = task set within the last hour
    _hasRecentTask = !!(data.last_task_age &&
      !data.last_task_age.includes('d') &&
      !(data.last_task_age.endsWith('h') && parseInt(data.last_task_age) > 1));
  } catch {
    // silently ignore metrics errors
  }
}

async function refresh() {
  await Promise.all([fetchStatus(), fetchMetrics(), fetchRepo()]);
  updateHint(_lastState, _hasRecentTask);
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
  btn.dataset.idleText    = 'Cram it';
  btn.dataset.loadingText = 'Cramming…';
  setLoading(btn, true);

  try {
    const res  = await fetch('/task', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ description, target }),
    });
    const data = await res.json();

    if (data.success) {
      document.getElementById('task-input').value = '';
      showOutput(data.output || 'Done.');
      _hasRecentTask = true;
      await fetchMetrics();
      updateHint(_lastState, _hasRecentTask);
    } else {
      showOutput(data.error || 'Failed.', true);
    }
  } catch (e) {
    showOutput(String(e), true);
  } finally {
    setLoading(btn, false);
  }
}

async function cramSync() {
  const btn = document.getElementById('sync-btn');
  btn.dataset.idleText    = '↺ Sync';
  btn.dataset.loadingText = '↺ Syncing…';
  setLoading(btn, true);

  try {
    const res  = await fetch('/sync', { method: 'POST' });
    const data = await res.json();
    showOutput(
      data.success ? 'ARCHITECTURE.md updated.' : (data.error || 'Sync failed.'),
      !data.success,
    );
    if (data.success) await refresh();
  } catch (e) {
    showOutput(String(e), true);
  } finally {
    setLoading(btn, false);
  }
}

async function cramInit() {
  const btn = document.getElementById('init-section').querySelector('button');
  btn.disabled    = true;
  btn.textContent = 'Initialising…';

  try {
    const res  = await fetch('/init', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showOutput(data.output || 'Done.');
      await refresh();
    } else {
      showOutput(data.error || 'Init failed.', true);
      btn.disabled    = false;
      btn.textContent = 'Run cram init';
    }
  } catch (e) {
    showOutput(String(e), true);
    btn.disabled    = false;
    btn.textContent = 'Run cram init';
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

refresh();

setInterval(refresh, 30_000);
