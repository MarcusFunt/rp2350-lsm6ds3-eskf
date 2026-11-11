#!/usr/bin/env python3
"""Regression tests for GCC .su stack-usage report parsing."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.report_firmware_resources import parse_stack_usage_record


class StackUsageRecordTests(unittest.TestCase):
    def test_preserves_cpp_qualified_signature_and_argument_commas(self):
        line = (
            "/home/runner/repo/eskf15.hpp:586:10:"
            "void inertial::Eskf15::predict(inertial::Vec3, inertial::Vec3, float)"
            "\t7560\tstatic"
        )
        self.assertEqual(
            parse_stack_usage_record(line),
            {
                "function": "void inertial::Eskf15::predict(inertial::Vec3, inertial::Vec3, float)",
                "bytes": 7560,
                "classification": "static",
                "source_record": line.split("\t", 1)[0],
            },
        )

    def test_preserves_windows_drive_path_and_operator_signature(self):
        line = "C:\\agent\\src\\file.cpp:42:6:void Example::operator()(int, int)\t64\tdynamic,bounded"
        record = parse_stack_usage_record(line)
        self.assertEqual(record["function"], "void Example::operator()(int, int)")
        self.assertEqual(record["bytes"], 64)
        self.assertEqual(record["classification"], "dynamic,bounded")

    def test_ignores_malformed_records(self):
        self.assertIsNone(parse_stack_usage_record("not a stack usage record"))
        self.assertIsNone(parse_stack_usage_record("file.cpp:1:2:f()\tnot-a-size\tstatic"))


if __name__ == "__main__":
    unittest.main()
