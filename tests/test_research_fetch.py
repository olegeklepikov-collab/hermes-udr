"""Direct fetch retains complete bytes and fails closed on unsafe redirects."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_research_report.research_fetch import fetch
from hermes_research_report.research_workspace import workspace


class ResearchFetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name})
        self.env.start()
        self.run_id = workspace({"action": "start", "question": "Read originals"})["run_id"]
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)

    def test_redirected_html_keeps_more_than_provider_50k_and_exact_raw_hash(self):
        raw = b"<html><main><p>" + b"A" * 60_000 + b"</p></main></html>"
        calls = []

        def pinned(url, maximum, host, **kwargs):
            calls.append((url, maximum, host))
            if len(calls) == 1:
                return 302, {"location": "https://journal.example/full"}, b"go", "8.8.8.8", True
            return 200, {"content-type": "text/html"}, raw, "8.8.4.4", True

        with patch("hermes_research_report.research_fetch._fetch_one", side_effect=pinned):
            result = fetch({"run_id": self.run_id, "url": "https://journal.example/short",
                            "max_bytes": 100_000})
        self.assertEqual(result["status"], "full_text_registered")
        self.assertEqual(result["extent"], "full_text")
        self.assertEqual(result["characters"], 60_000)
        self.assertEqual(result["original_sha256"], hashlib.sha256(raw).hexdigest())
        metadata = json.loads(Path(result["metadata_file"]).read_text())
        self.assertEqual(Path(metadata["original_path"]).read_bytes(), raw)
        self.assertEqual(len(metadata["hops"]), 2)
        self.assertEqual(calls[1][2], "journal.example")

    def test_pdf_text_is_saved_and_private_redirect_is_rejected_before_followup(self):
        pdf = b"%PDF-1.4\ncontrolled original\n"
        with patch("hermes_research_report.research_fetch._fetch_one",
                   return_value=(200, {"content-type": "application/pdf"}, pdf, "8.8.8.8", True)), \
             patch("hermes_research_report.research_fetch.shutil.which",
                   return_value="/usr/bin/pdftotext"), \
             patch("hermes_research_report.research_fetch.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=b"Full PDF text, last page included.")) as converter:
            result = fetch({"run_id": self.run_id, "url": "https://journal.example/paper.pdf"})
        self.assertEqual(result["extent"], "full_text")
        self.assertIn("last page included", Path(result["path"]).read_text())
        self.assertEqual(converter.call_args.args[0][:2], ["pdftotext", "-layout"])

        pages = [SimpleNamespace(extract_text=lambda **_: "First page text."),
                 SimpleNamespace(extract_text=lambda **_: "Final page text.")]
        with patch("hermes_research_report.research_fetch._fetch_one",
                   return_value=(200, {"content-type": "application/pdf"}, pdf, "8.8.8.8", True)), \
             patch("hermes_research_report.research_fetch.shutil.which", return_value=None), \
             patch("pdfplumber.open", return_value=nullcontext(SimpleNamespace(pages=pages))):
            fallback = fetch({"run_id": self.run_id, "url": "https://journal.example/fallback.pdf"})
        fallback_text = Path(fallback["path"]).read_text()
        self.assertIn("[PDF page 1/2]\nFirst page text.", fallback_text)
        self.assertIn("[PDF page 2/2]\nFinal page text.", fallback_text)
        metadata = json.loads(Path(fallback["metadata_file"]).read_text())
        self.assertEqual(metadata["extraction"], "pdfplumber_all_pages")
        self.assertFalse(metadata["visuals_verified"])

        jats = (b'<!DOCTYPE article PUBLIC "-//NLM//DTD JATS 1.2//EN" '
                b'"https://jats.nlm.nih.gov/JATS-archivearticle1.dtd">'
                b'<article><body><p>Complete JATS body text.</p></body></article>')
        with patch("hermes_research_report.research_fetch._fetch_one",
                   return_value=(200, {"content-type": "application/xml"}, jats, "8.8.8.8", True)):
            xml_result = fetch({"run_id": self.run_id, "url": "https://journal.example/article.xml"})
        self.assertIn("Complete JATS body text", Path(xml_result["path"]).read_text())

        with patch("hermes_research_report.research_fetch._fetch_one",
                   return_value=(302, {"location": "http://127.0.0.1/private"}, b"", "8.8.8.8", True)) as pinned:
            with self.assertRaises(ValueError):
                fetch({"run_id": self.run_id, "url": "https://journal.example/redirect"})
            self.assertEqual(pinned.call_count, 1)


if __name__ == "__main__":
    unittest.main()
