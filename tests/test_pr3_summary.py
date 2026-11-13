import csv
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from itertools import islice
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from summarize_pr3_benchmarks import display_estimator_id, summarize


class Pr3SummaryTests(unittest.TestCase):
    def test_internal_mahony_legacy_label_maps_to_versioned_historical_id(self):
        self.assertEqual(display_estimator_id("mahony"), "mahony_internal_historical")
        self.assertEqual(display_estimator_id("mahony_reference"), "mahony_reference")

    def test_reports_sample_standard_deviation_and_student_t_mean_interval(self):
        source = ROOT / "benchmarks/reports/pr3_protocol_v5_dev100_208_nominal_trials.csv"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "eight_trials.csv"
            with source.open(newline="", encoding="utf-8") as input_stream:
                base_rows = list(islice(csv.DictReader(input_stream), 5))
            rows = []
            for seed in range(1, 9):
                for model_index, base in enumerate(base_rows):
                    row = dict(base)
                    row["seed"] = str(seed)
                    row["input_sha256"] = f"{seed:064x}"
                    row["tilt_rms_deg"] = str(seed + model_index)
                    rows.append(row)
            with sample.open("w", newline="", encoding="utf-8") as output_stream:
                writer = csv.DictWriter(output_stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            output = root / "output"
            summarize(sample, output, report_source="eight_trials.csv", figure_prefix="eight")
            report = json.loads((output / "pr3_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(report["estimator_display_ids"]["mahony"], "mahony_internal_historical")
            self.assertEqual(
                report["variant_alias_registry"],
                "external_benchmarks/adapters/mahony_variant_aliases_b6_v1.json",
            )
            self.assertTrue(
                any(
                    "mahony_internal_historical" in (output / figure).read_text(encoding="utf-8")
                    for figure in report["figures"]
                )
            )
            group = next(
                item for item in report["distribution_groups"]
                if item["scenario"] == "static" and item["estimator"] == "eskf_conservative"
            )
            metric = group["metric_distributions"]["tilt_rms_deg"]
            self.assertIn("sample_standard_deviation", metric)
            self.assertAlmostEqual(metric["mean"], 4.5, places=12)
            self.assertAlmostEqual(metric["sample_standard_deviation"], 2.449489742783178, places=12)
            self.assertEqual(metric["mean_ci95_method"], "Student t, two-sided 95%, df=7")
            self.assertAlmostEqual(metric["mean_ci95"]["lower"], 2.452, delta=0.002)
            self.assertAlmostEqual(metric["mean_ci95"]["upper"], 6.548, delta=0.002)

    def test_runner_manifest_hashes_all_factorized_figures(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/run_pr3_benchmarks.py"),
                    "--protocol", str(ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"),
                    "--split", "development", "--first-seed", "4001", "--last-seed", "4001",
                    "--scenarios", "static", "--rate-modes", "uniform_208hz",
                    "--stress-modes", "nominal,stress", "--profiles", "baseline",
                    "--output-dir", str(output), "--source-commit", "e" * 40,
                    "--tree-dirty", "no", "--figure-prefix", "factorized",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / "pr3_summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "pr3_run_manifest.json").read_text(encoding="utf-8"))
            figure_names = [Path(path).name for path in report["figures"]]
            expected_hashes = {
                name: hashlib.sha256((output / "figures" / name).read_bytes()).hexdigest()
                for name in figure_names
            }
            self.assertEqual(manifest["figure_sha256"], expected_hashes[figure_names[0]])
            self.assertEqual(manifest["additional_figure_sha256"], {
                name: digest for name, digest in expected_hashes.items() if name != figure_names[0]
            })
            csv_sha = hashlib.sha256((output / "pr3_trial_summaries.csv").read_bytes()).hexdigest()
            refreshed = subprocess.run(
                [
                    sys.executable, str(ROOT / "tools/run_pr3_benchmarks.py"),
                    "--refresh-report-only", "--output-dir", str(output),
                    "--figure-prefix", "factorized", "--figure-path-prefix", "figures/",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
            self.assertEqual(csv_sha, hashlib.sha256((output / "pr3_trial_summaries.csv").read_bytes()).hexdigest())
            refreshed_manifest = json.loads((output / "pr3_run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(refreshed_manifest["figure_sha256"], expected_hashes[figure_names[0]])
            self.assertEqual(refreshed_manifest["additional_figure_sha256"], {
                name: digest for name, digest in expected_hashes.items() if name != figure_names[0]
            })

    def test_generates_separate_nonempty_figures_for_stress_and_nominal_factors(self):
        source = ROOT / "benchmarks/reports/pr3_protocol_v5_dev100_208_nominal_trials.csv"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "nominal_and_stress.csv"
            with source.open(newline="", encoding="utf-8") as input_stream:
                reader = csv.DictReader(input_stream)
                rows = list(islice(reader, 5))
            stress_rows = []
            for row in rows:
                stress = dict(row)
                stress["stress_mode"] = "stress"
                stress["input_sha256"] = "d" * 64
                stress["tilt_rms_deg"] = str(float(row["tilt_rms_deg"]) + 1.0)
                stress_rows.append(stress)
            with sample.open("w", newline="", encoding="utf-8") as output_stream:
                writer = csv.DictWriter(output_stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows + stress_rows)

            output = root / "output"
            summarize(sample, output, report_source="nominal_and_stress.csv", figure_prefix="factors")
            report = json.loads((output / "pr3_summary.json").read_text(encoding="utf-8"))
            tilt_figures = [Path(name).name for name in report["figures"] if "tilt_rms" in name]
            self.assertEqual(len(tilt_figures), 2)
            self.assertTrue(any("nominal" in name for name in tilt_figures))
            self.assertTrue(any("stress" in name for name in tilt_figures))
            for name in tilt_figures:
                figure = (output / "figures" / name).read_text(encoding="utf-8")
                self.assertIn("static", figure)
                self.assertIn("stress" if "stress" in name else "nominal", figure)
                self.assertIn("Student-t CI", figure)
                self.assertIn("<circle", figure)

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
