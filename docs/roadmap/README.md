# Saarthi 2.0 Roadmap

| Path | What it is |
|---|---|
| `Saarthi_Roadmap_2027.pptx` | The roadmap deck (Q1–Q4 2027) |
| `supporting_files/` | Excel, Word, image and SharePoint-link files behind the roadmap |
| `source/build_roadmap.js` | Generates the deck. All slide content is in the `ROADMAP` object at the top |

## Rebuilding the deck

```bash
npm install pptxgenjs react react-dom react-icons sharp
node docs/roadmap/source/build_roadmap.js
```

## Change log

| Version | Date | Change |
|---|---|---|
| v0.1 | 26 Nov 2026 | First draft, built from the design document (§1, §12, §13, §16) and the sales pitch |
