#!/usr/bin/env node
import { PdfEngine } from "@paperjsx/json-to-pdf";
import { writeFileSync } from "node:fs";

const [output, version = "1.0", date = new Date().toISOString().slice(0, 10)] = process.argv.slice(2);
if (!output) {
  throw new Error("usage: render_geo_operator_cover.mjs OUTPUT [VERSION] [DATE]");
}

// PaperJSX free-tier cover is intentionally ASCII. Chromium renders the CJK manual body.
const specification = {
  meta: {
    title: "ADVINSYS GEO Deployment and Operations Manual",
    author: "GEO Platform Engineering"
  },
  page: { size: "A4", margin: 68 },
  children: [
    { type: "heading", value: "ADVINSYS GEO", level: 1 },
    { type: "heading", value: "Deployment and Operations Manual", level: 2 },
    { type: "paragraph", value: "Production project plus isolated controlled staging acceptance." },
    { type: "paragraph", value: `Version ${version}  |  ${date}` },
    {
      type: "table",
      columns: [{ width: 150 }, { width: 270 }],
      rows: [
        { isHeader: true, cells: [{ value: "Control" }, { value: "Required evidence" }] },
        { cells: [{ value: "Actual project" }, { value: "Real sources, model calls, accounts and URLs only" }] },
        { cells: [{ value: "Staging simulation" }, { value: "SIMULATION-labelled URL, T+28/T+56/T+84 and reports" }] },
        { cells: [{ value: "Delivery gate" }, { value: "Receipts, browser QA and backup/restore smoke test" }] }
      ]
    },
    { type: "paragraph", value: "Generated from a versioned JSON document specification." }
  ]
};

const buffer = await PdfEngine.render(specification);
if (!buffer.length) throw new Error("PaperJSX produced an empty cover");
writeFileSync(output, buffer);
