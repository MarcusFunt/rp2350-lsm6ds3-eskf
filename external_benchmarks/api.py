"""Versioned, firmware-independent host contract for estimator adapters.

This module deliberately imports no production firmware code. The JSON Schemas
are the interchange contract; these functions enforce streaming and
cross-record invariants that JSON Schema cannot express by itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, TypeAlias
from urllib.parse import urlparse


SCHEMA_VERSION = 1
TRIAL_SCHEMA_ID = "org.marcusfunt.external_benchmarks.imu_trial"
MANIFEST_SCHEMA_ID = "org.marcusfunt.external_benchmarks.adapter_manifest"
OUTPUT_SCHEMA_ID = "org.marcusfunt.external_benchmarks.estimator_output"
SENSOR_SETS = frozenset(("gyro_accel_6d", "gyro_accel_mag_9d"))
AID_TYPES = frozenset(("independent_heading", "magnetometer"))
EXECUTION_MODES = frozenset(("causal_online", "offline_batch"))
YAW_GAUGES = frozenset(
    ("unobservable_startup", "independent_heading", "magnetic_reference", "provided_initial_yaw")
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GRAVITY_ENU = (0.0, 0.0, -9.80665)

Vector3: TypeAlias = tuple[float, float, float]
JsonObject: TypeAlias = Mapping[str, Any]


class ContractError(ValueError):
    """Raised when a trial, adapter declaration, or result breaks the contract."""


class FilterAdapter(Protocol):
    """One-step causal adapter API, independent of the target firmware API."""

    manifest: JsonObject

    def reset(self, config: JsonObject) -> None:
        """Start a fresh trial and clear every algorithm and wrapper state."""

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float],
        gyro_rad_s: Sequence[float],
        aid: JsonObject | None = None,
    ) -> JsonObject:
        """Consume one causal sample and return its orientation/validity record."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{label} keys must be strings")
    return value


def _keys(value: Mapping[str, Any], required: set[str], optional: set[str], label: str) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise ContractError(f"{label} is missing required fields: {sorted(missing)}")
    if unknown:
        raise ContractError(f"{label} has unknown fields: {sorted(unknown)}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{label} must be a finite number")
    return float(value)


def _vector(value: Any, label: str, length: int = 3) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ContractError(f"{label} must contain exactly {length} values")
    return tuple(_finite(component, f"{label}[{index}]") for index, component in enumerate(value))


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _exact_enum(value: Any, choices: frozenset[str] | set[str] | tuple[str, ...], label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ContractError(f"{label} must be one of {sorted(choices)}")
    return value


def _json_ready(value: Any) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ContractError(f"value is not strict finite JSON: {error}") from error


def canonical_json_sha256(value: Any) -> str:
    """Hash a stable UTF-8 JSON encoding; NaN and non-JSON values are rejected."""
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError(f"cannot hash non-finite or non-JSON value: {error}") from error
    return hashlib.sha256(payload).hexdigest()


def _validate_aid(aid: Any, sensor_set: str, label: str) -> str:
    aid = _mapping(aid, label)
    kind = aid.get("kind")
    if kind == "independent_heading":
        _keys(
            aid,
            {"kind", "value_rad", "units", "source_id", "reference_frame", "independence"},
            set(),
            label,
        )
        _finite(aid["value_rad"], f"{label}.value_rad")
        if aid["units"] != "rad" or aid["reference_frame"] != "ENU" or aid["independence"] != "independent_of_imu":
            raise ContractError(f"{label} must declare rad, ENU, and independence from the IMU")
        _text(aid["source_id"], f"{label}.source_id")
        if sensor_set != "gyro_accel_6d":
            raise ContractError("independent heading aid is only accepted by the 6D trial profile")
        return kind
    if kind == "magnetometer":
        _keys(
            aid,
            {"kind", "field_uT", "units", "source_id", "frame", "independence"},
            set(),
            label,
        )
        _vector(aid["field_uT"], f"{label}.field_uT")
        if (
            aid["units"] != "uT"
            or aid["frame"] != "sensor_body_right_handed"
            or aid["independence"] != "part_of_sensor_set"
        ):
            raise ContractError(f"{label} must declare uT in the sensor body frame as part of the 9D sensor set")
        _text(aid["source_id"], f"{label}.source_id")
        if sensor_set != "gyro_accel_mag_9d":
            raise ContractError("magnetometer aid changes the trial to 9D and is forbidden in a 6D trial")
        return kind
    raise ContractError(f"{label}.kind must be an explicitly supported aid type")


def validate_trial(trial: JsonObject) -> None:
    """Validate a complete, single-trial v1 input before an adapter sees it."""
    trial = _mapping(trial, "trial")
    required = {
        "schema_id", "schema_version", "trial_id", "source_id", "source_artifact_sha256",
        "sensor_set", "timebase", "frame_convention", "units", "sample_count", "samples",
    }
    _keys(trial, required, set(), "trial")
    if trial["schema_id"] != TRIAL_SCHEMA_ID or trial["schema_version"] != SCHEMA_VERSION:
        raise ContractError("trial schema_id/schema_version is not imu_trial v1")
    _text(trial["trial_id"], "trial.trial_id")
    _text(trial["source_id"], "trial.source_id")
    _hash(trial["source_artifact_sha256"], "trial.source_artifact_sha256")
    sensor_set = _exact_enum(trial["sensor_set"], SENSOR_SETS, "trial.sensor_set")

    timebase = _mapping(trial["timebase"], "trial.timebase")
    _keys(timebase, {"timestamp_unit", "sampling_mode", "nominal_rate_hz"}, set(), "trial.timebase")
    timestamp_unit = _exact_enum(timebase["timestamp_unit"], {"ns", "us"}, "timebase.timestamp_unit")
    sampling_mode = _exact_enum(timebase["sampling_mode"], {"uniform", "irregular"}, "timebase.sampling_mode")
    rate = timebase["nominal_rate_hz"]
    if sampling_mode == "uniform":
        rate = _mapping(rate, "timebase.nominal_rate_hz")
        _keys(rate, {"numerator", "denominator"}, set(), "timebase.nominal_rate_hz")
        numerator = _integer(rate["numerator"], "nominal rate numerator", 1)
        denominator = _integer(rate["denominator"], "nominal rate denominator", 1)
        if math.gcd(numerator, denominator) != 1:
            raise ContractError("nominal_rate_hz must be in reduced rational form")
    elif rate is not None:
        raise ContractError("irregular sampling must declare nominal_rate_hz as null")

    frame = _mapping(trial["frame_convention"], "trial.frame_convention")
    _keys(frame, {"body_frame", "world_frame", "gravity_world_mps2", "accelerometer_quantity"}, set(), "frame_convention")
    if frame["body_frame"] != "sensor_body_right_handed" or frame["world_frame"] != "ENU":
        raise ContractError("input frames must be right-handed sensor body and ENU world")
    if _vector(frame["gravity_world_mps2"], "frame_convention.gravity_world_mps2") != _GRAVITY_ENU:
        raise ContractError("ENU gravity must point down as [0, 0, -9.80665] m/s^2")
    if frame["accelerometer_quantity"] != "specific_force":
        raise ContractError("accelerometer input must be specific force")

    units = _mapping(trial["units"], "trial.units")
    unit_required = {"timestamp", "accelerometer", "gyroscope"}
    if sensor_set == "gyro_accel_mag_9d":
        unit_required.add("magnetometer")
    else:
        if "magnetometer" in units:
            raise ContractError("6D input must not declare magnetometer units")
    _keys(units, unit_required, set(), "trial.units")
    expected_units = {"timestamp": timestamp_unit, "accelerometer": "m/s^2", "gyroscope": "rad/s"}
    if sensor_set == "gyro_accel_mag_9d":
        expected_units["magnetometer"] = "uT"
    if dict(units) != expected_units:
        raise ContractError(f"input units must be exactly {expected_units}")

    sample_count = _integer(trial["sample_count"], "trial.sample_count", 1)
    samples = trial["samples"]
    if not isinstance(samples, list) or len(samples) != sample_count:
        raise ContractError("sample_count must equal the number of sample records")
    timestamps: list[int] = []
    for index, raw_sample in enumerate(samples):
        label = f"samples[{index}]"
        raw_sample = _mapping(raw_sample, label)
        _keys(raw_sample, {"timestamp", "accel_mps2", "gyro_rad_s", "valid"}, {"aid"}, label)
        timestamp = _integer(raw_sample["timestamp"], f"{label}.timestamp")
        timestamps.append(timestamp)
        _vector(raw_sample["accel_mps2"], f"{label}.accel_mps2")
        _vector(raw_sample["gyro_rad_s"], f"{label}.gyro_rad_s")
        if raw_sample["valid"] is not True:
            raise ContractError(f"{label}.valid must be true for the basic step API; invalid samples need an explicit protocol")
        if "aid" in raw_sample:
            _validate_aid(raw_sample["aid"], sensor_set, f"{label}.aid")
        if sensor_set == "gyro_accel_mag_9d":
            if "aid" not in raw_sample or raw_sample["aid"].get("kind") != "magnetometer":
                raise ContractError(f"{label} must contain its declared magnetometer sample in 9D mode")
        if sensor_set == "gyro_accel_6d" and raw_sample.get("aid", {}).get("kind") == "magnetometer":
            raise ContractError(f"{label} contains magnetometer data in a 6D trial")

    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ContractError("sample timestamps must be strictly increasing")
    if sampling_mode == "uniform" and len(timestamps) > 1:
        ticks_per_second = 1_000_000_000 if timestamp_unit == "ns" else 1_000_000
        ideal_interval = ticks_per_second * denominator / numerator
        intervals = [right - left for left, right in zip(timestamps, timestamps[1:])]
        if any(abs(interval - ideal_interval) > 1.0 for interval in intervals) or max(intervals) - min(intervals) > 1:
            raise ContractError("uniform timestamps disagree with the declared rational sample rate")


def validate_adapter_manifest(manifest: JsonObject) -> None:
    """Validate a versioned adapter identity, capabilities and fidelity record."""
    manifest = _mapping(manifest, "adapter manifest")
    required = {
        "schema_id", "schema_version", "adapter_id", "variant_id", "algorithm_name",
        "implementation_version", "execution_mode", "supported_sensor_sets", "supported_aid_types",
        "supported_timestamp_units", "supported_sampling_modes", "allowed_yaw_gauges",
        "initialization", "output_convention", "source_fidelity",
    }
    _keys(manifest, required, set(), "adapter manifest")
    if manifest["schema_id"] != MANIFEST_SCHEMA_ID or manifest["schema_version"] != SCHEMA_VERSION:
        raise ContractError("adapter manifest schema_id/schema_version is not adapter_manifest v1")
    for key in ("adapter_id", "variant_id", "algorithm_name", "implementation_version"):
        _text(manifest[key], f"adapter manifest.{key}")
    _exact_enum(manifest["execution_mode"], EXECUTION_MODES, "execution_mode")

    list_specs = {
        "supported_sensor_sets": SENSOR_SETS,
        "supported_aid_types": AID_TYPES,
        "supported_timestamp_units": {"ns", "us"},
        "supported_sampling_modes": {"uniform", "irregular"},
        "allowed_yaw_gauges": YAW_GAUGES,
    }
    for key, allowed in list_specs.items():
        values = manifest[key]
        if not isinstance(values, list) or (key != "supported_aid_types" and not values):
            raise ContractError(f"adapter manifest.{key} must be a {'possibly empty' if key == 'supported_aid_types' else 'non-empty'} list")
        for value in values:
            _exact_enum(value, allowed, f"adapter manifest.{key} item")
        if len(values) != len(set(values)):
            raise ContractError(f"adapter manifest.{key} must not contain duplicates")

    initialization = _mapping(manifest["initialization"], "adapter manifest.initialization")
    _keys(
        initialization,
        {"orientation_source", "initial_yaw_gauge", "uses_truth", "warmup_policy", "reset_clears_all_state"},
        set(),
        "initialization",
    )
    _exact_enum(initialization["orientation_source"], {"identity", "gravity_aligned_zero_yaw", "provided_config", "algorithm_default"}, "orientation_source")
    _exact_enum(initialization["initial_yaw_gauge"], YAW_GAUGES, "initial_yaw_gauge")
    if not isinstance(initialization["uses_truth"], bool):
        raise ContractError("initialization.uses_truth must be boolean")
    _text(initialization["warmup_policy"], "initialization.warmup_policy")
    if initialization["reset_clears_all_state"] is not True:
        raise ContractError("adapter reset must declare that it clears all trial state")

    convention = _mapping(manifest["output_convention"], "adapter manifest.output_convention")
    _keys(
        convention,
        {"quaternion_order", "rotation_direction", "reference_world_frame", "gravity_world_mps2", "accelerometer_quantity"},
        set(),
        "output_convention",
    )
    if (
        convention["quaternion_order"] != "wxyz"
        or convention["rotation_direction"] != "body_to_world"
        or convention["reference_world_frame"] != "ENU"
        or convention["accelerometer_quantity"] != "specific_force"
        or _vector(convention["gravity_world_mps2"], "output_convention.gravity_world_mps2") != _GRAVITY_ENU
    ):
        raise ContractError("output convention must be scalar-first body-to-world in ENU with down gravity and specific force")

    fidelity = _mapping(manifest["source_fidelity"], "adapter manifest.source_fidelity")
    _keys(
        fidelity,
        {"classification", "source_uri", "source_revision", "implementation_sha256", "adapter_sha256", "model_sha256", "license"},
        set(),
        "source_fidelity",
    )
    _exact_enum(
        fidelity["classification"],
        {"official_unmodified", "official_wrapper_only", "faithful_reimplementation", "internal_historical", "project_implementation"},
        "source_fidelity.classification",
    )
    source_uri = _text(fidelity["source_uri"], "source_fidelity.source_uri")
    if not urlparse(source_uri).scheme:
        raise ContractError("source_fidelity.source_uri must be an absolute URI")
    _text(fidelity["source_revision"], "source_fidelity.source_revision")
    _hash(fidelity["implementation_sha256"], "source_fidelity.implementation_sha256")
    _hash(fidelity["adapter_sha256"], "source_fidelity.adapter_sha256")
    if fidelity["model_sha256"] is not None:
        _hash(fidelity["model_sha256"], "source_fidelity.model_sha256")
    _text(fidelity["license"], "source_fidelity.license")


def _validate_adapter_for_trial(trial: Mapping[str, Any], manifest: Mapping[str, Any], *, allow_truth: bool) -> None:
    if trial["sensor_set"] not in manifest["supported_sensor_sets"]:
        raise ContractError("adapter does not support this 6D/9D sensor set")
    timebase = trial["timebase"]
    if timebase["timestamp_unit"] not in manifest["supported_timestamp_units"]:
        raise ContractError("adapter does not support this timestamp unit")
    if timebase["sampling_mode"] not in manifest["supported_sampling_modes"]:
        raise ContractError("adapter does not support this sampling mode")
    used_aids = {
        sample["aid"]["kind"]
        for sample in trial["samples"]
        if isinstance(sample.get("aid"), Mapping)
    }
    if not used_aids.issubset(set(manifest["supported_aid_types"])):
        raise ContractError(f"adapter does not support declared aid types: {sorted(used_aids - set(manifest['supported_aid_types']))}")
    if manifest["initialization"]["uses_truth"] and not allow_truth:
        raise ContractError("truth-based initialization is prohibited unless explicitly enabled for a labeled oracle run")


def _validate_optional_state(record: Mapping[str, Any], label: str) -> None:
    if "bias" in record and record["bias"] is not None:
        bias = _mapping(record["bias"], f"{label}.bias")
        _keys(bias, {"accelerometer_mps2", "gyroscope_rad_s"}, set(), f"{label}.bias")
        _vector(bias["accelerometer_mps2"], f"{label}.bias.accelerometer_mps2")
        _vector(bias["gyroscope_rad_s"], f"{label}.bias.gyroscope_rad_s")
    if "covariance" in record and record["covariance"] is not None:
        covariance = _mapping(record["covariance"], f"{label}.covariance")
        _keys(covariance, {"state_order", "state_units", "representation", "values_row_major"}, set(), f"{label}.covariance")
        state_order, state_units = covariance["state_order"], covariance["state_units"]
        values = covariance["values_row_major"]
        if not isinstance(state_order, list) or not state_order or not isinstance(state_units, list):
            raise ContractError(f"{label}.covariance must declare state order and units")
        if len(state_order) != len(state_units) or any(not isinstance(item, str) or not item for item in state_order + state_units):
            raise ContractError(f"{label}.covariance state order and units must have matching non-empty entries")
        if covariance["representation"] != "row_major" or not isinstance(values, list) or len(values) != len(state_order) ** 2:
            raise ContractError(f"{label}.covariance row-major value count must equal state dimension squared")
        for index, value in enumerate(values):
            _finite(value, f"{label}.covariance.values_row_major[{index}]")
    if "navigation" in record and record["navigation"] is not None:
        navigation = _mapping(record["navigation"], f"{label}.navigation")
        _keys(navigation, {"position_enu_m", "velocity_enu_m_s"}, set(), f"{label}.navigation")
        _vector(navigation["position_enu_m"], f"{label}.navigation.position_enu_m")
        _vector(navigation["velocity_enu_m_s"], f"{label}.navigation.velocity_enu_m_s")
    if "processing_time_ns" in record and record["processing_time_ns"] is not None:
        _integer(record["processing_time_ns"], f"{label}.processing_time_ns")


def validate_output_bundle(
    trial: JsonObject,
    bundle: JsonObject,
    *,
    expected_execution_mode: str = "causal_online",
) -> None:
    """Check identity, temporal alignment, validity, and optional states."""
    validate_trial(trial)
    bundle = _mapping(bundle, "output bundle")
    required = {
        "schema_id", "schema_version", "trial_id", "source_id", "sensor_set", "execution_mode",
        "sample_count", "input_sha256", "config_sha256", "adapter_manifest", "samples",
    }
    _keys(bundle, required, set(), "output bundle")
    if bundle["schema_id"] != OUTPUT_SCHEMA_ID or bundle["schema_version"] != SCHEMA_VERSION:
        raise ContractError("output schema_id/schema_version is not estimator_output v1")
    manifest = bundle["adapter_manifest"]
    validate_adapter_manifest(manifest)
    expected_execution_mode = _exact_enum(expected_execution_mode, EXECUTION_MODES, "expected_execution_mode")
    execution_mode = _exact_enum(bundle["execution_mode"], EXECUTION_MODES, "output.execution_mode")
    if execution_mode != expected_execution_mode or execution_mode != manifest["execution_mode"]:
        raise ContractError("output, adapter and requested execution modes must match exactly")
    _validate_adapter_for_trial(trial, manifest, allow_truth=False)
    if bundle["trial_id"] != trial["trial_id"] or bundle["source_id"] != trial["source_id"]:
        raise ContractError("output trial/source identity does not match input")
    if bundle["sensor_set"] != trial["sensor_set"]:
        raise ContractError("output 6D/9D mode does not match input mode")
    sample_count = _integer(bundle["sample_count"], "output.sample_count", 1)
    output_samples = bundle["samples"]
    if not isinstance(output_samples, list) or sample_count != len(trial["samples"]) or len(output_samples) != sample_count:
        raise ContractError("output sample count must equal both the declared and input sample counts")
    if bundle["input_sha256"] != canonical_input_sha256(trial):
        raise ContractError("output common input hash does not match the canonical input trial")
    _hash(bundle["config_sha256"], "output.config_sha256")

    trial_aids = {
        sample["aid"]["kind"]
        for sample in trial["samples"]
        if isinstance(sample.get("aid"), Mapping)
    }
    manifest_yaw_gauges = set(manifest["allowed_yaw_gauges"])
    for index, (input_sample, output_sample) in enumerate(zip(trial["samples"], output_samples)):
        label = f"output.samples[{index}]"
        output_sample = _mapping(output_sample, label)
        required_sample = {"sample_index", "timestamp", "orientation_valid", "status", "orientation"}
        optional_sample = {"bias", "covariance", "navigation", "processing_time_ns"}
        _keys(output_sample, required_sample, optional_sample, label)
        if _integer(output_sample["sample_index"], f"{label}.sample_index") != index:
            raise ContractError(f"{label}.sample_index is not the expected zero-based index")
        timestamp = _integer(output_sample["timestamp"], f"{label}.timestamp")
        if timestamp != input_sample["timestamp"]:
            raise ContractError(f"{label}.timestamp does not match its input sample")
        valid = output_sample["orientation_valid"]
        if not isinstance(valid, bool):
            raise ContractError(f"{label}.orientation_valid must be boolean")
        status = _exact_enum(output_sample["status"], {"valid", "warming_up", "invalid", "failed"}, f"{label}.status")
        orientation = output_sample["orientation"]
        if valid:
            if status != "valid":
                raise ContractError(f"{label} valid orientation must have status='valid'")
            orientation = _mapping(orientation, f"{label}.orientation")
            _keys(orientation, {"quaternion_wxyz", "yaw_gauge"}, set(), f"{label}.orientation")
            quaternion = _vector(orientation["quaternion_wxyz"], f"{label}.orientation.quaternion_wxyz", 4)
            norm = math.sqrt(sum(component * component for component in quaternion))
            if abs(norm - 1.0) > 1e-3:
                raise ContractError(f"{label} quaternion norm must be within 1e-3 of one")
            yaw_gauge = _exact_enum(orientation["yaw_gauge"], YAW_GAUGES, f"{label}.orientation.yaw_gauge")
            if yaw_gauge not in manifest_yaw_gauges:
                raise ContractError(f"{label} yaw gauge is not declared by the adapter manifest")
            if yaw_gauge == "independent_heading" and "independent_heading" not in trial_aids:
                raise ContractError(f"{label} claims independent heading without heading measurements in this trial")
            if yaw_gauge == "magnetic_reference" and trial["sensor_set"] != "gyro_accel_mag_9d":
                raise ContractError(f"{label} claims magnetic reference without a 9D magnetometer stream")
            if yaw_gauge == "provided_initial_yaw" and manifest["initialization"]["orientation_source"] != "provided_config":
                raise ContractError(f"{label} claims configured initial yaw without that initialization declaration")
        elif orientation is not None or status == "valid":
            raise ContractError(f"{label} invalid output must have null orientation and a non-valid status")
        _validate_optional_state(output_sample, label)


def run_trial(adapter: FilterAdapter, trial: JsonObject, config: JsonObject) -> dict[str, Any]:
    """Replay one trial through a causal adapter, resetting it before the first sample."""
    validate_trial(trial)
    manifest = _mapping(getattr(adapter, "manifest", None), "adapter.manifest")
    validate_adapter_manifest(manifest)
    if not callable(getattr(adapter, "reset", None)) or not callable(getattr(adapter, "step", None)):
        raise ContractError("causal adapter must implement reset(config) and step(timestamp, accel, gyro, aid)")
    if manifest["execution_mode"] != "causal_online":
        raise ContractError("offline_batch variants cannot be invoked through the online step API")
    _validate_adapter_for_trial(trial, manifest, allow_truth=False)
    config = _mapping(config, "adapter config")
    _json_ready(config)
    config_hash = canonical_json_sha256(config)
    adapter.reset(copy.deepcopy(dict(config)))
    outputs: list[dict[str, Any]] = []
    for index, sample in enumerate(trial["samples"]):
        step_output = adapter.step(
            sample["timestamp"],
            tuple(sample["accel_mps2"]),
            tuple(sample["gyro_rad_s"]),
            copy.deepcopy(sample.get("aid")),
        )
        step_output = _mapping(step_output, f"adapter.step output[{index}]")
        if "sample_index" in step_output:
            raise ContractError("adapter.step must not assign sample_index; the runner owns stream indexing")
        outputs.append({"sample_index": index, **dict(step_output)})
    bundle = {
        "schema_id": OUTPUT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "trial_id": trial["trial_id"],
        "source_id": trial["source_id"],
        "sensor_set": trial["sensor_set"],
        "execution_mode": manifest["execution_mode"],
        "sample_count": trial["sample_count"],
        "input_sha256": canonical_input_sha256(trial),
        "config_sha256": config_hash,
        "adapter_manifest": copy.deepcopy(dict(manifest)),
        "samples": outputs,
    }
    validate_output_bundle(trial, bundle, expected_execution_mode="causal_online")
    return bundle


def check_reset_isolation(
    adapter_factory: Callable[[], FilterAdapter],
    target_trial: JsonObject,
    interleaved_trial: JsonObject,
    config: JsonObject,
) -> None:
    """Fail if replaying a trial after another trial differs from a fresh adapter."""
    fresh_output = run_trial(adapter_factory(), target_trial, config)
    reused = adapter_factory()
    run_trial(reused, interleaved_trial, config)
    after_other_trial = run_trial(reused, target_trial, config)
    if canonical_json_sha256(fresh_output["samples"]) != canonical_json_sha256(after_other_trial["samples"]):
        raise ContractError("adapter state leaked across trials despite reset(config)")


def _normalized_quaternion(quaternion_wxyz: Sequence[float]) -> tuple[float, float, float, float]:
    values = _vector(quaternion_wxyz, "quaternion_wxyz", 4)
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ContractError("quaternion must have finite, nonzero norm")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def rotate_body_to_world(quaternion_wxyz: Sequence[float], vector_body: Sequence[float]) -> list[float]:
    """Rotate a body-frame vector into right-handed ENU using scalar-first q_WB."""
    w, x, y, z = _normalized_quaternion(quaternion_wxyz)
    vx, vy, vz = _vector(vector_body, "vector_body")
    # q * [0,v] * conjugate(q), expressed without allocating quaternion objects.
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return [
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    ]


def gravity_direction_body(quaternion_wxyz: Sequence[float]) -> list[float]:
    """Return unit down-gravity expressed in body coordinates for q_WB and ENU."""
    w, x, y, z = _normalized_quaternion(quaternion_wxyz)
    return rotate_body_to_world((w, -x, -y, -z), (0.0, 0.0, -1.0))


def canonical_input_sha256(trial: JsonObject) -> str:
    """Hash a validated, normalized trial payload for same-input comparisons."""
    validate_trial(trial)
    return canonical_json_sha256(trial)
