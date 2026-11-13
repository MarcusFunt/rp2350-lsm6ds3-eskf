"""Thin B1 adapter around the official qmt Seel/OriEstIMU streaming block.

The pinned qmt 0.2.4 distribution contains the author-maintained Cython/C++
OriEstIMU. A fresh block is constructed for every trial because upstream's
documented ``command(['reset'])`` resets quaternion and bias but leaves its
startup sample counter and raw-acceleration rating window intact.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from external_benchmarks.api import ContractError


DEFAULT_PARAMETERS: dict[str, Any] = {
    "tauAcc": 2.0,
    "tauMag": 2.0,
    "zeta": 0.0,
    "accRating": 1.0,
    "initQuat": [1.0, 0.0, 0.0, 0.0],
    "initBias": [0.0, 0.0, 0.0],
}
_BLOCK_PARAMETERS = {key: DEFAULT_PARAMETERS[key] for key in ("tauAcc", "tauMag", "zeta", "accRating")}
_MANIFEST_PATH = Path(__file__).with_name("qmt_oriestimu_6d_manifest_v1.json")
with _MANIFEST_PATH.open("r", encoding="utf-8") as _manifest_file:
    _MANIFEST: dict[str, Any] = json.load(_manifest_file)


def default_config(
    *, sampling_rate_numerator: int = 100, sampling_rate_denominator: int = 1, timestamp_unit: str = "ns"
) -> dict[str, Any]:
    """Return a JSON-ready config for the predeclared causal baseline."""
    return {
        "sampling_rate_hz": {"numerator": sampling_rate_numerator, "denominator": sampling_rate_denominator},
        "timestamp_unit": timestamp_unit,
        "parameters": json.loads(json.dumps(DEFAULT_PARAMETERS, allow_nan=False)),
    }


class SeelOriEstIMU6DAdapter:
    """Host-side causal 6D Seel/OriEstIMU adapter independent of firmware."""

    manifest = _MANIFEST

    def __init__(self) -> None:
        self._block = None
        self._np = None
        self._zero_mag = None
        self._period_s: float | None = None
        self._nominal_interval_ticks: float | None = None
        self._last_timestamp: int | None = None
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
        output: list[float] = []
        for index, component in enumerate(value):
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise ContractError(f"{label}[{index}] must be a finite number")
            converted = float(component)
            if not math.isfinite(converted):
                raise ContractError(f"{label}[{index}] must be a finite number")
            output.append(converted)
        return output[0], output[1], output[2]

    @staticmethod
    def _validate_parameters(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != set(DEFAULT_PARAMETERS):
            raise ContractError(f"parameters must contain exactly {sorted(DEFAULT_PARAMETERS)}")
        for name in ("tauAcc", "tauMag", "zeta", "accRating"):
            component = value[name]
            if isinstance(component, bool) or not isinstance(component, (int, float)) or not math.isfinite(component):
                raise ContractError(f"parameters.{name} must be a finite number")
        if value["tauAcc"] <= 0.0 or value["tauMag"] <= 0.0 or value["zeta"] < 0.0 or value["accRating"] < 0.0:
            raise ContractError("tauAcc/tauMag must be positive and zeta/accRating nonnegative")
        initial_quaternion = value["initQuat"]
        initial_bias = value["initBias"]
        if not isinstance(initial_quaternion, (list, tuple)) or len(initial_quaternion) != 4:
            raise ContractError("parameters.initQuat must contain four scalar-first values")
        if not isinstance(initial_bias, (list, tuple)) or len(initial_bias) != 3:
            raise ContractError("parameters.initBias must contain three values")
        for name, vector in (("initQuat", initial_quaternion), ("initBias", initial_bias)):
            for index, component in enumerate(vector):
                if isinstance(component, bool) or not isinstance(component, (int, float)) or not math.isfinite(component):
                    raise ContractError(f"parameters.{name}[{index}] must be finite")
        norm = math.sqrt(sum(float(component) ** 2 for component in initial_quaternion))
        if abs(norm - 1.0) > 1e-12:
            raise ContractError("parameters.initQuat must be unit length")
        normalized = {
            "tauAcc": float(value["tauAcc"]),
            "tauMag": float(value["tauMag"]),
            "zeta": float(value["zeta"]),
            "accRating": float(value["accRating"]),
            "initQuat": [float(component) for component in initial_quaternion],
            "initBias": [float(component) for component in initial_bias],
        }
        if normalized != DEFAULT_PARAMETERS:
            raise ContractError("this adapter is pinned to its documented block-default/reset parameter variant")
        return normalized

    def reset(self, config: Mapping[str, Any]) -> None:
        """Create a wholly fresh official block, then apply its documented reset."""
        # Drop every previous trial object before config validation; a failed
        # reset must not leave the prior C++ object available to step().
        self._block = None
        self._np = None
        self._zero_mag = None
        self._period_s = None
        self._nominal_interval_ticks = None
        self._last_timestamp = None
        self._last_diagnostics = None
        if not isinstance(config, Mapping) or set(config) != {"sampling_rate_hz", "timestamp_unit", "parameters"}:
            raise ContractError("qmt config fields must be exactly sampling_rate_hz, timestamp_unit, and parameters")
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
        parameters = self._validate_parameters(config["parameters"])

        try:
            import importlib.metadata

            import numpy as np
            import qmt
        except ImportError as error:  # pragma: no cover - optional reference dependency
            raise RuntimeError(
                "qmt adapter needs external_benchmarks/references/requirements-qmt-b4-win-cp311.lock.txt"
            ) from error
        if importlib.metadata.version("qmt") != "0.2.4":
            raise RuntimeError("qmt adapter requires the pinned official qmt==0.2.4 package")

        period_s = denominator / numerator
        ticks_per_second = 1_000_000_000 if unit == "ns" else 1_000_000
        nominal_interval_ticks = ticks_per_second * denominator / numerator
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ContractError("sampling rate must imply a finite positive Ts")
        if not math.isfinite(nominal_interval_ticks) or nominal_interval_ticks < 1.0:
            raise ContractError("configured rate cannot be represented by the timestamp unit")

        block = qmt.OriEstIMUBlock(period_s)
        if dict(block.params) != _BLOCK_PARAMETERS:
            raise RuntimeError("upstream qmt OriEstIMUBlock defaults do not match the pinned manifest")
        block.setParams(_BLOCK_PARAMETERS)
        # qmt's Cython block requires a magnetometer ndarray even though its
        # C++ implementation treats the all-zero vector as the no-mag path.
        # This mirrors qmt.oriEstIMU(..., mag=None), whose wrapper supplies the
        # same zero sentinel. No physical or synthetic magnetic aid is scored.
        block.command(["reset"])
        self._block = block
        self._np = np
        self._zero_mag = np.zeros(3, dtype=np.float64)
        self._period_s = period_s
        self._nominal_interval_ticks = nominal_interval_ticks

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float],
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process a single causal 6D sample using official OriEstIMUBlock."""
        if self._block is None or self._np is None or self._period_s is None:
            raise ContractError("reset(config) must be called before the first OriEstIMU step")
        if aid is not None:
            raise ContractError("Seel/OriEstIMU 6D does not accept a heading or magnetometer aid")
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
                raise ContractError("OriEstIMU requires configured uniform timestamps")

        accel_array = self._np.ascontiguousarray(accel, dtype=self._np.float64)
        gyro_array = self._np.ascontiguousarray(gyro, dtype=self._np.float64)
        quaternion = self._block.step(gyro_array, accel_array, self._zero_mag)
        quaternion_wxyz = [float(value) for value in quaternion]
        self._last_timestamp = timestamp

        raw_bias = getattr(self._block.obj, "bias", None)
        if raw_bias is not None:
            # qmt's official debug output reports -C++ internal bias.
            self._last_diagnostics = {
                "gyroscope_bias_rad_s": [-float(value) for value in raw_bias],
                "bias_estimation_enabled": bool(DEFAULT_PARAMETERS["zeta"] > 0.0),
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
        """Return qmt's optional gyro-bias diagnostic outside the shared schema."""
        if self._last_diagnostics is None:
            return None
        return json.loads(json.dumps(self._last_diagnostics, allow_nan=False))
