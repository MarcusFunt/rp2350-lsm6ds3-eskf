"""Host-only B1 adapter around official pretrained RIANN causal 6D inference."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.resources
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from external_benchmarks.api import ContractError


TRAINING_EXPOSURE = "BROAD_USED_IN_DEVELOPMENT"
MODEL_SHA256 = "9a38dc4c40dd6c31ef12558337e7affa5382476bbd594fdea3c347f10a67f3d8"
RIANN_SOURCE_SHA256 = "cd6708355059b0a09e6c2947da15362d8d51d334af63d2607f916f4b751a8a7c"
RIANN_INIT_SHA256 = "b71764e218237ec29126a3693d4c85c68fc7b080020b0f33fc3eed4e73aafc94"
_MANIFEST_PATH = Path(__file__).with_name("riann_pretrained_6d_manifest_v1.json")
with _MANIFEST_PATH.open("r", encoding="utf-8") as _manifest_file:
    _MANIFEST: dict[str, Any] = json.load(_manifest_file)


def default_config(
    *, sampling_rate_numerator: int = 100, sampling_rate_denominator: int = 1, timestamp_unit: str = "ns"
) -> dict[str, Any]:
    """Return the fixed-rate, host-only RIANN inference configuration."""
    return {
        "sampling_rate_hz": {
            "numerator": sampling_rate_numerator,
            "denominator": sampling_rate_denominator,
        },
        "timestamp_unit": timestamp_unit,
    }


def annotate_riann_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a RIANN result/summary with its mandatory dataset-exposure label.

    The shared B1 output schema deliberately stays algorithm-neutral and closed.
    This B5 envelope adds the model's training exposure to every persisted
    RIANN-specific output or summary without changing that shared contract.
    """
    if not isinstance(result, Mapping):
        raise ContractError("RIANN result annotation requires a mapping")
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.riann_result",
        "schema_version": 1,
        "training_exposure": TRAINING_EXPOSURE,
        "result": copy.deepcopy(dict(result)),
    }


class RIANNPretrained6DAdapter:
    """Causal online adapter for the official pretrained 6D RIANN model."""

    manifest = _MANIFEST
    training_exposure = TRAINING_EXPOSURE

    def __init__(self) -> None:
        self._model = None
        self._np = None
        self._period_s: float | None = None
        self._nominal_interval_ticks: float | None = None
        self._last_timestamp: int | None = None
        self._configured = False
        self._load_official_runtime()

    @staticmethod
    def _positive_integer(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContractError(f"{label} must be a positive integer")
        return value

    @staticmethod
    def _vector3(value: Sequence[float], label: str) -> tuple[float, float, float]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
            raise ContractError(f"{label} must contain exactly three values")
        result: list[float] = []
        for index, component in enumerate(value):
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise ContractError(f"{label}[{index}] must be a finite number")
            converted = float(component)
            if not math.isfinite(converted):
                raise ContractError(f"{label}[{index}] must be a finite number")
            result.append(converted)
        return result[0], result[1], result[2]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as model_file:
            for block in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _load_official_runtime(self) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
            from riann import RIANN, __version__
        except ImportError as error:  # pragma: no cover - optional reference dependency
            raise RuntimeError(
                "RIANN adapter requires external_benchmarks/references/"
                "requirements-riann-b5-win-cp311.lock.txt"
            ) from error

        versions = {
            "riann": __version__,
            "numpy": np.__version__,
            "onnxruntime": ort.__version__,
        }
        pinned = {"riann": "0.2.0", "numpy": "2.3.2", "onnxruntime": "1.22.1"}
        if versions != pinned:
            raise RuntimeError(f"RIANN B5 runtime versions must be {pinned}; found {versions}")
        if importlib.metadata.version("riann") != pinned["riann"]:
            raise RuntimeError("RIANN package metadata version does not match its official module version")

        package_resources = importlib.resources.files("riann")
        source_hashes = {
            "riann.py": hashlib.sha256(package_resources.joinpath("riann.py").read_bytes()).hexdigest(),
            "__init__.py": hashlib.sha256(package_resources.joinpath("__init__.py").read_bytes()).hexdigest(),
        }
        expected_source_hashes = {"riann.py": RIANN_SOURCE_SHA256, "__init__.py": RIANN_INIT_SHA256}
        if source_hashes != expected_source_hashes:
            raise RuntimeError(
                f"installed RIANN inference source does not match the provenance lock: {source_hashes}"
            )

        model_resource = package_resources.joinpath("riann.onnx")
        if not model_resource.is_file():
            raise RuntimeError("the official riann==0.2.0 package is missing its riann.onnx model")
        with importlib.resources.as_file(model_resource) as model_path:
            actual_model_sha256 = self._sha256(model_path)
            if actual_model_sha256 != MODEL_SHA256:
                raise RuntimeError(
                    f"RIANN ONNX SHA-256 mismatch: expected {MODEL_SHA256}, found {actual_model_sha256}"
                )

            # Keep the official Python inference class and model unchanged,
            # while replacing only its ONNX session with explicit deterministic
            # CPU settings. The class constructor accepts an explicit path;
            # that also avoids its relative-path fallback when installed.
            model = RIANN(str(model_path))
            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.use_deterministic_compute = True
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            model.session = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        if model.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("RIANN runtime did not initialize with CPUExecutionProvider only")

        self._np = np
        self._model = model

    def reset(self, config: Mapping[str, Any]) -> None:
        """Reset the official hidden state and set its documented uniform rate."""
        self._configured = False
        self._period_s = None
        self._nominal_interval_ticks = None
        self._last_timestamp = None
        if not isinstance(config, Mapping) or set(config) != {"sampling_rate_hz", "timestamp_unit"}:
            raise ContractError("RIANN config fields must be exactly sampling_rate_hz and timestamp_unit")
        rate = config["sampling_rate_hz"]
        if not isinstance(rate, Mapping) or set(rate) != {"numerator", "denominator"}:
            raise ContractError("sampling_rate_hz must contain numerator and denominator")
        numerator = self._positive_integer(rate["numerator"], "sampling_rate_hz.numerator")
        denominator = self._positive_integer(rate["denominator"], "sampling_rate_hz.denominator")
        if math.gcd(numerator, denominator) != 1:
            raise ContractError("sampling_rate_hz must be a reduced rational")
        unit = config["timestamp_unit"]
        if not isinstance(unit, str) or unit not in {"ns", "us"}:
            raise ContractError("timestamp_unit must be 'ns' or 'us'")

        try:
            period_s = denominator / numerator
            sample_rate_hz = numerator / denominator
        except OverflowError as error:
            raise ContractError("sampling rate is outside the supported numeric range") from error
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ContractError("sampling rate must imply a finite positive sample period")
        # RIANN's published time-aware network training/evaluation covers
        # 50–500 Hz. Fail closed outside that range instead of extrapolating
        # silently into an undocumented model regime.
        if not 50.0 <= sample_rate_hz <= 500.0:
            raise ContractError("the pinned RIANN variant supports uniform rates from 50 through 500 Hz")
        ticks_per_second = 1_000_000_000 if unit == "ns" else 1_000_000
        nominal_interval_ticks = ticks_per_second * denominator / numerator
        if not math.isfinite(nominal_interval_ticks) or nominal_interval_ticks < 1.0:
            raise ContractError("configured rate cannot be represented by the timestamp unit")

        assert self._model is not None
        self._model.reset_state()
        self._model.set_sampling_rate(sample_rate_hz)
        self._period_s = period_s
        self._nominal_interval_ticks = nominal_interval_ticks
        self._configured = True

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float],
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process one causal sample through official ``RIANN.predict_step``."""
        if not self._configured or self._model is None or self._np is None:
            raise ContractError("reset(config) must be called before the first RIANN step")
        if aid is not None:
            raise ContractError("the pretrained RIANN variant accepts no heading or magnetometer aid")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ContractError("timestamp must be a nonnegative integer")
        accel = self._vector3(accel_mps2, "accel_mps2")
        gyro = self._vector3(gyro_rad_s, "gyro_rad_s")
        if self._last_timestamp is not None:
            interval = timestamp - self._last_timestamp
            if interval <= 0:
                raise ContractError("timestamps must be strictly increasing")
            assert self._nominal_interval_ticks is not None
            if abs(interval - self._nominal_interval_ticks) > 1.0:
                raise ContractError("RIANN requires timestamps at its configured uniform sampling rate")

        accel_array = self._np.asarray(accel, dtype=self._np.float32)
        gyro_array = self._np.asarray(gyro, dtype=self._np.float32)
        quaternion = self._model.predict_step(accel_array, gyro_array)
        quaternion_wxyz = [float(value) for value in quaternion]
        if len(quaternion_wxyz) != 4 or not all(math.isfinite(value) for value in quaternion_wxyz):
            raise RuntimeError("official RIANN emitted a non-finite or malformed quaternion")
        norm = math.sqrt(sum(value * value for value in quaternion_wxyz))
        if abs(norm - 1.0) > 1e-3:
            raise RuntimeError(f"official RIANN emitted a non-unit quaternion (norm={norm})")
        self._last_timestamp = timestamp
        return {
            "timestamp": timestamp,
            "orientation_valid": True,
            "status": "valid",
            "orientation": {
                "quaternion_wxyz": quaternion_wxyz,
                "yaw_gauge": "unobservable_startup",
            },
        }
