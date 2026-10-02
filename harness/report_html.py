"""Render the shareable HTML version of the report (results/report.html).

    python -m harness.report_html

Reads results/report.md (run `python -m harness.report` first) and runs.csv. The
executive summary text is written by hand and must be updated if results change.
"""
import html
import re
from pathlib import Path

import markdown

from harness.common import ROOT
from harness.score import RUNS_CSV, detection_matrix, read_csv

OUT = ROOT / "results" / "report.html"
md = (ROOT / "results" / "report.md").read_text()

# Drop the H1 and the provenance lines; the page header carries them.
body_md = md.split("## 1. Summary", 1)[1]
summary_md, rest_md = body_md.split("## 2. Tasks tested", 1)
rest_md = "## 2. Tasks tested" + rest_md
prov = md.split("## 1. Summary", 1)[0].splitlines()[2:]
prov_html = markdown.markdown("\n".join(prov))


def render(text: str) -> str:
    h = markdown.markdown(text, extensions=["tables", "fenced_code"])
    h = h.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")
    # Section anchors
    def anchor(m):
        title = m.group(1)
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<.*?>", "", title).lower()).strip("-")
        return f'<h2 id="{slug}">{title}</h2>'
    return re.sub(r"<h2>(.*?)</h2>", anchor, h)


# Detection matrix by fault category x arm
runs = read_csv(RUNS_CSV)
matrix = detection_matrix(runs)
order = ["F-REF", "F-TYPE", "F-CONTRACT", "F-DUPKEY", "F-FANOUT", "F-FILTER", "F-TZ", "F-NULL", "F-OFFSET", "F-SHARED-DEF"]
group = {"F-REF": "Structural", "F-TYPE": "Structural", "F-CONTRACT": "Structural", "F-DUPKEY": "Assertion"}
agg = {}
cats = {}
for (vid, arm), d in matrix.items():
    a = agg.setdefault((d["fault_id"], arm), [0, 0, 0])
    a[0] += d["caught"]
    a[1] += d["reps"]
    a[2] += d["pre_exec"]
    cats[d["fault_id"]] = d["category"]
rows = []
for f in order:
    cells = []
    for arm in "ABC":
        c, n, pre = agg.get((f, arm), [0, 0, 0])
        frac = c / n if n else 0
        note = f'<span class="pre">{pre} before exec</span>' if f in ("F-REF", "F-TYPE", "F-CONTRACT") else ""
        cells.append(f'<td class="cell" style="--f:{frac:.3f}"><span class="num">{c}/{n}</span>{note}</td>')
    grp = group.get(f, "Semantic")
    rows.append(f'<tr><th scope="row"><code>{f}</code><span class="cat">{html.escape(cats[f])}</span></th>'
                f'<td class="grp">{grp}</td>{"".join(cells)}</tr>')
matrix_html = f"""
<figure class="matrix">
  <div class="tbl"><table>
    <thead><tr><th scope="col">Fault</th><th scope="col">Layer</th>
      <th scope="col">Arm A<span>v1 + spot check</span></th>
      <th scope="col">Arm B<span>v2 strict + spot check</span></th>
      <th scope="col">Arm C<span>v2 strict + AI recon</span></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  <figcaption>Runs caught / runs, by fault category. Shading is the fraction caught. Arm C ran 3 repetitions per variant. F-SHARED-DEF is a designed miss: the reference shares the model's bug.</figcaption>
</figure>"""

page = f"""<title>Seeded-Fault Validation Eval</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Public+Sans:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: single reading column (~72ch) with a wide band for the matrix and tables; findings first, full report after. */
:root {{
  --paper: #f6f7f5;
  --surface: #ffffff;
  --ink: #18211f;
  --muted: #5a6763;
  --rule: #d9dfdc;
  --accent: #0d6b66;
  --caught: #1f7a52;
  --miss: #b4532a;
  --display: "Bricolage Grotesque", "Segoe UI", system-ui, sans-serif;
  --body: "Public Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --paper: #121816; --surface: #19211f; --ink: #e4ebe8; --muted: #9aa8a3; --rule: #2c3734;
  --accent: #5cc3ba; --caught: #4fbf8b; --miss: #e08a62; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --paper: #121816; --surface: #19211f; --ink: #e4ebe8; --muted: #9aa8a3; --rule: #2c3734;
  --accent: #5cc3ba; --caught: #4fbf8b; --miss: #e08a62; color-scheme: dark; }}

* {{ box-sizing: border-box; }}
body {{ background: var(--paper); color: var(--ink); font: 16px/1.6 var(--body); }}
.wrap {{ max-width: 60rem; margin: 0 auto; padding-inline: 20px; padding-block: 48px 80px; }}
.col {{ max-width: 44rem; }}
header .eyebrow {{ font: 500 0.75rem/1 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }}
h1 {{ font: 700 clamp(2rem, 5vw, 3rem)/1.05 var(--display); letter-spacing: -0.02em; margin: 0.6rem 0 1rem; text-wrap: balance; }}
h2 {{ font: 700 1.5rem/1.2 var(--display); letter-spacing: -0.01em; margin: 3.5rem 0 1rem; padding-top: 1.25rem; border-top: 1px solid var(--rule); text-wrap: balance; scroll-margin-top: 16px; }}
h3 {{ font: 600 1.05rem/1.3 var(--body); margin: 2rem 0 0.5rem; }}
p, li {{ max-width: 70ch; }}
.lede {{ font-size: 1.15rem; color: var(--ink); }}
.repo {{ font-size: 0.95rem; margin: 0 0 0.75rem; overflow-wrap: anywhere; }}
.prov {{ font-size: 0.85rem; color: var(--muted); }}
.prov p {{ margin: 0.25rem 0; }}
code {{ font: 0.86em var(--mono); background: color-mix(in srgb, var(--accent) 9%, transparent); padding: 0.05em 0.3em; border-radius: 3px; overflow-wrap: anywhere; }}
a {{ color: var(--accent); }}
a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
blockquote {{ margin: 1rem 0; padding: 0.75rem 1rem; border-left: 3px solid var(--miss); background: var(--surface); }}

.exec h2 {{ margin-top: 2rem; }}
.exec .headline {{ font: 600 1.25rem/1.45 var(--display); letter-spacing: -0.005em; padding: 14px 18px; background: var(--surface); border: 1px solid var(--rule); border-left: 3px solid var(--accent); border-radius: 4px; text-wrap: pretty; }}
.exec ul {{ display: grid; gap: 10px; padding-left: 1.2rem; margin: 1.25rem 0; }}
.exec .trust {{ font-size: 0.92rem; color: var(--muted); }}
.findings {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 12px; margin: 2rem 0; }}
.finding {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px 18px; min-width: 0; }}
.finding .k {{ font: 500 0.72rem/1.2 var(--mono); letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted); }}
.finding .v {{ font: 700 2rem/1.1 var(--display); margin: 0.4rem 0 0.3rem; font-variant-numeric: tabular-nums; }}
.finding .v small {{ font: 500 0.95rem var(--body); color: var(--muted); }}
.finding p {{ margin: 0; font-size: 0.9rem; color: var(--muted); }}

.tbl {{ overflow-x: auto; margin: 1rem 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: left; vertical-align: top; padding: 7px 10px; border-bottom: 1px solid var(--rule); }}
thead th {{ font: 600 0.78rem/1.3 var(--body); color: var(--muted); border-bottom: 1.5px solid var(--ink); }}
tbody tr:hover td, tbody tr:hover th {{ background: color-mix(in srgb, var(--accent) 5%, transparent); }}

.matrix {{ margin: 1.5rem 0 0.5rem; }}
.matrix table {{ font-size: 0.92rem; }}
.matrix thead th span {{ display: block; font-weight: 400; font-size: 0.72rem; }}
.matrix tbody th {{ font-weight: 400; white-space: nowrap; }}
.matrix .cat {{ display: block; font-size: 0.75rem; color: var(--muted); white-space: normal; }}
.matrix .grp {{ font: 0.75rem var(--mono); color: var(--muted); }}
.matrix .cell {{ background: color-mix(in srgb, var(--caught) calc(var(--f) * 38%), color-mix(in srgb, var(--miss) calc((1 - var(--f)) * 16%), transparent)); min-width: 6.5rem; }}
.matrix .num {{ font: 500 1rem var(--mono); }}
.matrix .pre {{ display: block; font-size: 0.72rem; color: var(--muted); }}
figcaption {{ font-size: 0.82rem; color: var(--muted); max-width: 70ch; }}

nav.toc {{ font-size: 0.85rem; display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 1.5rem 0 0; }}
nav.toc a {{ text-decoration: none; }}
nav.toc a:hover {{ text-decoration: underline; }}
@media (max-width: 520px) {{ .wrap {{ padding-block: 28px 56px; padding-inline: 16px; }} h2 {{ margin-top: 2.5rem; }} }}
</style>

<div class="wrap">
<header class="col">
  <div class="eyebrow">Seeded-fault evaluation · dbt v1 vs v2 · DuckDB</div>
  <h1>Does AI-assisted validation catch metric errors?</h1>
  <p class="lede">We planted 39 known faults in six jaffle-shop metric models and ran each one, plus a clean control per model, through three workflows: dbt v1 with a manual spot check, dbt v2 strict with the same spot check, and dbt v2 strict with AI-generated reconciliation.</p>
  <p class="repo">Code, data and every run: <a href="https://github.com/C00ldudeNoonan/dbt-v2-ai-validation-eval">github.com/C00ldudeNoonan/dbt-v2-ai-validation-eval</a></p>
  <div class="prov">{prov_html}</div>
</header>

<section class="exec col" aria-labelledby="exec-summary">
  <h2 id="exec-summary">Executive summary</h2>
  <p class="headline">On 13 business-metric faults that passed builds and tests, the manual spot check caught 3. AI-generated reconciliation caught all 13, every time (39 of 39 runs), with no false alarms on clean models.</p>
  <ul>
    <li><strong>dbt v2 catches broken code earlier.</strong> It stopped 11 of 18 structural faults (bad column references, type errors) before any SQL ran on the warehouse. dbt v1 stopped none early; it caught them only after about 48 queries had already run. Both engines eventually caught all 18. v2 did not catch contract violations early: those always surfaced at runtime.</li>
    <li><strong>AI reconciliation catches wrong numbers that pass every test.</strong> Missing filters, join fan-out, time-zone shifts, null handling and offsetting errors that leave grand totals unchanged. The usual "check the total and last month" spot check caught 3 of 13. The AI caught 13 of 13 in all 3 repetitions, comparing the model against the reference dashboard across about 36 slices per run.</li>
    <li><strong>It didn't cry wolf.</strong> No flags on the 18 clean-model runs, across 662 queries.</li>
    <li><strong>It's cheap.</strong> About $0.16 and under 2 minutes per validation. The whole AI run cost $9.75.</li>
    <li><strong>It has a known blind spot.</strong> When the reference dashboard has the same bug as the model, nothing catches it: 0 of 10 runs. Reconciliation is only as good as the reference you compare against.</li>
  </ul>
  <p class="trust"><strong>How far to trust this.</strong> These are planted, clean, single-model faults on a small sample (6 models), and the same team designed both the faults and the checks. Several faults are easy to see in the code the AI reads, and the reference dashboard uses the same column names and grain as each model. The result shows the approach works under good conditions. It does not show how it does against messy real bugs or how much rework it saves in production; that needs a field study.</p>
</section>

<section class="findings" aria-label="Key results">
  <div class="finding"><div class="k">Caught before execution</div><div class="v">11<small>/18</small></div><p>Structural faults stopped by dbt v2 strict before any model SQL ran. dbt v1: 0/18.</p></div>
  <div class="finding"><div class="k">Semantic faults, spot check</div><div class="v">3<small>/13</small></div><p>Caught by the two-total manual check, on either engine.</p></div>
  <div class="finding"><div class="k">Semantic faults, AI recon</div><div class="v">39<small>/39 runs</small></div><p>All 13 variants caught in all 3 repetitions. Two had thin margins.</p></div>
  <div class="finding"><div class="k">Clean-control flags</div><div class="v">0<small>/18 runs</small></div><p>Across 662 AI queries. ~$0.155 and 36 queries per AI validation.</p></div>
</section>

<section class="col">
  <h2 id="summary">Summary</h2>
  {render(summary_md)}
</section>

{matrix_html}

<nav class="toc" aria-label="Report sections">
  <a href="#2-tasks-tested">Tasks</a><a href="#3-baseline-arm-a">Baseline</a><a href="#4-how-correctness-was-judged">Method</a>
  <a href="#5-engine-comparison-h1-arm-a-vs-arm-b">Engine (H1)</a><a href="#6-reconciliation-comparison-h2-arm-b-vs-arm-c">Reconciliation (H2)</a>
  <a href="#7-false-positives-clean-controls">False positives</a><a href="#8-cost">Cost</a><a href="#9-missed-cases">Misses</a>
  <a href="#10-measured-vs-expected">Measured vs expected</a><a href="#11-limitations">Limitations</a>
</nav>

<main>
{render(rest_md)}
</main>
</div>
"""
OUT.write_text(page)
print(OUT, len(page))
