"""Regression: complete historical report must write every matrix field to CSV."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from research_v3 import historical


class HistoricalCSVSchema(unittest.TestCase):
    def test_report_writes_entry_mode_and_all_rows(self):
        base=1793491200000
        bars=[{"ts":base+i*60000,"o":100.,"h":101.,"l":99.,
               "c":100.,"quote":100.,"buy":50.} for i in range(1100)]
        with tempfile.TemporaryDirectory() as d:
            with patch.object(historical,"load_symbol",return_value=(bars,[])):
                result=historical.run(out_dir=d,universe=("BTCUSDT",),months=("2026-10",))
            with (Path(d)/"matrix.csv").open(newline="",encoding="utf8") as f:
                reader=csv.DictReader(f)
                rows=list(reader)
                self.assertIn("entry_mode",reader.fieldnames)
                self.assertEqual(len(rows),len(result["matrix"]))
                self.assertEqual({r["entry_mode"] for r in rows},{"acc","breakout"})
                self.assertTrue(all(r["entry_mode"]==r["model"] for r in rows))
            self.assertEqual(len(json.loads((Path(d)/"summary.json").read_text())["matrix"]),len(rows))
            self.assertTrue((Path(d)/"trades.csv").exists())
            self.assertTrue((Path(d)/"report.md").exists())


if __name__=="__main__":
    unittest.main()
