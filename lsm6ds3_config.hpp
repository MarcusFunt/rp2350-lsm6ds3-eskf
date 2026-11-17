#pragma once

#include "eskf15.hpp"

#include <cstdint>

namespace lsm6ds3_config {

constexpr float kFaultRangeMargin = 0.98f;
constexpr std::uint8_t kOdr208HzBits = 0x50;

constexpr bool supported_accel_range(unsigned full_scale_g) {
    return full_scale_g == 2 || full_scale_g == 4 || full_scale_g == 8 || full_scale_g == 16;
}

constexpr std::uint8_t accel_range_bits(unsigned full_scale_g) {
    switch (full_scale_g) {
    case 2: return 0x00;
    case 4: return 0x08;
    case 8: return 0x0c;
    case 16: return 0x04;
    default: return 0;
    }
}

constexpr float accel_sensitivity_mg_per_lsb(unsigned full_scale_g) {
    switch (full_scale_g) {
    case 2: return 0.061f;
    case 4: return 0.122f;
    case 8: return 0.244f;
    case 16: return 0.488f;
    default: return 0.0f;
    }
}

constexpr bool supported_gyro_range(unsigned full_scale_dps) {
    return full_scale_dps == 125 || full_scale_dps == 245 || full_scale_dps == 500
        || full_scale_dps == 1000 || full_scale_dps == 2000;
}

constexpr std::uint8_t gyro_range_bits(unsigned full_scale_dps) {
    switch (full_scale_dps) {
    case 125: return 0x02;
    case 245: return 0x00;
    case 500: return 0x04;
    case 1000: return 0x08;
    case 2000: return 0x0c;
    default: return 0;
    }
}

constexpr float gyro_sensitivity_mdps_per_lsb(unsigned full_scale_dps) {
    switch (full_scale_dps) {
    case 125: return 4.375f;
    case 245: return 8.75f;
    case 500: return 17.50f;
    case 1000: return 35.0f;
    case 2000: return 70.0f;
    default: return 0.0f;
    }
}

struct RangeConfig {
    bool supported;
    unsigned accel_full_scale_g;
    unsigned gyro_full_scale_dps;
    std::uint8_t ctrl1_xl_value;
    std::uint8_t ctrl2_g_value;
    float accel_mps2_per_lsb;
    float gyro_rad_s_per_lsb;
    float max_accel_axis_mps2;
    float max_gyro_axis_rps;
};

constexpr RangeConfig make_range_config(unsigned accel_full_scale_g,
                                        unsigned gyro_full_scale_dps) {
    const bool supported = supported_accel_range(accel_full_scale_g)
        && supported_gyro_range(gyro_full_scale_dps);
    const float accel_scale = accel_sensitivity_mg_per_lsb(accel_full_scale_g)
        * 0.001f * inertial::kGravity;
    const float gyro_scale = gyro_sensitivity_mdps_per_lsb(gyro_full_scale_dps)
        * 0.001f * (inertial::kPi / 180.0f);
    return {
        supported,
        accel_full_scale_g,
        gyro_full_scale_dps,
        static_cast<std::uint8_t>(supported ? kOdr208HzBits | accel_range_bits(accel_full_scale_g) : 0),
        static_cast<std::uint8_t>(supported ? kOdr208HzBits | gyro_range_bits(gyro_full_scale_dps) : 0),
        supported ? accel_scale : 0.0f,
        supported ? gyro_scale : 0.0f,
        supported ? kFaultRangeMargin * static_cast<float>(accel_full_scale_g) * inertial::kGravity : 0.0f,
        supported ? kFaultRangeMargin * static_cast<float>(gyro_full_scale_dps)
            * (inertial::kPi / 180.0f) : 0.0f,
    };
}

constexpr RangeConfig kActiveRange = make_range_config(4, 245);
static_assert(kActiveRange.supported, "selected LSM6DS3 full-scale profile must be supported");

constexpr inertial::Settings eskf_settings(const RangeConfig &range) {
    inertial::Settings settings{};
    settings.max_accel_axis_mps2 = range.max_accel_axis_mps2;
    settings.max_gyro_axis_rps = range.max_gyro_axis_rps;
    return settings;
}

} // namespace lsm6ds3_config
