"""Shareable markdown report for cram audit.

render_report() is a pure function over the collect_audit() aggregate dict —
the same numbers as the terminal report, formatted to travel: paste into a PR,
an issue, or Slack. Headline first, findings second, then the evidence tables.
Every number carries a measured/estimated basis so the report makes no claim
the transcripts can't back.
"""

from __future__ import annotations
import datetime
import os


def _repo_rel(path: str, repo_root: str) -> str:
    repo_sep = repo_root.rstrip(os.sep) + os.sep
    return path[len(repo_sep):] if path.startswith(repo_sep) else path


def render_report(data: dict, repo_root: str) -> str:
    """Return a markdown report for a collect_audit() result."""
    name = os.path.basename(repo_root.rstrip(os.sep)) or repo_root
    total = data['sessions']
    today = datetime.date.today().isoformat()

    lines: list[str] = []
    lines.append(f'# Agent session audit — {name}')
    lines.append('')
    lines.append(f'*Last {data["days"]} days · {total} session'
                 f'{"s" if total != 1 else ""} · generated {today} · '
                 f'{data["provider"]} pricing*')

    # ── Headline ──────────────────────────────────────────────────────────────
    lines.append('')
    lines.append('## Headline')
    lines.append('')
    if data['pre_edit_spend_share'] is not None:
        n_meas = data['pre_edit_measured_sessions']
        prelim = (f'**Preliminary** — only {n_meas} measured edit session'
                  f'{"s" if n_meas != 1 else ""}. '
                  if data.get('pre_edit_preliminary') else '')
        lines.append(f'{prelim}**Pre-edit context share: '
                     f'{data["pre_edit_spend_share"]:.0%}** of '
                     f'{data["pre_edit_eff_total_tokens"]:,.0f} effective input '
                     f'tokens across {n_meas} measured edit session'
                     f'{"s" if n_meas != 1 else ""}. This is descriptive: it says '
                     f'how much context-gathering precedes editing, not that all '
                     f'of it is waste — see Findings for the avoidable patterns.')
        if data['pre_edit_spend_eff_tokens'] is not None:
            lines.append(f'Pre-edit spend: ~{data["pre_edit_spend_eff_tokens"]:,.0f} '
                         f'eff. tokens/session (~${data["pre_edit_spend_cost"]:.4f}).')
    else:
        lines.append('**Pre-edit context share not measurable** — no edit sessions '
                     'with token usage in this window (estimates below).')
    lines.append('')
    seg = (f'{total} total — {data["edit_sessions"]} edit session'
           f'{"s" if data["edit_sessions"] != 1 else ""}')
    if data['pre_edit_measured_sessions']:
        seg += f' ({data["pre_edit_measured_sessions"]} measured)'
    if data['read_only_sessions']:
        seg += (f', {data["read_only_sessions"]} read-only '
                f'(excluded — reading was the job)')
    lines.append(f'Sessions: {seg}.')

    # ── Findings ──────────────────────────────────────────────────────────────
    findings = data.get('findings') or []
    if findings:
        lines.append('')
        lines.append(f'## Findings ({len(findings)})')
        lines.append('')
        for i, fd in enumerate(findings, 1):
            lines.append(f'{i}. **{fd["id"]}** — {fd["evidence"]}')
            lines.append(f'   → {fd["fix"]}')

    # ── Top repeated files ────────────────────────────────────────────────────
    repeated = [t for t in data.get('top_read_files', []) if t[1] > 1]
    if repeated:
        lines.append('')
        lines.append('## Top repeated files')
        lines.append('')
        lines.append('| Reads | Sessions | File |')
        lines.append('|------:|---------:|------|')
        for fp, r, n in repeated[:10]:
            lines.append(f'| {r} | {n} | `{_repo_rel(fp, repo_root)}` |')

    # ── Key metrics ───────────────────────────────────────────────────────────
    lines.append('')
    lines.append('## Key metrics')
    lines.append('')
    lines.append('| Metric | Value | Basis |')
    lines.append('|---|---:|---|')

    def row(label: str, value: str, basis: str) -> None:
        lines.append(f'| {label} | {value} | {basis} |')

    row('Reads before first edit (avg)', f'{data["avg_reads_before_edit"]:.1f}',
        'measured')
    row('Read-to-edit ratio', f'{data["avg_ratio"]:.1f}× ({data["ratio_band"]})',
        'measured')
    if data['avg_cache_writes'] or data['avg_cache_reads']:
        row('Cache writes / session', f'{data["avg_cache_writes"]:,.0f} tok', 'measured')
        row('Cache reads / session', f'{data["avg_cache_reads"]:,.0f} tok', 'measured')
    if data['avg_requests']:
        row('Requests / session', f'{data["avg_requests"]:.0f}', 'measured')
        row('Context / request', f'{data["avg_context_per_request"]:,.0f} tok '
            f'(peak {data["peak_context"]:,})', 'measured')
        if data['avg_context_growth'] is not None:
            row('Context growth (peak/start)', f'{data["avg_context_growth"]:.1f}×',
                'measured')
        if data['bloat_tail_share'] is not None:
            row('Read-cost share, last ⅓ of turns',
                f'{data["bloat_tail_share"]:.0%}', 'measured (33% = flat)')
        if data['sessions_with_big_results']:
            row('Oversized tool results',
                f'{data["sessions_with_big_results"]}/{total} sessions '
                f'(> {data["big_result_bytes"] // 1000} KB)', 'measured')
            row('Carried cost of oversized results',
                f'${data["carried_cost_per_session"]:.4f}/session',
                'measured tokens × price')
    if data['avg_redundant_reads'] >= 0.5:
        row('Redundant same-file reads / session',
            f'{data["avg_redundant_reads"]:.1f}', 'measured')
    if data['avg_error_results'] > 0:
        row('Failed tool calls / session', f'{data["avg_error_results"]:.1f} '
            f'({data["sessions_with_errors"]}/{total} sessions)', 'measured')
    if data['avg_edit_churn'] > 0:
        row('Same-file re-edits / session', f'{data["avg_edit_churn"]:.1f}',
            'measured')
    row('Orientation cost / session',
        f'${data["orient_cost_per_session"]:.4f}',
        'estimated (assumed tokens/file model)')

    # ── By source ─────────────────────────────────────────────────────────────
    projects = data.get('projects') or []
    if len(projects) > 1:
        lines.append('')
        lines.append('## By source')
        lines.append('')
        lines.append('| Source | Sessions | Reads/session | Reads before edit |')
        lines.append('|---|---:|---:|---:|')
        for src, n, avg_r, avg_rbe, _cw in projects:
            label = src if src in ('cursor', 'codex') else 'claude'
            lines.append(f'| {label} | {n} | {avg_r:.1f} | {avg_rbe:.1f} |')

    # ── Weekly trend ──────────────────────────────────────────────────────────
    if len(data.get('weekly') or []) > 1:
        lines.append('')
        lines.append('## Weekly trend — reads before first edit')
        lines.append('')
        lines.append('| Week | Avg | Sessions |')
        lines.append('|---|---:|---:|')
        for wk, avg, n in data['weekly']:
            lines.append(f'| {wk} | {avg:.1f} | {n} |')

    # ── Methodology ───────────────────────────────────────────────────────────
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('*Methodology: the pre-edit context share is the input-side '
                 'token spend (input + cache traffic weighted by provider '
                 'multipliers) of all requests before each session\'s first '
                 'edit, divided by total input-side spend, summed across '
                 'measured sessions. It is descriptive, not a waste claim. '
                 'Conservative by construction: read-only sessions are excluded '
                 '(reading was the job), sessions without token usage are '
                 'excluded and reported as unmeasured, and output-token spend is '
                 'not counted. Rows marked estimated use the assumed tokens/file '
                 'model and are not measurements. Generated by `cram audit '
                 '--report`.*')
    lines.append('')
    return '\n'.join(lines)
