"""B1 adapters for pinned canonical 6D AHRS references and PR3 history."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from external_benchmarks.api import ContractError, canonical_json_sha256
from external_benchmarks.adapters.canonical_ahrs6d_math import (
    cross,
    madgwick_imu_step,
    mahony_imu_step,
    quaternion_conjugate,
    quaternion_exponential,
    quaternion_multiply,
    quaternion_normalize,
    rotate_body_to_world,
)


_ADAPTER_DIR = Path(__file__).parent
HISTORICAL_VARIANT_ID = "mahony_internal_historical"
MAHONY_MANIFEST = json.loads((_ADAPTER_DIR / "mahony_reference_6d_manifest_v1.json").read_text(encoding="utf-8"))
MADGWICK_MANIFEST = json.loads((_ADAPTER_DIR / "madgwick_reference_6d_manifest_v1.json").read_text(encoding="utf-8"))
HISTORICAL_MANIFEST = json.loads((_ADAPTER_DIR / "mahony_internal_historical_manifest_v1.json").read_text(encoding="utf-8"))
_IDENTITY: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
_WORLD_UP = (0.0, 0.0, 1.0)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ContractError(f"{label} must be a finite number")
    return converted


def _vector(value: Any, label: str, *, allow_none: bool = False) -> tuple[float, float, float] | None:
    if value is None and allow_none:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise ContractError(f"{label} must contain exactly three finite values")
    return tuple(_number(value[index], f"{label}[{index}]") for index in range(3))  # type: ignore[return-value]


def _initial_quaternion(config: Mapping[str, Any]) -> tuple[float, float, float, float]:
    raw = config["initial_quaternion_wxyz"]
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 4:
        raise ContractError("initial_quaternion_wxyz must contain four finite values")
    values = tuple(_number(raw[index], f"initial_quaternion_wxyz[{index}]") for index in range(4))
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or abs(norm - 1.0) > 1e-9:
        raise ContractError("initial_quaternion_wxyz must already be unit length")
    return values  # type: ignore[return-value]


def _shared_default_config(
    *,
    sampling_rate_numerator: int,
    sampling_rate_denominator: int,
    timestamp_unit: str,
    initial_quaternion_wxyz: Sequence[float],
) -> dict[str, Any]:
    return {
        "sampling_rate_hz": {
            "numerator": sampling_rate_numerator,
            "denominator": sampling_rate_denominator,
        },
        "timestamp_unit": timestamp_unit,
        "initial_quaternion_wxyz": list(initial_quaternion_wxyz),
        "initial_yaw_gauge": "unobservable_startup",
    }


def default_mahony_config(
    *,
    sampling_rate_numerator: int = 100,
    sampling_rate_denominator: int = 1,
    timestamp_unit: str = "ns",
    initial_quaternion_wxyz: Sequence[float] = _IDENTITY,
    initial_gyro_bias_rad_s: Sequence[float] = (0.0, 0.0, 0.0),
    k_p: float = 1.0,
    k_i: float = 0.3,
) -> dict[str, Any]:
    """Return fixed canonical Mahony development parameters (no truth/aid)."""
    return {
        **_shared_default_config(
            sampling_rate_numerator=sampling_rate_numerator,
            sampling_rate_denominator=sampling_rate_denominator,
            timestamp_unit=timestamp_unit,
            initial_quaternion_wxyz=initial_quaternion_wxyz,
        ),
        "initial_gyro_bias_rad_s": list(initial_gyro_bias_rad_s),
        "k_p_s_inv": k_p,
        "k_i_s_inv2": k_i,
        "accel_norm_epsilon_mps2": 1e-12,
    }


def default_madgwick_config(
    *,
    sampling_rate_numerator: int = 100,
    sampling_rate_denominator: int = 1,
    timestamp_unit: str = "ns",
    initial_quaternion_wxyz: Sequence[float] = _IDENTITY,
    beta: float = 0.033,
) -> dict[str, Any]:
    """Return fixed canonical Madgwick IMU parameters (no truth/aid)."""
    return {
        **_shared_default_config(
            sampling_rate_numerator=sampling_rate_numerator,
            sampling_rate_denominator=sampling_rate_denominator,
            timestamp_unit=timestamp_unit,
            initial_quaternion_wxyz=initial_quaternion_wxyz,
        ),
        "beta_rad_s": beta,
        "accel_norm_epsilon_mps2": 1e-12,
        "gradient_epsilon": 1e-15,
    }


class _Causal6DAdapter:
    manifest: dict[str, Any]
    _algorithm_config_keys: frozenset[str] = frozenset()

    def __init__(self) -> None:
        self._configured = False
        self._q: tuple[float, float, float, float] = _IDENTITY
        self._last_timestamp: int | None = None
        self._ticks_per_second = 1_000_000_000
        self._nominal_interval_ticks = 0.0
        self._period_s = 0.0
        self._config: dict[str, Any] = {}
        self.configuration_identity: str | None = None

    def _common_reset(self, config: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise ContractError("adapter config must be a mapping")
        required = {
            "sampling_rate_hz",
            "timestamp_unit",
            "initial_quaternion_wxyz",
            "initial_yaw_gauge",
            *self._algorithm_config_keys,
        }
        if set(config) != required:
            raise ContractError(f"adapter config fields must be exactly {sorted(required)}")
        rate = config["sampling_rate_hz"]
        if not isinstance(rate, Mapping) or set(rate) != {"numerator", "denominator"}:
            raise ContractError("sampling_rate_hz must contain numerator and denominator")
        numerator = _positive_int(rate["numerator"], "sampling_rate_hz.numerator")
        denominator = _positive_int(rate["denominator"], "sampling_rate_hz.denominator")
        if math.gcd(numerator, denominator) != 1:
            raise ContractError("sampling_rate_hz must be a reduced rational")
        unit = config["timestamp_unit"]
        if not isinstance(unit, str) or unit not in {"ns", "us"}:
            raise ContractError("timestamp_unit must be 'ns' or 'us'")
        if config["initial_yaw_gauge"] != "unobservable_startup":
            raise ContractError("six-axis references require the unobservable_startup yaw gauge")
        q0 = _initial_quaternion(config)
        try:
            period_s = denominator / numerator
        except OverflowError as error:
            raise ContractError("sampling rate is outside the supported numeric range") from error
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ContractError("sampling rate must imply a finite positive sample period")
        ticks_per_second = 1_000_000_000 if unit == "ns" else 1_000_000
        interval_ticks = ticks_per_second * period_s
        if not math.isfinite(interval_ticks) or interval_ticks < 1.0:
            raise ContractError("configured sample period cannot be represented in the timestamp unit")
        self._configured = False
        self._last_timestamp = None
        self._ticks_per_second = ticks_per_second
        self._nominal_interval_ticks = interval_ticks
        self._period_s = period_s
        self._q = q0
        self._config = dict(config)
        self.configuration_identity = (
            f"{self.manifest['variant_id']}:{canonical_json_sha256(dict(config))}"
        )
        return self._config

    def _begin_reset(self) -> None:
        self._configured = False
        self._last_timestamp = None
        self._q = _IDENTITY
        self._config = {}
        self.configuration_identity = None
        if hasattr(self, "_gyro_bias"):
            self._gyro_bias = (0.0, 0.0, 0.0)

    def _base_step_inputs(
        self,
        timestamp: int,
        accel_mps2: Sequence[float] | None,
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None,
    ) -> tuple[int, tuple[float, float, float] | None, tuple[float, float, float], float | None]:
        if not self._configured:
            raise ContractError("reset(config) must be called before step")
        if aid is not None:
            raise ContractError("canonical 6D references do not accept heading or magnetometer aids")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ContractError("timestamp must be a nonnegative integer")
        accel = _vector(accel_mps2, "accel_mps2", allow_none=True)
        gyro = _vector(gyro_rad_s, "gyro_rad_s")
        dt_s: float | None = None
        if self._last_timestamp is not None:
            interval = timestamp - self._last_timestamp
            if interval <= 0:
                raise ContractError("timestamps must be strictly increasing")
            if abs(interval - self._nominal_interval_ticks) > 1.0:
                raise ContractError("canonical reference requires configured uniform sampling")
            dt_s = interval / self._ticks_per_second
        return timestamp, accel, gyro, dt_s

    def _output(self, timestamp: int) -> dict[str, Any]:
        return {
            "timestamp": timestamp,
            "orientation_valid": True,
            "status": "valid",
            "orientation": {
                "quaternion_wxyz": list(self._q),
                "yaw_gauge": "unobservable_startup",
            },
        }


class MahonyReference6DAdapter(_Causal6DAdapter):
    """Equation-faithful 6D Mahony reference with online gyro-bias state."""

    manifest = MAHONY_MANIFEST
    _algorithm_config_keys = frozenset(
        {
            "initial_gyro_bias_rad_s",
            "k_p_s_inv",
            "k_i_s_inv2",
            "accel_norm_epsilon_mps2",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self._gyro_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def estimated_gyro_bias_rad_s(self) -> tuple[float, float, float]:
        return self._gyro_bias

    def reset(self, config: Mapping[str, Any]) -> None:
        self._begin_reset()
        parsed = self._common_reset(config)
        bias = _vector(parsed["initial_gyro_bias_rad_s"], "initial_gyro_bias_rad_s")
        k_p = _number(parsed["k_p_s_inv"], "k_p_s_inv")
        k_i = _number(parsed["k_i_s_inv2"], "k_i_s_inv2")
        epsilon = _number(parsed["accel_norm_epsilon_mps2"], "accel_norm_epsilon_mps2")
        if k_p < 0.0 or k_i < 0.0 or epsilon <= 0.0:
            raise ContractError("Mahony gains must be nonnegative and acceleration epsilon positive")
        self._gyro_bias = bias
        self._configured = True

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float] | None,
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp, accel, gyro, dt_s = self._base_step_inputs(timestamp, accel_mps2, gyro_rad_s, aid)
        if dt_s is not None:
            self._q, self._gyro_bias = mahony_imu_step(
                self._q,
                gyro,
                accel,
                self._gyro_bias,
                dt_s=dt_s,
                k_p_s_inv=float(self._config["k_p_s_inv"]),
                k_i_s_inv2=float(self._config["k_i_s_inv2"]),
                accel_norm_epsilon_mps2=float(self._config["accel_norm_epsilon_mps2"]),
            )
        self._last_timestamp = timestamp
        return self._output(timestamp)


class MadgwickReference6DAdapter(_Causal6DAdapter):
    """Equation-faithful canonical 6D Madgwick gradient-descent reference."""

    manifest = MADGWICK_MANIFEST
    _algorithm_config_keys = frozenset(
        {"beta_rad_s", "accel_norm_epsilon_mps2", "gradient_epsilon"}
    )

    def reset(self, config: Mapping[str, Any]) -> None:
        self._begin_reset()
        parsed = self._common_reset(config)
        beta = _number(parsed["beta_rad_s"], "beta_rad_s")
        epsilon = _number(parsed["accel_norm_epsilon_mps2"], "accel_norm_epsilon_mps2")
        gradient_epsilon = _number(parsed["gradient_epsilon"], "gradient_epsilon")
        if beta < 0.0 or epsilon <= 0.0 or gradient_epsilon <= 0.0:
            raise ContractError("Madgwick beta must be nonnegative and numerical epsilons positive")
        self._configured = True

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float] | None,
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp, accel, gyro, dt_s = self._base_step_inputs(timestamp, accel_mps2, gyro_rad_s, aid)
        if dt_s is not None:
            self._q = madgwick_imu_step(
                self._q,
                gyro,
                accel,
                dt_s=dt_s,
                beta_rad_s=float(self._config["beta_rad_s"]),
                accel_norm_epsilon_mps2=float(self._config["accel_norm_epsilon_mps2"]),
                gradient_epsilon=float(self._config["gradient_epsilon"]),
            )
        self._last_timestamp = timestamp
        return self._output(timestamp)


class MahonyInternalHistoricalAdapter(_Causal6DAdapter):
    """Faithful PR3 v5 no-aid replay under its distinct historical ID.

    The old C++ `mahony` baseline uses a fixed proportional gravity residual,
    Ki=0.05 bias integration, and exponential quaternion integration. This
    adapter mirrors that code only for same-input forensic comparison; it is
    not the canonical Mahony reference.
    """

    manifest = HISTORICAL_MANIFEST
    _algorithm_config_keys = frozenset(
        {
            "initial_gyro_bias_rad_s",
            "k_p_s_inv",
            "k_i_s_inv2",
            "accel_min_norm_mps2",
        }
    )

    @staticmethod
    def default_config(
        *,
        sampling_rate_numerator: int = 100,
        sampling_rate_denominator: int = 1,
        timestamp_unit: str = "ns",
        initial_quaternion_wxyz: Sequence[float] = _IDENTITY,
    ) -> dict[str, Any]:
        return {
            **_shared_default_config(
                sampling_rate_numerator=sampling_rate_numerator,
                sampling_rate_denominator=sampling_rate_denominator,
                timestamp_unit=timestamp_unit,
                initial_quaternion_wxyz=initial_quaternion_wxyz,
            ),
            "initial_gyro_bias_rad_s": [0.0, 0.0, 0.0],
            "k_p_s_inv": 1.0,
            "k_i_s_inv2": 0.05,
            "accel_min_norm_mps2": 1e-4,
        }

    @property
    def estimated_gyro_bias_rad_s(self) -> tuple[float, float, float]:
        return self._gyro_bias

    def __init__(self) -> None:
        super().__init__()
        self._gyro_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def reset(self, config: Mapping[str, Any]) -> None:
        self._begin_reset()
        parsed = self._common_reset(config)
        if (
            _number(parsed["k_p_s_inv"], "k_p_s_inv") != 1.0
            or _number(parsed["k_i_s_inv2"], "k_i_s_inv2") != 0.05
            or _number(parsed["accel_min_norm_mps2"], "accel_min_norm_mps2") != 1e-4
        ):
            raise ContractError("historical PR3 Mahony parameters are fixed by the pinned source")
        if self._period_s > 0.025:
            raise ContractError("historical PR3 baseline rejected sample periods above 25 ms")
        self._gyro_bias = _vector(parsed["initial_gyro_bias_rad_s"], "initial_gyro_bias_rad_s")
        self._configured = True

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float] | None,
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp, accel, gyro, dt_s = self._base_step_inputs(timestamp, accel_mps2, gyro_rad_s, aid)
        if dt_s is not None:
            rate = tuple(gyro[index] - self._gyro_bias[index] for index in range(3))
            if accel is not None:
                norm = math.sqrt(sum(value * value for value in accel))
                if norm > float(self._config["accel_min_norm_mps2"]):
                    measured_up = tuple(value / norm for value in accel)
                    predicted_up = rotate_body_to_world(quaternion_conjugate(self._q), _WORLD_UP)
                    error = cross(measured_up, predicted_up)
                    rate = tuple(rate[index] + error[index] for index in range(3))
                    self._gyro_bias = tuple(
                        self._gyro_bias[index] - error[index] * 0.05 * dt_s
                        for index in range(3)
                    )
            increment = quaternion_exponential(tuple(value * dt_s for value in rate))
            self._q = quaternion_normalize(quaternion_multiply(self._q, increment))
        self._last_timestamp = timestamp
        return self._output(timestamp)
