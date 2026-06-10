from __future__ import annotations

from pathlib import Path
import unittest


class WebConsoleContractsTest(unittest.TestCase):
    def test_runtime_console_contains_traceability_links_and_graph_maps(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("function CitationGraphMap", page_source)
        self.assertIn("function TraceabilityMap", page_source)
        self.assertIn("function NodeLink", page_source)
        self.assertIn('id={anchorId("traceability-map", "runtime")}', page_source)
        self.assertIn('id={anchorId("source-node", item.node.id)}', page_source)
        self.assertIn('id={anchorId("answer-run", run.answer_run.id)}', page_source)
        self.assertIn('href={anchorHref("answer-run", run.answer_run.id)}', page_source)
        self.assertIn('href={anchorHref("source-node", item.node.id)}', page_source)

    def test_runtime_console_styles_highlight_deep_link_targets(self) -> None:
        css_source = Path("apps/web/app/globals.css").read_text(encoding="utf-8")

        self.assertIn(".graphCanvas", css_source)
        self.assertIn(".traceMapCanvas", css_source)
        self.assertIn(".nodeLink", css_source)
        self.assertIn(":target", css_source)


if __name__ == "__main__":
    unittest.main()
