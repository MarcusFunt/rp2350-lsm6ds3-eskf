import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v3.json"
PROTOCOL_V4 = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v4.json"
PROTOCOL_V5 = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v5.json"
CODEGEN = ROOT / "tools" / "pr3_generate_scenario_header.py"


class Pr3ScenarioCodegenTests(unittest.TestCase):
    def test_header_codegen_is_deterministic_and_contains_all_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.hpp"
            second = Path(directory) / "second.hpp"
            for output in (first, second):
                result = subprocess.run(
                    [sys.executable, str(CODEGEN), str(PROTOCOL), str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            source = first.read_text(encoding="utf-8")
            for scenario in (
                "static",
                "slow_yaw",
                "lateral_accel",
                "maneuver",
                "vibration",
                "timing_jitter",
                "stop_start",
                "compound_motion",
            ):
                self.assertIn(f'"{scenario}"', source)
            self.assertIn("irregular_208hz", source)
            self.assertIn("scenario_jitter_us", source)
            self.assertIn("kProtocolVersion = 3", source)
            self.assertIn("t >= 0x1.0000000000000p+1", source)
            self.assertIn("protocol_sha256=", source)

    def test_header_codegen_rejects_invalid_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            output = Path(directory) / "invalid.hpp"
            invalid.write_text('{"protocol":"wrong"}', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CODEGEN), str(invalid), str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protocol validation", result.stderr.lower())
            self.assertFalse(output.exists())

    def test_v4_codegen_carries_disjoint_confirmation_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "v4.hpp"
            result = subprocess.run(
                [sys.executable, str(CODEGEN), str(PROTOCOL_V4), str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            source = output.read_text(encoding="utf-8")
            self.assertIn("kProtocolVersion = 4", source)
            self.assertIn("kHeldOutFirstSeed = 7001", source)
            self.assertIn("kConfirmationFirstSeed = 8001", source)

    def test_v5_codegen_carries_disjoint_confirmation_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "v5.hpp"
            result = subprocess.run(
                [sys.executable, str(CODEGEN), str(PROTOCOL_V5), str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            source = output.read_text(encoding="utf-8")
            self.assertIn("kProtocolVersion = 5", source)
            self.assertIn("kHeldOutFirstSeed = 9001", source)
            self.assertIn("kConfirmationFirstSeed = 10001", source)

    def test_protocol_sha_is_stable_across_windows_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = PROTOCOL_V5.read_bytes().replace(b"\r\n", b"\n")
            lf_protocol = root / "v5-lf.json"
            crlf_protocol = root / "v5-crlf.json"
            lf_protocol.write_bytes(normalized)
            crlf_protocol.write_bytes(normalized.replace(b"\n", b"\r\n"))
            headers = [root / "lf.hpp", root / "crlf.hpp"]
            for protocol, output in ((lf_protocol, headers[0]), (crlf_protocol, headers[1])):
                result = subprocess.run(
                    [sys.executable, str(CODEGEN), str(protocol), str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(headers[0].read_bytes(), headers[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
