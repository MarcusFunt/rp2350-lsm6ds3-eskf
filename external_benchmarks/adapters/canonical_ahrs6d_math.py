"""Equation-level 6D Mahony and Madgwick references in the B1 q_WB convention.

These routines are a small, float64 Python reimplementation of the documented
IMU equations. They intentionally do not call the pinned AHRS package methods:
the maintained package short-circuits when gyro norm is exactly zero, which
also suppresses valid accelerometer feedback. The B6 adapter keeps the
canonical equations active for that input and skips only a zero gradient.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


def cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    w, x, y, z = left
    a, b, c, d = right
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


def quaternion_conjugate(quaternion: Quaternion) -> Quaternion:
    return quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3]


def quaternion_normalize(quaternion: Sequence[float]) -> Quaternion:
    norm = math.sqrt(sum(value * value for value in quaternion))
    if not math.isfinite(norm) or norm <= 1e-15:
        raise ValueError("quaternion must have finite, nonzero norm")
    return tuple(value / norm for value in quaternion)  # type: ignore[return-value]


def rotate_body_to_world(quaternion_wxyz: Sequence[float], vector_body: Sequence[float]) -> Vector3:
    q = quaternion_normalize(quaternion_wxyz)
    vector = tuple(float(value) for value in vector_body)
    rotated = quaternion_multiply(
        quaternion_multiply(q, (0.0, vector[0], vector[1], vector[2])),
        quaternion_conjugate(q),
    )
    return rotated[1], rotated[2], rotated[3]


def quaternion_geodesic_rad(left: Sequence[float], right: Sequence[float]) -> float:
    q_left = quaternion_normalize(left)
    q_right = quaternion_normalize(right)
    relative = quaternion_multiply(quaternion_conjugate(q_left), q_right)
    return 2.0 * math.atan2(
        math.sqrt(relative[1] ** 2 + relative[2] ** 2 + relative[3] ** 2),
        abs(relative[0]),
    )


def _quaternion_derivative(quaternion: Quaternion, angular_rate_rad_s: Vector3) -> Quaternion:
    product = quaternion_multiply(quaternion, (0.0, *angular_rate_rad_s))
    return tuple(0.5 * value for value in product)  # type: ignore[return-value]


def _normalize_accelerometer(accelerometer_mps2: Vector3 | None, epsilon_mps2: float) -> Vector3 | None:
    if accelerometer_mps2 is None:
        return None
    magnitude = math.sqrt(sum(value * value for value in accelerometer_mps2))
    if not math.isfinite(magnitude) or magnitude <= epsilon_mps2:
        return None
    return tuple(value / magnitude for value in accelerometer_mps2)  # type: ignore[return-value]


def mahony_imu_step(
    quaternion_wxyz: Quaternion,
    gyro_rad_s: Vector3,
    accel_mps2: Vector3 | None,
    estimated_gyro_bias_rad_s: Vector3,
    *,
    dt_s: float,
    k_p_s_inv: float,
    k_i_s_inv2: float,
    accel_norm_epsilon_mps2: float,
) -> tuple[Quaternion, Vector3]:
    """One explicit Mahony complementary-filter step (6D, q_WB, ENU).

    The residual is measured specific-force direction cross the predicted body
    direction of world-up. Bias follows b_dot=-kI*residual, and the corrected
    rate is gyro-b+kP*residual. Missing acceleration skips both feedback terms
    while retaining the current bias estimate in gyro-bias compensation.
    """
    q = quaternion_normalize(quaternion_wxyz)
    measured_up_body = _normalize_accelerometer(accel_mps2, accel_norm_epsilon_mps2)
    bias = estimated_gyro_bias_rad_s
    corrected_rate = tuple(gyro_rad_s[index] - bias[index] for index in range(3))
    if measured_up_body is not None:
        predicted_up_body = rotate_body_to_world(quaternion_conjugate(q), (0.0, 0.0, 1.0))
        residual = cross(measured_up_body, predicted_up_body)
        bias = tuple(
            estimated_gyro_bias_rad_s[index] - k_i_s_inv2 * residual[index] * dt_s
            for index in range(3)
        )
        corrected_rate = tuple(
            gyro_rad_s[index] - bias[index] + k_p_s_inv * residual[index]
            for index in range(3)
        )
    q_dot = _quaternion_derivative(q, corrected_rate)
    q_next = tuple(q[index] + q_dot[index] * dt_s for index in range(4))
    return quaternion_normalize(q_next), bias


def madgwick_imu_step(
    quaternion_wxyz: Quaternion,
    gyro_rad_s: Vector3,
    accel_mps2: Vector3 | None,
    *,
    dt_s: float,
    beta_rad_s: float,
    accel_norm_epsilon_mps2: float,
    gradient_epsilon: float,
) -> Quaternion:
    """One canonical Madgwick IMU gradient-descent step (6D, q_WB, ENU)."""
    q = quaternion_normalize(quaternion_wxyz)
    q_dot = list(_quaternion_derivative(q, gyro_rad_s))
    measured_up_body = _normalize_accelerometer(accel_mps2, accel_norm_epsilon_mps2)
    if measured_up_body is not None:
        qw, qx, qy, qz = q
        ax, ay, az = measured_up_body
        # Objective f(q) = q* [0,0,1] q - [0,a], and its Jacobian.
        objective = (
            2.0 * (qx * qz - qw * qy) - ax,
            2.0 * (qw * qx + qy * qz) - ay,
            2.0 * (0.5 - qx * qx - qy * qy) - az,
        )
        jacobian = (
            (-2.0 * qy, 2.0 * qz, -2.0 * qw, 2.0 * qx),
            (2.0 * qx, 2.0 * qw, 2.0 * qz, 2.0 * qy),
            (0.0, -4.0 * qx, -4.0 * qy, 0.0),
        )
        gradient = tuple(
            sum(jacobian[row][column] * objective[row] for row in range(3))
            for column in range(4)
        )
        gradient_norm = math.sqrt(sum(value * value for value in gradient))
        if gradient_norm > gradient_epsilon:
            q_dot = [
                q_dot[index] - beta_rad_s * gradient[index] / gradient_norm
                for index in range(4)
            ]
    q_next = tuple(q[index] + q_dot[index] * dt_s for index in range(4))
    return quaternion_normalize(q_next)


def quaternion_exponential(rotation_vector_rad: Vector3) -> Quaternion:
    """Quaternion exponential used only to replay the historical PR3 baseline."""
    angle = math.sqrt(sum(value * value for value in rotation_vector_rad))
    half_angle = 0.5 * angle
    if angle <= 1e-15:
        return 1.0, 0.5 * rotation_vector_rad[0], 0.5 * rotation_vector_rad[1], 0.5 * rotation_vector_rad[2]
    scale = math.sin(half_angle) / angle
    return (
        math.cos(half_angle),
        rotation_vector_rad[0] * scale,
        rotation_vector_rad[1] * scale,
        rotation_vector_rad[2] * scale,
    )
