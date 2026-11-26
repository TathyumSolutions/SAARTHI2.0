// Builds docs/roadmap/Saarthi_Roadmap_2027.pptx
// Run from the repo root:  node docs/roadmap/source/build_roadmap.js
// Needs: pptxgenjs, react, react-dom, react-icons, sharp (npm).
// All roadmap content lives in ROADMAP below; edit it and rebuild.

const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const OUT = path.join(__dirname, "..", "Saarthi_Roadmap_2027.pptx");

// ---------- Theme ----------
const THEME = {
  name: "Saarthi Roadmap",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2B48", // ink navy (dominant)
    lt1: "FFFFFF",
    dk2: "4A5670", // muted slate text
    lt2: "EEF2F7", // light card tint
    accent1: "E8A33D", // saffron
    accent2: "2A9D8F", // teal
    accent3: "3D5A99", // indigo
    accent4: "C8553D", // terracotta
    accent5: "8AA1C4",
    accent6: "6B7A8F",
    hlink: "2A9D8F",
    folHlink: "3D5A99",
  },
};
const HEX = THEME.colors;

// ---------- Content ----------
const ROADMAP = {
  title: "Saarthi 2.0 Product Roadmap",
  subtitle: "From governed pilot to enterprise-ready AI layer · 2027",
  version: "Draft v0.1 · 26 Nov 2026",
  today: [
    { icon: "FaDatabase", name: "DB track", text: "8-agent LangGraph pipeline writes SQL for PostgreSQL" },
    { icon: "FaFileExcel", name: "Spreadsheet track", text: "Excel/CSV as Parquet, answered via an LLM query plan" },
    { icon: "FaFileAlt", name: "Files track", text: "RAG over Qdrant for PDF, DOCX, MD and TXT documents" },
    { icon: "FaPlug", name: "API track", text: "LLM tool-calling against registered REST endpoints" },
    { icon: "FaBrain", name: "MetaMind + self-learning", text: "Per-user router config that learns from feedback" },
  ],
  stats: [
    { value: "5", label: "answer tracks" },
    { value: "3", label: "LLM backends supported" },
    { value: "12", label: "known gaps logged in the design doc" },
  ],
  quarters: [
    {
      q: "Q1 2027", theme: "Secure the core", icon: "FaShieldAlt", color: "accent4",
      items: [
        "Encrypt stored DB passwords",
        "Scope API tools and spreadsheets to own + granted",
        "Remove user-1 identity fallback",
        "Strip secrets and PII from debug logs",
        "Fix API-track call signature",
      ],
    },
    {
      q: "Q2 2027", theme: "Scale and reliability", icon: "FaServer", color: "accent3",
      items: [
        "Query all PostgreSQL connections, not only the first",
        "Redis pub/sub for multi-worker streaming",
        "Clean re-index of re-processed documents",
        "Cached metadata for the Details popup",
      ],
    },
    {
      q: "Q3 2027", theme: "Smarter answers", icon: "FaLightbulb", color: "accent2",
      items: [
        "Conversation memory for follow-up questions",
        "MySQL, SQL Server and Oracle connectors",
        "LLM cost tracking and daily budgets",
        "Richer self-learning from feedback",
      ],
    },
    {
      q: "Q4 2027", theme: "Enterprise rollout", icon: "FaBuilding", color: "accent1", ink: "text1",
      items: [
        "SharePoint and OneDrive document connector",
        "One-step VPC / on-prem deployment kit",
        "Data warehouse builder to general availability",
        "Audit and governance dashboards for admins",
      ],
    },
  ],
  outcomes: [
    { icon: "FaRupeeSign", name: "Predictable economics", text: "Self-hosted models carry most traffic; spend is visible per budget" },
    { icon: "FaLock", name: "Zero data leakage", text: "Every source tenant-scoped; no secrets in logs or plaintext" },
    { icon: "FaSitemap", name: "Autonomous schema discovery", text: "Any major SQL database discovered and queryable after Process" },
    { icon: "FaClipboardCheck", name: "Governance and audit", text: "Each answer traceable to its query, model, cost and user" },
  ],
  nextSteps: [
    "Review and confirm the quarter themes and items",
    "Add owners, effort and target dates per item",
    "Drop supporting Excel, Word, image and SharePoint files in docs/roadmap/supporting_files",
  ],
};

// ---------- Helpers ----------
async function icon(name, hex, size = 256) {
  const Comp = fa[name];
  if (!Comp) throw new Error(`Unknown icon ${name}`);
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: "#" + hex, size: String(size) })
  );
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
  pres.title = ROADMAP.title;
  pres.author = "Tathyum Solutions";
  pres.company = "Tathyum Solutions Pvt. Ltd.";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  // ---------- Layouts ----------
  pres.defineSlideMaster({
    title: "DARK_TITLE",
    background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.6, w: 8.8, h: 1.2, fontSize: 40, bold: true, color: C.background1, align: "left", valign: "bottom", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 2.95, w: 8.8, h: 0.9, fontSize: 18, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: C.background1 },
    margin: [0.5, 0.5, 0.5, 0.5],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.75, fontSize: 30, bold: true, color: C.text1, valign: "middle", margin: 0 }, text: "" } },
      { text: { text: "Saarthi 2.0 · Product Roadmap", options: { x: 0.5, y: 5.2, w: 5, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } },
    ],
    slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.3, fontSize: 10, color: C.text2, align: "right" },
  });

  // ---------- 1. Title ----------
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "DARK_TITLE", sectionTitle: "Introduction" });
  s.addText(ROADMAP.title, { placeholder: "title" });
  s.addText(ROADMAP.subtitle, { placeholder: "body" });
  s.addImage({ data: await icon("FaRoute", HEX.accent1), x: 0.6, y: 0.7, w: 0.7, h: 0.7, objectName: "Route icon" });
  s.addText(ROADMAP.version, { x: 0.6, y: 4.8, w: 6, h: 0.3, fontSize: 12, color: C.background2, margin: 0, isTextBox: true, objectName: "Version" });
  s.addNotes("Draft roadmap built from the Saarthi 2.0 design document and the sales pitch. Content is a starting point for review.");

  // ---------- 2. Where we are today ----------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Introduction" });
  s.addText("Where Saarthi stands today", { placeholder: "title" });
  for (let i = 0; i < ROADMAP.today.length; i++) {
    const t = ROADMAP.today[i];
    const y = 1.25 + i * 0.75;
    s.addShape(pres.shapes.OVAL, { x: 0.5, y, w: 0.55, h: 0.55, fill: { color: C.text1 }, line: { type: "none" }, objectName: `Today icon bg ${i + 1}` });
    s.addImage({ data: await icon(t.icon, HEX.accent1), x: 0.63, y: y + 0.13, w: 0.29, h: 0.29, objectName: `Today icon ${i + 1}` });
    s.addText(
      [
        { text: t.name, options: { bold: true, fontSize: 15, color: C.text1, breakLine: true } },
        { text: t.text, options: { fontSize: 14, color: C.text2 } },
      ],
      { x: 1.25, y: y - 0.05, w: 4.85, h: 0.65, margin: 0, valign: "middle", isTextBox: true, objectName: `Today text ${i + 1}` }
    );
  }
  for (let i = 0; i < ROADMAP.stats.length; i++) {
    const st = ROADMAP.stats[i];
    const y = 1.25 + i * 1.25;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 6.3, y, w: 3.2, h: 1.05, rectRadius: 0.1, fill: { color: C.background2 }, line: { type: "none" }, objectName: `Stat card ${i + 1}` });
    s.addText(st.value, { x: 6.45, y: y + 0.1, w: 1.0, h: 0.85, fontSize: 40, bold: true, color: C.accent2, fontFace: THEME.headFontFace, valign: "middle", margin: 0, isTextBox: true, objectName: `Stat value ${i + 1}` });
    s.addText(st.label, { x: 7.45, y: y + 0.1, w: 1.95, h: 0.85, fontSize: 14, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: `Stat label ${i + 1}` });
  }

  // ---------- 3. Roadmap at a glance ----------
  pres.addSection({ title: "Roadmap" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Roadmap" });
  s.addText("2027 at a glance", { placeholder: "title" });
  s.addShape(pres.shapes.LINE, { x: 0.9, y: 2.0, w: 8.2, h: 0, line: { color: C.accent6, width: 2 }, objectName: "Timeline line" });
  for (let i = 0; i < ROADMAP.quarters.length; i++) {
    const q = ROADMAP.quarters[i];
    const cx = 0.5 + i * 2.3;
    s.addShape(pres.shapes.OVAL, { x: cx + 0.75, y: 1.6, w: 0.8, h: 0.8, fill: { color: C[q.color] }, line: { color: C.background1, width: 3 }, objectName: `Quarter dot ${i + 1}` });
    s.addImage({ data: await icon(q.icon, HEX.lt1), x: cx + 0.97, y: 1.82, w: 0.36, h: 0.36, objectName: `Quarter icon ${i + 1}` });
    s.addText(q.q, { x: cx, y: 2.55, w: 2.3, h: 0.4, fontSize: 18, bold: true, color: C.text1, align: "center", margin: 0, isTextBox: true, objectName: `Quarter label ${i + 1}` });
    s.addText(q.theme, { x: cx, y: 2.95, w: 2.3, h: 0.4, fontSize: 14, italic: true, color: C[q.color], align: "center", margin: 0, isTextBox: true, objectName: `Quarter theme ${i + 1}` });
    s.addText(`${q.items.length} initiatives`, { x: cx, y: 3.35, w: 2.3, h: 0.35, fontSize: 12, color: C.text2, align: "center", margin: 0, isTextBox: true, objectName: `Quarter count ${i + 1}` });
  }
  s.addText("Harden first, then scale, then widen what Saarthi can answer, then package it for enterprise rollout.", {
    x: 0.5, y: 4.1, w: 9.0, h: 0.6, fontSize: 15, color: C.text1, align: "center", margin: 0, isTextBox: true, objectName: "Glance summary",
  });

  // ---------- 4-7. One slide per quarter ----------
  for (let i = 0; i < ROADMAP.quarters.length; i++) {
    const q = ROADMAP.quarters[i];
    s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Roadmap" });
    s.addText(`${q.q} · ${q.theme}`, { placeholder: "title" });
    // left panel
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y: 1.25, w: 2.6, h: 3.7, rectRadius: 0.12, fill: { color: C[q.color] }, line: { type: "none" }, objectName: "Quarter panel" });
    const ink = q.ink ? C[q.ink] : C.background1;
    const inkHex = q.ink ? HEX.dk1 : HEX.lt1;
    s.addImage({ data: await icon(q.icon, inkHex), x: 1.35, y: 1.65, w: 0.9, h: 0.9, objectName: "Quarter panel icon" });
    s.addText(q.q, { x: 0.6, y: 2.8, w: 2.4, h: 0.5, fontSize: 24, bold: true, color: ink, fontFace: THEME.headFontFace, align: "center", margin: 0, isTextBox: true, objectName: "Quarter panel label" });
    s.addText(`${q.items.length} initiatives`, { x: 0.6, y: 3.35, w: 2.4, h: 0.4, fontSize: 14, color: ink, align: "center", margin: 0, isTextBox: true, objectName: "Quarter panel count" });
    // item rows
    const rowH = Math.min(0.68, 3.7 / q.items.length);
    for (let j = 0; j < q.items.length; j++) {
      const y = 1.25 + j * rowH;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.4, y, w: 6.1, h: rowH - 0.12, rectRadius: 0.08, fill: { color: C.background2 }, line: { type: "none" }, objectName: `Item card ${j + 1}` });
      s.addText(String(j + 1), { x: 3.55, y, w: 0.4, h: rowH - 0.12, fontSize: 16, bold: true, color: q.ink ? C.text1 : C[q.color], valign: "middle", margin: 0, isTextBox: true, objectName: `Item number ${j + 1}` });
      s.addText(q.items[j], { x: 4.0, y, w: 5.35, h: rowH - 0.12, fontSize: 15, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: `Item text ${j + 1}` });
    }
  }

  // ---------- 8. Outcomes ----------
  pres.addSection({ title: "Outcomes" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Outcomes" });
  s.addText("What the roadmap delivers by end of 2027", { placeholder: "title" });
  for (let i = 0; i < ROADMAP.outcomes.length; i++) {
    const o = ROADMAP.outcomes[i];
    const x = 0.5 + (i % 2) * 4.6;
    const y = 1.25 + Math.floor(i / 2) * 1.85;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 4.4, h: 1.65, rectRadius: 0.1, fill: { color: C.background2 }, line: { type: "none" }, objectName: `Outcome card ${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.3, w: 0.6, h: 0.6, fill: { color: C.text1 }, line: { type: "none" }, objectName: `Outcome icon bg ${i + 1}` });
    s.addImage({ data: await icon(o.icon, HEX.accent1), x: x + 0.4, y: y + 0.45, w: 0.3, h: 0.3, objectName: `Outcome icon ${i + 1}` });
    s.addText(
      [
        { text: o.name, options: { bold: true, fontSize: 16, color: C.text1, breakLine: true } },
        { text: o.text, options: { fontSize: 14, color: C.text2 } },
      ],
      { x: x + 1.05, y: y + 0.15, w: 3.2, h: 1.35, valign: "middle", margin: 0, isTextBox: true, objectName: `Outcome text ${i + 1}` }
    );
  }

  // ---------- 9. Next steps ----------
  s = pres.addSlide({ masterName: "DARK_TITLE", sectionTitle: "Outcomes" });
  s.addText("Next steps", { placeholder: "title" });
  s.addText(
    ROADMAP.nextSteps.map((t, i) => ({
      text: t,
      options: { bullet: { type: "number" }, breakLine: i < ROADMAP.nextSteps.length - 1, paraSpaceAfter: 6 },
    })),
    { placeholder: "body", color: C.background1, fontSize: 16, h: 1.8 }
  );

  await pres.writeFile({ fileName: OUT });

  const { applyTheme } = require("./apply_theme.js");
  await applyTheme(OUT, THEME);
  console.log("Wrote", OUT);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
