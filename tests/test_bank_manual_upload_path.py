"""Bank/NBFC ratios of an UPLOADED report: `_get_extracted_bank_financials` must read the synthetic manual-upload:// marker from the on-disk
PDF cache like the Schedule-III path does.  It used to HTTP-GET the marker, so every bank ratio of an uploaded annual report came back
'Could not download the Annual Report' (NIM, CASA, NPA, CAR, C/D, cost-to-income all unavailable)."""
import os
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBankManualUploadPath(unittest.TestCase):

    def test_uploaded_report_is_served_from_the_pdf_cache_not_downloaded(self):
        path = os.path.join(ROOT, "cache", "ar_pdfs", "SYNTHBANK_2026.pdf")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existed = os.path.exists(path)
        if not existed:
            with open(path, "wb") as fh:
                fh.write(b"%PDF-synthetic" + b"0" * 60000)
        try:
            seen = {}

            def fake_extract(content, consolidated=False):
                seen["bytes"] = len(content)
                return {"advances": (1.0, 1.0)}

            def no_network(*a, **k):
                raise AssertionError("a manual-upload:// marker must never be downloaded")
            with patch.object(ar, "_find_annual_report_pdf", return_value="manual-upload://SYNTHBANK_2026"), \
                 patch.object(ar, "_extract_bank_from_pdf", fake_extract), patch.object(ar, "_sess", no_network), \
                 patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None):
                out = ar._get_extracted_bank_financials("SYNTHBANK", "Synth Bank", 2026, True)
            self.assertNotIn("error", out)
            self.assertGreater(seen["bytes"], 50000)
            self.assertEqual(out["source_url"], "manual-upload://SYNTHBANK_2026")
        finally:
            if not existed and os.path.exists(path):
                os.remove(path)

    def test_missing_uploaded_pdf_is_reported_not_downloaded(self):
        with patch.object(ar, "_find_annual_report_pdf", return_value="manual-upload://NOPEBANK_2026"), \
             patch.object(ar, "_sess", lambda: (_ for _ in ()).throw(AssertionError("no download"))), \
             patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None):
            out = ar._get_extracted_bank_financials("NOPEBANK", "Nope", 2026, True)
        self.assertIn("No uploaded Annual Report PDF", out["error"])


if __name__ == "__main__":
    unittest.main()
