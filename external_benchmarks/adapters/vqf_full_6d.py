"""Thin adapter for the official, causal, full 6D VQF implementation.

The dependency's ``vqf.VQF`` is its Cython wrapper around the official C++
implementation. This module calls one online ``update(gyr, acc)`` per sample
and exposes only ``getQuat6D``. It intentionally has no firmware imports and
does not call magnetic or offline update paths.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from external_benchmarks.api import ContractError


_MANIFEST_PATH = Path(__file__).with_name("vqf_full_6d_manifest_v1.json")
with _MANIFEST_PATH.open("r", encoding="utf-8") as _manifest_file:
    _MANIFEST: dict[str, Any] = json.load(_manifest_file)


class VQFFull6DAdapter:
    """B1-compatible sample-by-sample host adapter for full VQF 6D mode."""

    manifest = _MANIFEST

    def __init__(self) -> None:
        self._filter = None
        self._period_s: float | None = None
        self._ticks_per_second: int | None = None
        self._last_timestamp: int | None = None
        self._nominal_interval_ticks: float | None = None
        self._last_diagnostics: dict[str, Any] | None = None

    @staticmethod
    def _positive_integer(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContractError(f"{label} must be a positive integer")
        return value

    @staticmethod
    def _vector3(value: Sequence[float], label: str) -> tuple[float, float, float]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
            raise ContractError(f"{label} must contain exactly three values")
        components: list[float] = []
        for index, component in enumerate(value):
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise ContractError(f"{label}[{index}] must be a finite number")
            converted = float(component)
            if not math.isfinite(converted):
                raise ContractError(f"{label}[{index}] must be a finite number")
            components.append(converted)
        return components[0], components[1], components[2]

    def reset(self, config: Mapping[str, Any]) -> None:
        """Reset all filter state and set fixed per-trial sample timing.

        Config is deliberately closed and expressed in the shared benchmark
        contract's units. VQF requires uniform sampling for this online profile.
        """
        # Invalidate the previous trial before validating the new config, so a
        # failed reset cannot accidentally leave a stale filter callable.
        self._filter = None
        self._period_s = None
        self._ticks_per_second = None
        self._last_timestamp = None
        self._nominal_interval_ticks = None
        self._last_diagnostics = None
        if not isinstance(config, Mapping):
            raise ContractError("VQF config must be an object")
        required = {"sampling_rate_hz", "timestamp_unit"}
        if set(config) != required:
            raise ContractError(f"VQF config fields must be exactly {sorted(required)}")
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

        # Import lazily so the shared, dependency-free benchmark API remains
        # importable when the optional reference package is not installed.
        try:
            import vqf
        except ImportError as error:  # pragma: no cover - exercised without optional dependency
            raise RuntimeError(
                "VQF adapter requires the pinned optional dependencies in "
                "external_benchmarks/requirements-vqf-b3.txt"
            ) from error

        try:
            period_s = denominator / numerator
        except OverflowError as error:
            raise ContractError("sampling_rate_hz is outside the supported numeric range") from error
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ContractError("sampling_rate_hz must imply a finite positive sample period")
        ticks_per_second = 1_000_000_000 if unit == "ns" else 1_000_000
        nominal_interval_ticks = ticks_per_second * denominator / numerator
        if not math.isfinite(nominal_interval_ticks) or nominal_interval_ticks < 1.0:
            raise ContractError("configured rate cannot be represented by the timestamp unit")
        # A new official object is equivalent to VQF.resetState() and ensures
        # the new sample rate is used to recompute all filter coefficients.
        filter_instance = vqf.VQF(period_s)
        self._filter = filter_instance
        self._period_s = period_s
        self._ticks_per_second = ticks_per_second
        self._nominal_interval_ticks = nominal_interval_ticks

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float],
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process one causal 6D sample and return the official 6D quaternion."""
        if self._filter is None or self._period_s is None:
            raise ContractError("reset(config) must be called before the first VQF step")
        if aid is not None:
            raise ContractError("full 6D VQF does not accept heading or magnetometer aids in this adapter")
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
                raise ContractError("VQF online adapter requires configured uniform timestamps")
        self._last_timestamp = timestamp

        # VQF documents gyro in rad/s and accelerometer in m/s^2. Omitting
        # mag invokes full VQF's 6D path; getQuat6D cannot consume 9D heading.
        import numpy as np

        self._filter.update(np.asarray(gyro, dtype=np.float64), np.asarray(accel, dtype=np.float64))
        quaternion = self._filter.getQuat6D()
        quaternion_wxyz = [float(value) for value in quaternion]

        bias_rad_s, bias_sigma_rad_s = self._filter.getBiasEstimate()
        self._last_diagnostics = {
            "gyroscope_bias_rad_s": [float(value) for value in bias_rad_s],
            "gyroscope_bias_uncertainty_std_rad_s": float(bias_sigma_rad_s),
            "rest_detected": bool(self._filter.getRestDetected()),
        }
        return {
            "timestamp": timestamp,
            "orientation_valid": True,
            "status": "valid",
            "orientation": {
                "quaternion_wxyz": quaternion_wxyz,
                "yaw_gauge": "unobservable_startup",
            },
        }

    def diagnostics(self) -> dict[str, Any] | None:
        """Return VQF's supported gyro-bias/rest diagnostics for the latest step.

        This is adapter-specific telemetry, not a shared estimator-output bias
        record. VQF does not estimate accelerometer bias.
        """
        if self._last_diagnostics is None:
            return None
        return json.loads(json.dumps(self._last_diagnostics, allow_nan=False))
