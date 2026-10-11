# Design document PDF

Rebuilds `docs/Saarthi_Design_Document.pdf` from `docs/SAARTHI_DESIGN_DOCUMENT.md`.
Run it after editing the Markdown:

```bash
scripts/design_pdf/build.sh            # writes docs/Saarthi_Design_Document.pdf
scripts/design_pdf/build.sh out.pdf    # or another path
```

Requirements: `pandoc`, `python3`, `node`. The first run does `npm install` here (Mermaid + Playwright). Playwright then needs a Chromium: run `npx playwright install chromium`, or set `PLAYWRIGHT_CHROMIUM_PATH` to an existing one.

The build fails if any Mermaid diagram doesn't render. A common cause: a `;` inside a sequence-diagram message, which Mermaid reads as a line break.

Files:
- `build.sh`: the pipeline (pandoc → HTML → Chromium → PDF)
- `build_html.py`: cover page, print CSS, landscape page for the CRUD matrix, inlined Mermaid
- `print.js`: renders the diagrams, sizes them to the page, prints the PDF with header and page numbers
