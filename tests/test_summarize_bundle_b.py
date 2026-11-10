#!/usr/bin/env python3
"""Unit tests for strict Bundle B aggregation and paired comparison rules."""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'summarize_bundle_b.py'
SPEC = importlib.util.spec_from_file_location('summarize_bundle_b', MODULE_PATH)
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def fixture_rows(profiles=('nominal',), trials=2):
    rows = []
    for scenario_index, scenario in enumerate(SUMMARY.SCENARIOS):
        for profile in profiles:
            for trial_id in range(trials):
                stream_hash = f'{scenario_index + trial_id + 1:016x}'
                for model_index, model in enumerate(SUMMARY.MODELS):
                    row = {
                        'schema_version': '2', 'metric_definition_version': '2',
                        'scenario': scenario, 'trial_id': str(trial_id),
                        'sensor_profile': profile, 'model': model,
                        'seed': str(20261728 + trial_id * 1009 + scenario_index),
                        'startup_bias': '0', 'expected': '3', 'valid': '3', 'invalid': '0',
                        'valid_fraction': '1.0', 'valid_mask': '111',
                        'tilt_rms_deg': str(1.0 + model_index + trial_id * 0.1),
                        'yaw_rms_deg': str(4.0 + model_index + trial_id * 0.2),
                        'tilt_nees_mean': '', 'tilt_nees_coverage95': '', 'tilt_nees_count': '0',
                        'gravity_nis_mean': '', 'gravity_nis_count': '0', 'gyro_bias_error_rps': '',
                        'uninitialized_samples': '0', 'invalid_samples': '0',
                        'degraded_samples': '0', 'faulted_samples': '0',
                        'accel_clip_samples': '0', 'gyro_clip_samples': '0',
                        'imu_stream_hash_fnv1a64': stream_hash,
                        'noise_draw_hash_fnv1a64': f'{scenario_index + trial_id + 100:016x}',
                    }
                    rows.append(row)
    return rows


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class StudentTTests(unittest.TestCase):
    def test_known_two_sided_95_percent_critical_values(self):
        expected = {1: 12.7062047364, 7: 2.3646242510, 30: 2.0422724563, 199: 1.9719565442}
        for degrees, value in expected.items():
            with self.subTest(degrees=degrees):
                self.assertAlmostEqual(SUMMARY.student_t_critical_975(degrees), value, places=7)

    def test_missing_and_single_observation_intervals_are_null(self):
        empty = SUMMARY.mean_ci([None, float('nan')])
        self.assertEqual(empty, {'mean': None, 'sd': None, 'ci95_low': None,
                                 'ci95_high': None, 'n_finite': 0, 'n_missing': 2})
        one = SUMMARY.mean_ci([2.5, None])
        self.assertEqual(one['mean'], 2.5)
        self.assertIsNone(one['sd'])
        self.assertIsNone(one['ci95_low'])
        self.assertEqual((one['n_finite'], one['n_missing']), (1, 1))

    def test_identical_two_trial_interval_and_eight_trial_reference(self):
        identical = SUMMARY.mean_ci([3.0, 3.0])
        self.assertEqual(identical['sd'], 0.0)
        self.assertEqual(identical['ci95_low'], 3.0)
        self.assertEqual(identical['ci95_high'], 3.0)
        eight = SUMMARY.mean_ci([1, 2, 3, 4, 5, 6, 7, 8])
        expected_half_width = 2.3646242510103 * (6.0 ** 0.5) / (8.0 ** 0.5)
        self.assertAlmostEqual(eight['mean'], 4.5, places=12)
        self.assertAlmostEqual(eight['sd'], 6.0 ** 0.5, places=12)
        self.assertAlmostEqual(eight['ci95_low'], 4.5 - expected_half_width, delta=1e-8)
        self.assertAlmostEqual(eight['ci95_high'], 4.5 + expected_half_width, delta=1e-8)

    def test_empty_nonfinite_and_malformed_numeric_parsing(self):
        self.assertIsNone(SUMMARY.parse_finite({'x': ''}, 'x'))
        self.assertIsNone(SUMMARY.parse_finite({'x': 'nan'}, 'x'))
        self.assertIsNone(SUMMARY.parse_finite({'x': 'inf'}, 'x'))
        with self.assertRaisesRegex(ValueError, 'must be numeric'):
            SUMMARY.parse_finite({'x': 'broken'}, 'x')


class InputAndPairingTests(unittest.TestCase):
    def test_complete_rows_summarize_and_emit_matched_pairs(self):
        raw = fixture_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trials.csv'
            write_csv(path, raw)
            parsed = SUMMARY.read(path)
        groups, pairs = SUMMARY.summarize(parsed)
        self.assertEqual(len(groups), 8 * 3)
        self.assertEqual(len(pairs), 8 * 3 * 2)
        comparison = next(item for item in pairs if item['scenario'] == 'static'
                          and item['model_a'] == 'eskf_conservative'
                          and item['model_b'] == 'eskf_legacy'
                          and item['metric'] == 'tilt_rms_deg')
        self.assertEqual(comparison['n_pairs'], 2)
        self.assertAlmostEqual(comparison['delta']['mean'], -2.0)
        self.assertEqual(comparison['mask_mismatch_count'], 0)
        static = next(row for row in groups if row['scenario']=='static'
                      and row['sensor_profile']=='nominal' and row['model']=='eskf_conservative')
        self.assertEqual(static['diagnostics']['tilt_nees_sample_count'],0)
        self.assertEqual(static['diagnostics']['tilt_nees_sample_coverage'],0.0)

    def test_single_trial_svg_marks_ci_unavailable(self):
        raw = fixture_rows(trials=1)
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / 'single.csv'
            svg_path = Path(directory) / 'single.svg'
            write_csv(csv_path, raw)
            groups, _ = SUMMARY.summarize(SUMMARY.read(csv_path))
            SUMMARY.write_svg(groups, False, 'nominal', 'tilt_rms_deg', 'Single trial', svg_path)
            content = svg_path.read_text()
            self.assertIn('CI N/A when fewer than two finite trials.', content)
            ET.parse(svg_path)

    def test_unaligned_masks_are_excluded_and_reported(self):
        raw = fixture_rows()
        for row in raw:
            if row['scenario'] == 'static' and row['trial_id'] == '0' and row['model'] == 'eskf_legacy':
                row['valid_mask'] = '110'
                row['valid'] = '2'
                row['invalid'] = '1'
                row['valid_fraction'] = '0.6666666666666666'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trials.csv'
            write_csv(path, raw)
            parsed = SUMMARY.read(path)
        _, pairs = SUMMARY.summarize(parsed)
        comparison = next(item for item in pairs if item['scenario'] == 'static'
                          and item['model_a'] == 'eskf_conservative'
                          and item['model_b'] == 'eskf_legacy'
                          and item['metric'] == 'tilt_rms_deg')
        self.assertEqual(comparison['n_pairs'], 1)
        self.assertEqual(comparison['mask_mismatch_count'], 1)
        self.assertEqual(comparison['n_missing'], 1)

    def test_duplicate_trial_and_stream_hash_mismatch_are_rejected(self):
        raw = fixture_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trials.csv'
            write_csv(path, raw + [raw[0]])
            with self.assertRaisesRegex(ValueError, 'duplicate trial row'):
                SUMMARY.read(path)
            raw[1]['imu_stream_hash_fnv1a64'] = 'ffffffffffffffff'
            write_csv(path, raw)
            with self.assertRaisesRegex(ValueError, 'same IMU stream hash'):
                SUMMARY.read(path)

    def test_missing_group_trial_is_rejected(self):
        raw = fixture_rows()
        raw = [row for row in raw if not (row['scenario']=='static' and row['model']=='eskf_legacy' and row['trial_id']=='0')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trials.csv'
            write_csv(path, raw)
            with self.assertRaisesRegex(ValueError, 'inconsistent trial IDs'):
                SUMMARY.read(path)


if __name__ == '__main__':
    unittest.main()
