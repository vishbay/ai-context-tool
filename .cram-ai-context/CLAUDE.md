# Current Task

## Task
Anchor Popup Tray to icon on menu bar. Add light/dark mode toggle. improve visual design and layout.

## Models
- Context loaded by: `Claude Haiku (claude CLI)`
- **Switch to `Claude Opus (claude CLI)` for coding** ←

## Relevant Files

### cram/tray_ui/popup.html
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>cram-ai</title>
  <link rel="stylesheet" href="/static/popup.css" />
</head>
<body>

<div id="app" class="state-loading">

  <!-- Header -->
  <header id="header" onclick="cramExpandIfCompact()">
    <span class="logo">⚡ cram-ai</span>
    <span id="badge" class="badge">●</span>
    <button class="icon-btn help-toggle" onclick="event.stopPropagation(); toggleHelp()" title="Workflow guide">?</button>
    <button class="icon-btn minimize-btn"  onclick="event.stopPropagation(); cramMinimize()" title="Minimise">—</button>
    <button class="icon-btn expand-btn"    onclick="event.stopPropagation(); cramExpand()"   title="Expand">↑</button>
    <button class="icon-btn close-btn"     onclick="event.stopPropagation(); cramClose()"    title="Close">✕</button>
  </header>

  <!-- Branch-switch alert -->
  <div id="branch-alert" class="branch-alert hidden">
    <span id="branch-alert-text"></span>
    <button class="branch-alert-dismiss" onclick="dismissBranchAlert()" title="Dismiss">✕</button>
  </div>

  <!-- Repo selector -->
  <div id="repo-bar" class="repo-bar collapsible">
    <button class="repo-trigger" id="repo-trigger" onclick="toggleRepoDropdown()">
      <span class="repo-icon">⬡</span>
      <span id="repo-name">—</span>
      <span id="repo-arrow" class="repo-arrow">▾</span>
    </button>
    <div id="repo-dropdown" class="repo-dropdown hidden">
      <div id="recent-repos-list"></div>
      <button class="repo-item repo-browse" onclick="cramBrowseRepo()">
        📂 Browse for repo…
      </button>
    </div>
  </div>

  <!-- Contextual next-step hint -->
  <div id="hint-bar" class="hint-bar collapsible"></div>

  <!-- Metrics -->
  <div class="metrics collapsible">
    <div class="metric-row">
      <div class="metric-block">
        <div class="metric-value" id="savings-pct">—</div>
        <div class="metric-label">saved</div>
      </div>
      <div class="metric-divider"></div>
      <div class="metric-block">
        <div class="metric-value" id="cost-saved">—</div>
        <div class="metric-label">per session</div>
      </div>
      <div class="metric-divider"></div>
      <div class="metric-block">
        <div class="metric-value" id="cram-tokens">—</div>
        <div class="metric-label">tokens</div>
      </div>
    </div>
    <div class="metric-sub" id="last-task-line">last task: —</div>
  </div>

  <!-- Task input (shown when init'd) -->
  <div id="task-section" class="collapsible">
    <div class="section-label">What are you building?</div>

    <!-- Auto-suggest bar -->
    <div id="suggest-bar" class="suggest-bar hidden">
      <span id="suggest-text" class="suggest-text"></span>
      <div class="suggest-actions">
        <button class="suggest-use" onclick="useSuggestion()">Use</button>
        <button class="suggest-dismiss" onclick="hideSuggestion()" title="Dismiss">✕</button>
        <button class="suggest-disable" onclick="disableSuggestion()" title="Turn off auto-suggest">off</button>
      </div>
    </div>

... [88 lines omitted]

```

### cram/tray_ui/popup.css
```css
:root {
  --bg:       #0d0b17;
  --surface:  rgba(255,255,255,0.05);
  --surface2: rgba(255,255,255,0.08);
  --border:   rgba(255,255,255,0.09);
  --text:     #f0eeff;
  --muted:    rgba(240,238,255,0.42);
  --cyan:     #00f5d4;
  --green:    #06ffa5;
  --amber:    #f8c537;
  --red:      #ff4d6d;
  --pink:     #f72585;
  --radius:   12px;
  --mono:     'JetBrains Mono', 'Fira Code', monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  width: 280px;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, 'Inter', 'Segoe UI', sans-serif;
  font-size: 13px;
  line-height: 1.5;
  overflow: hidden;
  border-radius: var(--radius);
}

::-webkit-scrollbar { display: none; }

#app {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

/* ── header ──────────────────────────────────────────────── */

header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 11px 10px 10px 14px;
  border-bottom: 1px solid var(--border);
  background: rgba(0,0,0,0.3);
  -webkit-app-region: drag;
  flex-shrink: 0;
}

.logo {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.2px;
  flex: 1;
}

.badge {
  font-size: 11px;
  font-weight: 700;
  font-family: var(--mono);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
  flex-shrink: 0;
}

.state-fresh   .badge { background: rgba(6,255,165,0.12);  border-color: rgba(6,255,165,0.25);  color: var(--green); }
.state-stale   .badge { background: rgba(248,197,55,0.12); border-color: rgba(248,197,55,0.25); color: var(--amber); }
.state-not-init .badge,
.state-loading  .badge { background: rgba(255,77,109,0.12); border-color: rgba(255,77,109,0.25); color: var(--red); }

/* ── branch-switch alert banner ──────────────────────────── */

.branch-alert {
  display: flex;
  align-items: center;
  gap: 6px;

... [670 lines omitted]

```

### cram/tray_ui/popup.js
```js
[lines 1–149 of 644]
/* popup.js — cram-ai tray popup logic */

const app        = document.getElementById('app');
const badge      = document.getElementById('badge');
const output     = document.getElementById('output');
const outputWrap = document.getElementById('output-wrap');

// Heights used when resizing via pywebview API
const HEIGHT_FULL    = 648;
const HEIGHT_COMPACT = 48;
const HEIGHT_HELP    = 788;
const _SUGGEST_H     = 44;  // extra height when suggest bar is visible

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
  ··· 69 lines omitted ···

function _currentTargetHeight() {
  const helpOpen     = !document.getElementById('help-panel').classList.contains('hidden');
  const suggestShown = !document.getElementById('suggest-bar').classList.contains('hidden');
  return (helpOpen ? HEIGHT_HELP : HEIGHT_FULL) + (suggestShown ? _SUGGEST_H : 0);
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

async function toggleHelp() {
  if (app.classList.contains('compact')) {
    cramExpand();
    return;
  }
  const panel  = document.getElementById('help-panel');
  const isOpen = !panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  _resizeTo(_currentTargetHeight());
  if (!isOpen) {
    // Sync the auto-suggest toggle with persisted setting
    try {
      const res = await fetch('/settings');
      const s   = await res.json();
      const tog = document.getElementById('auto-suggest-toggle');
      if (tog) tog.checked = s.auto_suggest !== false;
    } catch {}
  }
  ··· 495 more lines

```
