"""
Wraps the pandoc HTML of docs/SAARTHI_DESIGN_DOCUMENT.md in a printable
page: cover, print CSS, landscape section for the CRUD matrix, and
Mermaid (inlined, so rendering needs no network). Called by build.sh.

Usage: python3 build_html.py <work_dir>
  reads  <work_dir>/body.html  and  ./node_modules/mermaid/dist/mermaid.min.js
  writes <work_dir>/doc.html
"""
import os
import re
import sys

S = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
body = open(f"{S}/body.html").read()
body = re.sub(r'<pre class="mermaid"><code>(.*?)</code></pre>',
              lambda m: f'<div class="diagram"><div class="mermaid">{m.group(1)}</div></div>', body, flags=re.S)
# drop the doc's own H1 (cover page replaces it)
body = re.sub(r'<h1[^>]*>Saarthi 2.0 — Detailed Design Document</h1>', '', body, count=1)
# mark the wide CRUD matrix table
idx = body.find('<h2 id="14-table--flow-crud-matrix"')
end = body.find('<h2', idx + 5)
if idx != -1:
    sec = body[idx:end].replace('<table', '<table class="wide"', 1)
    body = body[:idx] + '<section class="landscape">' + sec + '</section>' + body[end:]
mermaid_js = open(os.path.join(HERE, "node_modules/mermaid/dist/mermaid.min.js")).read()
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Saarthi 2.0 — Design Document</title>
<style>
@page {{ size: A4; margin: 18mm 15mm 18mm 15mm; }}
body {{ font-family: "Segoe UI", "DejaVu Sans", Arial, sans-serif; font-size: 10.2pt; line-height: 1.5; color: #1f2933; }}
.cover {{ height: 245mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; border-left: 8px solid #1f5fa8; padding-left: 14mm; }}
.cover h1 {{ font-size: 34pt; margin: 0 0 6mm; color: #12355b; border: none; }}
.cover .sub {{ font-size: 15pt; color: #3e4c59; margin-bottom: 14mm; }}
.cover .meta {{ font-size: 10.5pt; color: #616e7c; line-height: 1.8; }}
h1, h2 {{ color: #12355b; }}
h2 {{ font-size: 17pt; border-bottom: 2px solid #1f5fa8; padding-bottom: 3px; margin-top: 0; page-break-before: always; }}
h3 {{ font-size: 12.5pt; color: #1f5fa8; margin-top: 18px; page-break-after: avoid; }}
h4 {{ font-size: 11pt; page-break-after: avoid; }}
p, li {{ orphans: 3; widows: 3; }}
code {{ font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.6pt; background: #eef2f7; padding: 0 3px; border-radius: 3px; overflow-wrap: anywhere; }}
pre {{ background: #f5f7fa; border: 1px solid #d9e2ec; border-left: 4px solid #1f5fa8; padding: 8px 10px; font-size: 8.2pt; line-height: 1.4; white-space: pre-wrap; word-break: break-word; page-break-inside: avoid; }}
pre code {{ background: none; padding: 0; font-size: inherit; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0 14px; font-size: 8.6pt; page-break-inside: auto; }}
tr {{ page-break-inside: avoid; }}
thead {{ display: table-header-group; }}
th {{ background: #12355b; color: #fff; text-align: left; padding: 5px 6px; font-weight: 600; }}
td {{ border: 1px solid #d9e2ec; padding: 4px 6px; vertical-align: top; overflow-wrap: anywhere; }}
tbody tr:nth-child(even) td {{ background: #f7f9fb; }}
@page wide {{ size: A4 landscape; margin: 14mm 12mm; }}
section.landscape {{ page: wide; }}
section.landscape h2 {{ page-break-before: auto; }}
th code {{ background: rgba(255,255,255,.15); color: #fff; }}
table.wide {{ font-size: 7.2pt; table-layout: auto; }}
table.wide td {{ overflow-wrap: normal; }}
table.wide th {{ padding: 3px 2px; writing-mode: vertical-rl; transform: rotate(180deg); height: 95px; vertical-align: bottom; text-align: left; }}
table.wide th:first-child {{ writing-mode: horizontal-tb; transform: none; width: 15%; vertical-align: bottom; }}
table.wide td {{ padding: 2px 2px; text-align: center; }}
table.wide td:first-child {{ text-align: left; }}
blockquote {{ margin: 10px 0; padding: 8px 12px; background: #fff8e6; border-left: 4px solid #f0b429; color: #3e4c59; page-break-inside: avoid; }}
blockquote p {{ margin: 4px 0; }}
.diagram {{ margin: 12px 0 16px; padding: 8px; border: 1px solid #d9e2ec; border-radius: 6px; background: #fff; text-align: center; page-break-inside: avoid; }}
.diagram svg {{ display: inline-block; }}
hr {{ display: none; }}
a {{ color: #1f5fa8; text-decoration: none; }}
#toc-section ol, nav ol {{ line-height: 1.8; }}
</style></head><body>
<div class="cover">
  <h1>Saarthi 2.0</h1>
  <div class="sub">Detailed Design Document<br/>Module flows, data model &amp; table usage</div>
  <div class="meta">Repository: TathyumSolutions/SAARTHI2.0<br/>Source: docs/SAARTHI_DESIGN_DOCUMENT.md<br/>Generated: {{GENERATED}}</div>
</div>
{body}
<script>{mermaid_js}</script>
<script>
mermaid.initialize({{ startOnLoad: false, theme: 'default', securityLevel: 'loose',
  flowchart: {{ htmlLabels: true, useMaxWidth: true }}, sequence: {{ useMaxWidth: true, wrap: true }},
  themeVariables: {{ fontFamily: 'DejaVu Sans, Arial, sans-serif', fontSize: '13px' }} }});
mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
  document.querySelectorAll('.diagram svg').forEach(svg => {{
    const vb = svg.viewBox.baseVal; if (!vb || !vb.width) return;
    const k = Math.min(660 / vb.width, 820 / vb.height, 1.8);
    svg.style.maxWidth = 'none';
    svg.setAttribute('width', Math.round(vb.width * k));
    svg.setAttribute('height', Math.round(vb.height * k));
  }});
  window.__done = true; }}).catch(e => {{ window.__err = (e && (e.message || e.str)) || String(e); window.__done = true; }});
</script></body></html>"""
open(f"{S}/doc.html", "w").write(page.replace("{GENERATED}", os.environ.get("DOC_DATE", "")))
