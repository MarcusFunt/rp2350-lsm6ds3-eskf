import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v3.json"
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


if __name__ == "__main__":
    unittest.main()
