#!/usr/bin/env python3
"""Run B9 fault lifecycle assertions with the candidate gravity-gate settings."""

from __future__ import annotations

import shlex
import subprocess
import os
import hashlib
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEST = ROOT / "tests/test_b9_fault_recovery.cpp"


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    if not compiler:
        raise ValueError("CXX cannot be empty")
    with tempfile.TemporaryDirectory(prefix="b9-fault-candidate-") as name:
        temp = Path(name)
        baseline_executable = temp / "test_b9_fault_recovery_baseline"
        run([*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
             str(TEST), "-o", str(baseline_executable)], cwd=ROOT)
        baseline_result = run([str(baseline_executable)], cwd=ROOT)
        baseline_checks = [line for line in baseline_result.stdout.splitlines() if line.startswith("PASS ")]
        if len(baseline_checks) < 5:
            raise ValueError(f"expected baseline lifecycle PASS output, found {len(baseline_checks)} checks")

    source = TEST.read_text(encoding="utf-8")
    source = source.replace('#include "../eskf15.hpp"', '#include "eskf15.hpp"')
    source = source.replace('#include "../runtime_health.hpp"', '#include "runtime_health.hpp"')
    old = "    Settings settings{};"
    new = "    Settings settings{};\n    settings.static_gyro_limit=0.48f;\n    settings.static_min_samples=7;"
    count = source.count(old)
    if count < 5:
        raise ValueError(f"expected at least 5 lifecycle settings sites, found {count}")
    source = source.replace(old, new)
    with tempfile.TemporaryDirectory(prefix="b9-fault-candidate-") as name:
        temp = Path(name)
        patched_test = temp / "test_b9_fault_recovery_candidate.cpp"
        patched_test.write_text(source, encoding="utf-8")
        executable = temp / "test_b9_fault_recovery_candidate"
        run([*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
             f"-I{ROOT}", str(patched_test), "-o", str(executable)], cwd=ROOT)
        result = run([str(executable)], cwd=ROOT)
        checks = [line for line in result.stdout.splitlines() if line.startswith("PASS ")]
        if len(checks) < 5:
            raise ValueError(f"expected lifecycle PASS output, found {len(checks)} checks")
        version = run([*compiler, "--version"], cwd=ROOT).stdout.splitlines()[0]
        report = {
            "schema": "b9.fault_gate_candidate_validation.v1",
            "candidate_settings": {"static_gyro_limit_rad_s": 0.48, "static_min_samples": 7},
            "baseline_assertion_groups": baseline_checks,
            "candidate_assertion_groups": checks,
            "baseline_assertion_group_count": len(baseline_checks),
            "candidate_assertion_group_count": len(checks),
            "compiler": version,
            "test_source_sha256": hashlib.sha256(TEST.read_bytes()).hexdigest(),
            "candidate_test_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "production_filter_modified": False,
            "fault_latch_modified": False,
            "stale_output_safeguards_modified": False,
            "status": "PASS",
        }
        (ROOT / "remediation/analysis/pr3_gravity_gate_ablations/fault_gate_candidate_validation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"baseline groups: {len(baseline_checks)}; candidate groups: {len(checks)}")
        print("candidate settings: gyro gate 0.48 rad/s; dwell 7 samples")
        print("fault and recovery assertions:")
        print("\n".join(checks))
        print(f"PASS candidate fault-injection lifecycle checks ({len(checks)} assertions groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
