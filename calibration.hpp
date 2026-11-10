#pragma once
// Deterministic offline calibration in SI units. Raw data must first be
// converted from device LSB to m/s^2 and rad/s. All matrices are row-major.
// C_BS maps corrected vectors from sensor axes to body axes.
#include <cmath>
#include <cstdint>
#include "eskf15.hpp"

namespace inertial {
struct Matrix3 {
    float v[3][3] = {{1,0,0},{0,1,0},{0,0,1}};
    Vec3 apply(Vec3 a) const {
        return {v[0][0]*a.x+v[0][1]*a.y+v[0][2]*a.z,
                v[1][0]*a.x+v[1][1]*a.y+v[1][2]*a.z,
                v[2][0]*a.x+v[2][1]*a.y+v[2][2]*a.z};
    }
    bool finite() const {
        for (const auto &row : v) for (float x : row) if (!std::isfinite(x)) return false;
        return true;
    }
    float det() const {
        return v[0][0]*(v[1][1]*v[2][2]-v[1][2]*v[2][1])
            -v[0][1]*(v[1][0]*v[2][2]-v[1][2]*v[2][0])
            +v[0][2]*(v[1][0]*v[2][1]-v[1][1]*v[2][0]);
    }
};
struct SensorCalibration {
    // ID=0 expressly means uncalibrated, not a verified zero-error device.
    uint32_t version=1;
    uint32_t calibration_id=0;
    uint32_t source_id=0x4c364433; // LSM6DS3 original
    Matrix3 body_from_sensor{};
    Matrix3 accel_correction{}; // contains scale, cross-axis/misalignment effects
    Matrix3 gyro_correction{};
    Vec3 accel_offset{};         // SI constant factory/offline offset
    Vec3 gyro_offset{};
    Vec3 accel_temp_coeff{};     // SI units per C
    Vec3 gyro_temp_coeff{};
    float reference_temp_c=25.0f;
    bool temperature_compensation=false;
    // ESKF bias states estimate RESIDUAL bias after this fixed calibration.
    bool valid() const {
        if (version!=1 || !body_from_sensor.finite() || !accel_correction.finite() ||
            !gyro_correction.finite() || !std::isfinite(reference_temp_c)) return false;
        if (!finite_vec(accel_offset) || !finite_vec(gyro_offset) ||
            !finite_vec(accel_temp_coeff) || !finite_vec(gyro_temp_coeff)) return false;
        // Require an approximately proper rigid rotation. Do not silently
        // accept a reflection or a scale as the sensor-to-body rotation.
        if (std::fabs(body_from_sensor.det()-1.0f)>0.01f) return false;
        const float *p=&body_from_sensor.v[0][0];
        for(int i=0;i<3;i++)for(int j=0;j<3;j++){
            float d=0;
            for(int k=0;k<3;k++) d+=p[i*3+k]*p[j*3+k];
            if (std::fabs(d-(i==j ? 1.0f:0.0f))>0.01f) return false;
        }
        if (accel_correction.det()<=0.0f || gyro_correction.det()<=0.0f) return false;
        return true;
    }
    static bool finite_vec(Vec3 x) {
        return std::isfinite(x.x)&&std::isfinite(x.y)&&std::isfinite(x.z);
    }
    bool apply(const Imu &raw, float temp_c, Imu &corrected) const {
        if (!valid() || !finite_vec(raw.accel_mps2) || !finite_vec(raw.gyro_rps)) return false;
        if (temperature_compensation && !std::isfinite(temp_c)) return false;
        const float dt=temperature_compensation ? temp_c-reference_temp_c : 0;
        const Vec3 a=raw.accel_mps2-accel_offset-accel_temp_coeff*dt;
        const Vec3 g=raw.gyro_rps-gyro_offset-gyro_temp_coeff*dt;
        corrected=raw;
        corrected.accel_mps2=body_from_sensor.apply(accel_correction.apply(a));
        corrected.gyro_rps=body_from_sensor.apply(gyro_correction.apply(g));
        return finite_vec(corrected.accel_mps2)&&finite_vec(corrected.gyro_rps);
    }
};
} // namespace inertial
