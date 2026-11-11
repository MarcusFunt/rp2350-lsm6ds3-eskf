import csv
import sys
import tempfile
import unittest
from itertools import islice
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from summarize_pr3_benchmarks import summarize


class Pr3SummaryTests(unittest.TestCase):
    def test_reports_and_figures_are_lf_even_with_windows_text_translation(self):
        source = ROOT / "benchmarks/reports/pr3_protocol_v5_dev100_208_nominal_trials.csv"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "sample.csv"
            with source.open(newline="", encoding="utf-8") as input_stream, sample.open(
                "w", newline="", encoding="utf-8"
            ) as output_stream:
                reader = csv.DictReader(input_stream)
                writer = csv.DictWriter(output_stream, fieldnames=reader.fieldnames)
                writer.writeheader()
                writer.writerows(islice(reader, 5))

            original_write_text = Path.write_text

            def windows_write_text(path, text, encoding=None, errors=None, newline=None):
                if newline is None:
                    text = text.replace("\n", "\r\n")
                return original_write_text(
                    path, text, encoding=encoding, errors=errors, newline=newline
                )

            output = root / "output"
            with patch.object(Path, "write_text", windows_write_text):
                summarize(
                    sample,
                    output,
                    report_source="sample.csv",
                    figure_prefix="stable",
                    figure_path_prefix="figures/",
                )

            artifacts = [output / "pr3_summary.json", *sorted((output / "figures").glob("*.svg"))]
            self.assertGreaterEqual(len(artifacts), 2)
            for artifact in artifacts:
                self.assertNotIn(b"\r\n", artifact.read_bytes(), str(artifact))


if __name__ == "__main__":
    unittest.main()
