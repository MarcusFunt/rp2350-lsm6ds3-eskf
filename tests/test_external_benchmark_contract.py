import copy
import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sample(timestamp, *, accel=(0.0, 0.0, 9.80665), gyro=(0.0, 0.0, 0.0), aid=None):
    value = {
        "timestamp": timestamp,
        "accel_mps2": list(accel),
        "gyro_rad_s": list(gyro),
        "valid": True,
    }
    if aid is not None:
        value["aid"] = copy.deepcopy(aid)
    return value


def make_trial(samples=None, *, sensor_set="gyro_accel_6d"):
    if samples is None:
        samples = [sample(0), sample(5_000_000), sample(10_000_000)]
    units = {
        "timestamp": "ns",
        "accelerometer": "m/s^2",
        "gyroscope": "rad/s",
    }
    if sensor_set == "gyro_accel_mag_9d":
        units["magnetometer"] = "uT"
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": "fixture-trial-001",
        "source_id": "fixture-source",
        "source_artifact_sha256": "a" * 64,
        "sensor_set": sensor_set,
        "timebase": {
            "timestamp_unit": "ns",
            "sampling_mode": "uniform",
            "nominal_rate_hz": {"numerator": 200, "denominator": 1},
        },
        "frame_convention": {
            "body_frame": "sensor_body_right_handed",
            "world_frame": "ENU",
            "gravity_world_mps2": [0.0, 0.0, -9.80665],
            "accelerometer_quantity": "specific_force",
        },
        "units": units,
        "sample_count": len(samples),
        "samples": copy.deepcopy(samples),
    }


def make_manifest(*, execution_mode="causal_online", sensor_sets=None, aids=None):
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.adapter_manifest",
        "schema_version": 1,
        "adapter_id": "test.identity",
        "variant_id": "test.identity.v1",
        "algorithm_name": "Deterministic contract fixture",
        "implementation_version": "fixture-1",
        "execution_mode": execution_mode,
        "supported_sensor_sets": sensor_sets or ["gyro_accel_6d"],
        "supported_aid_types": aids or ["independent_heading"],
        "supported_timestamp_units": ["ns"],
        "supported_sampling_modes": ["uniform", "irregular"],
        "allowed_yaw_gauges": ["unobservable_startup", "independent_heading", "magnetic_reference"],
        "initialization": {
            "orientation_source": "identity",
            "initial_yaw_gauge": "unobservable_startup",
            "uses_truth": False,
            "warmup_policy": "none",
            "reset_clears_all_state": True,
        },
        "output_convention": {
            "quaternion_order": "wxyz",
            "rotation_direction": "body_to_world",
            "reference_world_frame": "ENU",
            "gravity_world_mps2": [0.0, 0.0, -9.80665],
            "accelerometer_quantity": "specific_force",
        },
        "source_fidelity": {
            "classification": "project_implementation",
            "source_uri": "https://example.invalid/contract-fixture",
            "source_revision": "fixture-1",
            "implementation_sha256": "b" * 64,
            "adapter_sha256": "c" * 64,
            "model_sha256": None,
            "license": "test-fixture-only",
        },
    }


class IdentityFixtureAdapter:
    def __init__(self, manifest=None, *, reset_state=True):
        self.manifest = copy.deepcopy(manifest or make_manifest())
        self.reset_state = reset_state
        self.yaw = 0.0
        self.last_timestamp = None

    def reset(self, config):
        self.config = copy.deepcopy(config)
        if self.reset_state:
            self.yaw = 0.0
        self.last_timestamp = None

    def step(self, timestamp, accel_mps2, gyro_rad_s, aid=None):
        if self.last_timestamp is not None:
            dt_s = (timestamp - self.last_timestamp) * 1e-9
            self.yaw += gyro_rad_s[2] * dt_s
        self.last_timestamp = timestamp
        return {
            "timestamp": timestamp,
            "orientation_valid": True,
            "status": "valid",
            "orientation": {
                "quaternion_wxyz": [math.cos(self.yaw / 2), 0.0, 0.0, math.sin(self.yaw / 2)],
                "yaw_gauge": "unobservable_startup",
            },
        }


class ExternalBenchmarkContractTests(unittest.TestCase):
    def setUp(self):
        api_path = ROOT / "external_benchmarks" / "api.py"
        self.assertTrue(api_path.is_file(), "B1 external benchmark API is not implemented yet")
        from external_benchmarks import api

        self.api = api

    def test_versioned_schemas_are_present_and_closed(self):
        schema_dir = ROOT / "external_benchmarks" / "schema"
        for filename in (
            "imu_trial_v1.schema.json",
            "adapter_manifest_v1.schema.json",
            "estimator_output_v1.schema.json",
        ):
            with self.subTest(filename=filename):
                schema = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
                self.assertIn("2020-12", schema["$schema"])
                self.assertEqual(schema["additionalProperties"], False)
                self.assertEqual(schema["properties"]["schema_version"]["const"], 1)

    def test_input_schema_declares_distinct_six_and_nine_axis_branches(self):
        schema = json.loads(
            (ROOT / "external_benchmarks" / "schema" / "imu_trial_v1.schema.json").read_text(encoding="utf-8")
        )
        sensor_modes = {
            branch["if"]["properties"]["sensor_set"]["const"]
            for branch in schema["allOf"]
            if "sensor_set" in branch.get("if", {}).get("properties", {})
        }
        self.assertEqual(sensor_modes, {"gyro_accel_6d", "gyro_accel_mag_9d"})
        self.assertIn("aid", schema["allOf"][1]["then"]["properties"]["samples"]["items"]["required"])

    def test_manifest_schema_requires_execution_and_provenance_identity(self):
        schema = json.loads(
            (ROOT / "external_benchmarks" / "schema" / "adapter_manifest_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["execution_mode"]["enum"], ["causal_online", "offline_batch"])
        source_required = schema["$defs"]["source_fidelity"]["required"]
        self.assertIn("implementation_sha256", source_required)
        self.assertIn("adapter_sha256", source_required)

    def test_valid_six_axis_trial_is_accepted(self):
        self.api.validate_trial(make_trial())

    def test_missing_required_sample_value_is_rejected(self):
        trial = make_trial()
        del trial["samples"][0]["gyro_rad_s"]
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_wrong_declared_unit_is_rejected(self):
        trial = make_trial()
        trial["units"]["accelerometer"] = "g"
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_nonmonotonic_timestamp_is_rejected(self):
        trial = make_trial([sample(0), sample(5_000_000), sample(5_000_000)])
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_uniform_timestamps_must_match_declared_sample_rate(self):
        trial = make_trial()
        trial["timebase"]["nominal_rate_hz"] = {"numerator": 100, "denominator": 1}
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_sample_count_disagreement_is_rejected(self):
        trial = make_trial()
        trial["sample_count"] += 1
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_nonfinite_sensor_value_is_rejected(self):
        trial = make_trial([sample(0, accel=(0.0, float("nan"), 9.80665))])
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_invalid_sample_flag_is_not_silently_treated_as_a_valid_step(self):
        trial = make_trial()
        trial["samples"][1]["valid"] = False
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_nine_axis_trial_requires_magnetometer_on_every_sample(self):
        trial = make_trial(sensor_set="gyro_accel_mag_9d")
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(trial)

    def test_nine_axis_trial_accepts_declared_magnetometer_input(self):
        mag = {
            "kind": "magnetometer",
            "field_uT": [25.0, 0.0, 40.0],
            "units": "uT",
            "source_id": "mag-1",
            "frame": "sensor_body_right_handed",
            "independence": "part_of_sensor_set",
        }
        trial = make_trial(
            [sample(0, aid=mag), sample(5_000_000, aid=mag)],
            sensor_set="gyro_accel_mag_9d",
        )
        self.api.validate_trial(trial)

    def test_six_axis_trial_rejects_magnetometer_disguised_as_aid(self):
        mag = {
            "kind": "magnetometer",
            "field_uT": [25.0, 0.0, 40.0],
            "units": "uT",
            "source_id": "mag-1",
            "frame": "sensor_body_right_handed",
            "independence": "part_of_sensor_set",
        }
        with self.assertRaises(self.api.ContractError):
            self.api.validate_trial(make_trial([sample(0, aid=mag)]))

    def test_six_axis_trial_accepts_explicit_independent_heading_aid(self):
        heading = {
            "kind": "independent_heading",
            "value_rad": 0.25,
            "units": "rad",
            "source_id": "heading-1",
            "reference_frame": "ENU",
            "independence": "independent_of_imu",
        }
        self.api.validate_trial(make_trial([sample(0, aid=heading)]))

    def test_adapter_manifest_requires_provenance_hashes(self):
        manifest = make_manifest()
        manifest["source_fidelity"]["implementation_sha256"] = "not-a-hash"
        with self.assertRaises(self.api.ContractError):
            self.api.validate_adapter_manifest(manifest)

    def test_offline_variant_cannot_run_through_online_step_api(self):
        manifest = make_manifest(execution_mode="offline_batch")
        adapter = IdentityFixtureAdapter(manifest)
        with self.assertRaises(self.api.ContractError):
            self.api.run_trial(adapter, make_trial(), {})

    def test_adapter_without_reset_or_step_is_rejected(self):
        class IncompleteAdapter:
            manifest = make_manifest()

        with self.assertRaises(self.api.ContractError):
            self.api.run_trial(IncompleteAdapter(), make_trial(), {})

    def test_streaming_trial_records_matching_input_and_config_hashes(self):
        trial = make_trial()
        config = {"initial_yaw_rad": 0.0}
        output = self.api.run_trial(IdentityFixtureAdapter(), trial, config)
        self.assertEqual(output["sample_count"], len(trial["samples"]))
        self.assertEqual(output["input_sha256"], self.api.canonical_input_sha256(trial))
        self.assertEqual(output["config_sha256"], self.api.canonical_json_sha256(config))

    def test_output_count_and_timestamps_must_match_input(self):
        trial = make_trial()
        output = self.api.run_trial(IdentityFixtureAdapter(), trial, {})
        output["samples"].pop()
        with self.assertRaises(self.api.ContractError):
            self.api.validate_output_bundle(trial, output, expected_execution_mode="causal_online")

    def test_six_axis_output_cannot_claim_magnetic_north_without_magnetometer(self):
        trial = make_trial()
        output = self.api.run_trial(IdentityFixtureAdapter(), trial, {})
        output["samples"][0]["orientation"]["yaw_gauge"] = "magnetic_reference"
        with self.assertRaises(self.api.ContractError):
            self.api.validate_output_bundle(trial, output, expected_execution_mode="causal_online")

    def test_reset_isolation_checker_detects_state_leakage(self):
        target = make_trial()
        interleaved = make_trial(
            [sample(0, gyro=(0.0, 0.0, 1.0)), sample(5_000_000, gyro=(0.0, 0.0, 1.0))]
        )
        self.api.check_reset_isolation(IdentityFixtureAdapter, target, interleaved, {})
        leaky_factory = lambda: IdentityFixtureAdapter(reset_state=False)
        with self.assertRaises(self.api.ContractError):
            self.api.check_reset_isolation(leaky_factory, target, interleaved, {})

    def test_quaternion_convention_is_body_to_world_and_gravity_is_down_in_enu(self):
        rotate = self.api.rotate_body_to_world
        root_half = math.sqrt(0.5)
        identity = rotate([1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        self.assertEqual(identity, [0.0, 1.0, 0.0])
        world_x = rotate([root_half, 0.0, 0.0, root_half], [1.0, 0.0, 0.0])
        world_y = rotate([root_half, root_half, 0.0, 0.0], [0.0, 1.0, 0.0])
        world_z = rotate([root_half, 0.0, root_half, 0.0], [0.0, 0.0, 1.0])
        for actual, expected in ((world_x, [0.0, 1.0, 0.0]), (world_y, [0.0, 0.0, 1.0]), (world_z, [1.0, 0.0, 0.0])):
            for component, target in zip(actual, expected):
                self.assertAlmostEqual(component, target, places=7)
        negated = rotate([-root_half, 0.0, 0.0, -root_half], [1.0, 0.0, 0.0])
        for component, target in zip(negated, world_x):
            self.assertAlmostEqual(component, target, places=7)
        down_body = self.api.gravity_direction_body([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(down_body, [0.0, 0.0, -1.0])

    def test_global_yaw_does_not_change_body_gravity_direction_for_tilted_attitude(self):
        half_tilt = math.radians(15.0)
        half_yaw = math.radians(45.0)
        q_tilt = [math.cos(half_tilt), math.sin(half_tilt), 0.0, 0.0]
        q_world_yaw = [math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw)]
        w1, x1, y1, z1 = q_world_yaw
        w2, x2, y2, z2 = q_tilt
        q_yaw_then_tilt = [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
        tilt_gravity = self.api.gravity_direction_body(q_tilt)
        yawed_gravity = self.api.gravity_direction_body(q_yaw_then_tilt)
        for component, target in zip(yawed_gravity, tilt_gravity):
            self.assertAlmostEqual(component, target, places=7)


if __name__ == "__main__":
    unittest.main()
