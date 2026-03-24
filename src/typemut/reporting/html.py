"""HTML report generation."""

from __future__ import annotations

import difflib
from html import escape
from pathlib import Path

import typemut
from typemut.db import Database, MutantRow

STATUS_COLORS = {
    "killed": "#2d7d2d",
    "survived": "#d32f2f",
    "error": "#e67e22",
    "pending": "#7f8c8d",
    "skipped": "#95a5a6",
}

STATUS_LABELS = {
    "killed": "Killed",
    "survived": "Survived",
    "error": "Error",
    "pending": "Pending",
    "skipped": "Skipped",
}

HEADER_COLORS = {
    "killed": "#e8f5e9",
    "survived": "#ffebee",
    "error": "#fff3e0",
    "pending": "#f5f5f5",
    "skipped": "#f5f5f5",
}


def generate_html(db: Database) -> str:
    """Generate a standalone HTML report with full mutant details."""
    summary = db.get_summary()
    all_mutants = db.get_all()

    total_killed = sum(s.get("killed", 0) for s in summary.values())
    total_survived = sum(s.get("survived", 0) for s in summary.values())
    total_errors = sum(s.get("error", 0) for s in summary.values())
    total_skipped = sum(s.get("skipped", 0) for s in summary.values())
    total_all = sum(sum(s.values()) for s in summary.values())
    testable = total_killed + total_survived
    total_score = (total_killed / testable * 100) if testable > 0 else 0

    module_rows = _build_module_rows(summary)
    survived_cards = _build_mutant_cards(all_mutants, {"survived"})
    error_cards = _build_mutant_cards(all_mutants, {"error"})
    killed_cards = _build_mutant_cards(all_mutants, {"killed"})

    sc = _score_class(total_score)

    survived_section = (
        "<p>No survived mutants. All mutations were caught by the type checker.</p>"
        if total_survived == 0
        else _detail_cards(survived_cards, total_survived)
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>typemut Report</title>
<style>
:root {{
  --bg: #fafafa; --fg: #1a1a1a; --border: #e0e0e0;
  --card-bg: #fff; --code-bg: #f5f5f5;
  --good: #2d7d2d; --mid: #e67e22; --bad: #d32f2f;
  --muted: #6b7280;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  max-width: 1100px; margin: 0 auto; padding: 2em 1.5em;
  line-height: 1.5;
}}
h1 {{ font-size: 1.6em; margin-bottom: 0.3em; }}
h2 {{
  font-size: 1.2em; margin: 1.5em 0 0.5em;
  border-bottom: 2px solid var(--border); padding-bottom: 0.3em;
}}
.summary {{
  display: flex; gap: 1.5em; flex-wrap: wrap; margin: 1em 0;
}}
.stat {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 1em 1.5em; min-width: 120px;
}}
.stat .value {{ font-size: 2em; font-weight: 700; }}
.stat .label {{ font-size: 0.85em; color: var(--muted); }}
.good {{ color: var(--good); }}
.mid {{ color: var(--mid); }}
.bad {{ color: var(--bad); }}

/* Module summary table */
table {{
  border-collapse: collapse; width: 100%; margin: 0.5em 0 1.5em;
  font-size: 0.9em; background: var(--card-bg);
  border: 1px solid var(--border); border-radius: 6px;
  overflow: hidden;
}}
th {{ background: var(--code-bg); font-weight: 600; text-align: left; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
tr:last-child td {{ border-bottom: none; }}
tr:hover {{ background: #f9f9f9; }}
.module-name {{ font-family: "SF Mono", "Fira Code", monospace; font-size: 0.85em; }}
.totals td {{ font-weight: 700; border-top: 2px solid var(--border); }}

code {{
  font-family: "SF Mono", "Fira Code", monospace; font-size: 0.85em;
  background: var(--code-bg); padding: 2px 5px; border-radius: 3px;
}}
.badge {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  color: #fff; font-size: 0.8em; font-weight: 600; white-space: nowrap;
}}

/* Section collapse */
.collapsible {{ cursor: pointer; user-select: none; }}
.collapsible::before {{ content: "\\25B6 "; font-size: 0.8em; }}
.collapsible.open::before {{ content: "\\25BC "; }}
.section-content {{ display: none; }}
.section-content.open {{ display: block; }}

/* Mutant cards */
.mutant-card {{
  border: 1px solid var(--border); border-radius: 6px;
  margin: 0.4em 0; background: var(--card-bg); overflow: hidden;
}}
.card-header {{
  display: flex; align-items: center; gap: 0.75em;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 0.9em; transition: filter 0.15s;
}}
.card-header:hover {{ filter: brightness(0.96); }}
.mutant-id {{
  font-weight: 700; font-family: "SF Mono", "Fira Code", monospace;
  min-width: 3.5em; color: var(--fg);
}}
.mutant-operator {{
  font-family: "SF Mono", "Fira Code", monospace;
  color: var(--muted); font-size: 0.9em;
}}
.mutant-location {{
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 0.85em; color: var(--muted);
}}
.mutant-duration {{
  font-size: 0.82em; color: var(--muted);
}}
.chevron {{
  margin-left: auto; font-size: 0.7em; transition: transform 0.2s;
  color: var(--muted);
}}
.card-header.open .chevron {{ transform: rotate(90deg); }}
.card-body {{
  display: none; padding: 12px 16px;
  border-top: 1px solid var(--border);
}}
.card-body.open {{ display: block; }}
.card-description {{
  margin-bottom: 0.5em; font-size: 0.9em;
}}

/* Diff */
.diff {{
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 0.82em; line-height: 1.6;
  background: var(--code-bg); padding: 10px 14px;
  border-radius: 4px; overflow-x: auto;
  white-space: pre; margin: 0.5em 0;
  border: 1px solid var(--border);
}}
.diff span {{ display: block; padding: 0 4px; }}
.diff-del {{ background: #fdd; color: #900; }}
.diff-add {{ background: #dfd; color: #060; }}
.diff-hunk {{ color: #0077aa; font-style: italic; }}
.diff-header {{ color: var(--muted); font-weight: 600; }}

/* Fallback diff (no source file) */
.fallback-diff {{ margin: 0.5em 0; font-size: 0.9em; }}
.diff-del-block {{
  background: #fdd; padding: 4px 10px; border-radius: 4px 4px 0 0;
  border: 1px solid #fcc; font-family: "SF Mono", "Fira Code", monospace;
}}
.diff-del-block::before {{ content: "- "; color: #900; font-weight: 700; }}
.diff-add-block {{
  background: #dfd; padding: 4px 10px; border-radius: 0 0 4px 4px;
  border: 1px solid #cec; border-top: none;
  font-family: "SF Mono", "Fira Code", monospace;
}}
.diff-add-block::before {{ content: "+ "; color: #060; font-weight: 700; }}

/* Output */
.card-output {{ margin-top: 0.5em; }}
.card-output summary {{
  cursor: pointer; font-size: 0.85em; color: var(--muted);
  padding: 4px 0; user-select: none;
}}
.card-output pre {{
  font-size: 0.8em; background: var(--code-bg);
  padding: 10px 14px; border-radius: 4px;
  overflow-x: auto; white-space: pre-wrap; word-break: break-word;
  max-height: 400px; overflow-y: auto;
  border: 1px solid var(--border); margin-top: 4px;
}}

/* Controls */
.card-controls {{ margin: 0.5em 0; }}
.card-controls button {{
  padding: 4px 14px; border: 1px solid var(--border);
  background: var(--card-bg); border-radius: 4px;
  cursor: pointer; font-size: 0.85em; margin-right: 0.5em;
}}
.card-controls button:hover {{ background: var(--code-bg); }}

footer {{ margin-top: 2em; color: var(--muted); font-size: 0.85em; }}
</style>
</head>
<body>
<h1>typemut — Type Mutation Testing Report</h1>

<div class="summary">
  <div class="stat">
    <div class="value {sc}">{total_score:.1f}%</div>
    <div class="label">Mutation Score</div>
  </div>
  <div class="stat">
    <div class="value">{total_all}</div>
    <div class="label">Total Mutants</div>
  </div>
  <div class="stat">
    <div class="value good">{total_killed}</div>
    <div class="label">Killed</div>
  </div>
  <div class="stat">
    <div class="value bad">{total_survived}</div>
    <div class="label">Survived</div>
  </div>
  <div class="stat">
    <div class="value mid">{total_errors}</div>
    <div class="label">Errors</div>
  </div>
  <div class="stat">
    <div class="value">{total_skipped}</div>
    <div class="label">Skipped</div>
  </div>
</div>

<h2>Summary by Module</h2>
<table>
<tr><th>Module</th><th>Total</th><th>Killed</th><th>Survived</th><th>Errors</th><th>Skipped</th><th>Score</th></tr>
{module_rows}<tr class="totals">
<td>TOTAL</td><td>{total_all}</td><td>{total_killed}</td><td>{total_survived}</td>
<td>{total_errors}</td><td>{total_skipped}</td><td class="{sc}">{total_score:.1f}%</td></tr>
</table>

<h2 class="collapsible" onclick="toggle(this)">Survived Mutants ({total_survived})</h2>
<div class="section-content{" open" if total_survived > 0 else ""}">
{survived_section}
</div>

<h2 class="collapsible" onclick="toggle(this)">Errors ({total_errors})</h2>
<div class="section-content">
{_detail_cards(error_cards, total_errors)}
</div>

<h2 class="collapsible" onclick="toggle(this)">Killed Mutants ({total_killed})</h2>
<div class="section-content">
{_detail_cards(killed_cards, total_killed)}
</div>

<footer>Generated by typemut v{typemut.__version__}</footer>

<script>
function toggle(el) {{
  el.classList.toggle('open');
  el.nextElementSibling.classList.toggle('open');
}}
function toggleCard(header) {{
  header.classList.toggle('open');
  header.nextElementSibling.classList.toggle('open');
}}
function expandAll(btn) {{
  var section = btn.closest('.section-content');
  section.querySelectorAll('.card-header:not(.open)').forEach(function(h) {{
    h.classList.add('open');
    h.nextElementSibling.classList.add('open');
  }});
}}
function collapseAll(btn) {{
  var section = btn.closest('.section-content');
  section.querySelectorAll('.card-header.open').forEach(function(h) {{
    h.classList.remove('open');
    h.nextElementSibling.classList.remove('open');
  }});
}}
// Auto-open survived section if any
document.querySelectorAll('.section-content.open').forEach(function(el) {{
  el.previousElementSibling.classList.add('open');
}});
</script>
</body>
</html>"""


def _build_module_rows(summary: dict[str, dict[str, int]]) -> str:
    rows = ""
    for module, statuses in sorted(summary.items()):
        killed = statuses.get("killed", 0)
        survived = statuses.get("survived", 0)
        errors = statuses.get("error", 0)
        skipped = statuses.get("skipped", 0)
        total = sum(statuses.values())
        testable = killed + survived
        score = (killed / testable * 100) if testable > 0 else 0
        sc = _score_class(score)
        rows += (
            f'<tr><td class="module-name">{escape(module)}</td>'
            f"<td>{total}</td>"
            f"<td>{killed}</td>"
            f"<td>{survived}</td>"
            f"<td>{errors}</td>"
            f"<td>{skipped}</td>"
            f'<td class="{sc}">{score:.1f}%</td></tr>\n'
        )
    return rows


def _build_mutant_cards(mutants: list[MutantRow], statuses: set[str]) -> str:
    """Build card-based HTML for mutants matching given statuses."""
    cards: list[str] = []
    for m in mutants:
        if m.status not in statuses:
            continue

        header_bg = HEADER_COLORS.get(m.status, "#f5f5f5")
        duration_str = f"{m.duration_seconds:.1f}s" if m.duration_seconds else ""
        duration_html = (
            f'<span class="mutant-duration">{duration_str}</span>' if duration_str else ""
        )

        # Diff section
        diff_text = _generate_diff(m)
        if diff_text:
            diff_html = f'<pre class="diff">{_format_diff_html(diff_text)}</pre>'
        else:
            diff_html = (
                f'<div class="fallback-diff">'
                f'<div class="diff-del-block"><code>{escape(m.original_annotation)}</code></div>'
                f'<div class="diff-add-block"><code>{escape(m.mutated_annotation)}</code></div>'
                f"</div>"
            )

        # Output section
        output_html = ""
        if m.output:
            output_html = (
                f'<details class="card-output">'
                f"<summary>Type checker output</summary>"
                f"<pre>{escape(m.output)}</pre>"
                f"</details>"
            )

        cards.append(
            f'<div class="mutant-card">'
            f'<div class="card-header" style="background:{header_bg}" onclick="toggleCard(this)">'
            f'<span class="mutant-id">#{m.id}</span>'
            f'<span class="mutant-operator">{escape(m.operator)}</span>'
            f'<span class="mutant-location">{escape(m.module_path)}:{m.line}</span>'
            f"{_status_badge(m.status)}"
            f"{duration_html}"
            f'<span class="chevron">&#x25B6;</span>'
            f"</div>"
            f'<div class="card-body">'
            f'<div class="card-description">{escape(m.description)}</div>'
            f"{diff_html}"
            f"{output_html}"
            f"</div>"
            f"</div>\n"
        )
    return "".join(cards)


def _detail_cards(cards_html: str, count: int) -> str:
    if count == 0:
        return "<p>None.</p>"
    return (
        '<div class="card-controls">'
        '<button onclick="expandAll(this)">Expand All</button>'
        '<button onclick="collapseAll(this)">Collapse All</button>'
        "</div>\n"
        f"{cards_html}"
    )


def _score_class(score: float) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "mid"
    return "bad"


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#7f8c8d")
    label = STATUS_LABELS.get(status, status)
    return f'<span class="badge" style="background:{color}">{label}</span>'


def _generate_diff(mutant: MutantRow, context_lines: int = 3) -> str | None:
    """Generate a unified diff showing the mutation in context."""
    try:
        source = Path(mutant.module_path).read_text()
    except (OSError, UnicodeDecodeError):
        return None

    lines = source.splitlines(keepends=True)
    line_idx = mutant.line - 1

    if line_idx < 0 or line_idx >= len(lines):
        return None

    original_line = lines[line_idx]
    col = mutant.col
    orig = mutant.original_annotation
    end_col = col + len(orig)
    if original_line[col:end_col] != orig:
        return None
    mutated_line = original_line[:col] + mutant.mutated_annotation + original_line[end_col:]

    # Build context window
    start = max(0, line_idx - context_lines)
    end = min(len(lines), line_idx + context_lines + 1)

    original_chunk = lines[start:end]
    mutated_chunk = list(original_chunk)
    mutated_chunk[line_idx - start] = mutated_line

    diff = difflib.unified_diff(
        original_chunk,
        mutated_chunk,
        fromfile=f"a/{mutant.module_path}",
        tofile=f"b/{mutant.module_path}",
        lineterm="",
    )
    return "\n".join(line.rstrip("\n") for line in diff)


def _format_diff_html(diff_text: str) -> str:
    """Colorize a unified diff as HTML."""
    html_lines: list[str] = []
    for line in diff_text.splitlines():
        escaped = escape(line)
        if line.startswith("---") or line.startswith("+++"):
            html_lines.append(f'<span class="diff-header">{escaped}</span>')
        elif line.startswith("@@"):
            html_lines.append(f'<span class="diff-hunk">{escaped}</span>')
        elif line.startswith("-"):
            html_lines.append(f'<span class="diff-del">{escaped}</span>')
        elif line.startswith("+"):
            html_lines.append(f'<span class="diff-add">{escaped}</span>')
        else:
            html_lines.append(f"<span>{escaped}</span>")
    return "\n".join(html_lines)
