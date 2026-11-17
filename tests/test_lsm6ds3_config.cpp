#include "lsm6ds3_config.hpp"

#include <cmath>
#include <cstdio>

namespace {

bool near(float actual, float expected, float tolerance) {
    return std::fabs(actual - expected) <= tolerance;
}

int check(bool condition, const char *message) {
    if (condition) return 0;
    std::fprintf(stderr, "FAIL %s\n", message);
    return 1;
}

} // namespace

int main() {
    using lsm6ds3_config::make_range_config;
    const auto active_config = make_range_config(4, 245);
    const auto broad_config = make_range_config(16, 2000);
    const auto unsupported_config = make_range_config(3, 245);
    int failures = 0;

    failures += check(active_config.supported, "4 g / 245 dps profile is supported");
    failures += check(active_config.ctrl1_xl_value == 0x58,
                      "4 g / 208 Hz profile encodes CTRL1_XL as 0x58");
    failures += check(active_config.ctrl2_g_value == 0x50,
                      "245 dps / 208 Hz profile encodes CTRL2_G as 0x50");
    failures += check(near(active_config.accel_mps2_per_lsb,
                           0.000122f * inertial::kGravity, 1e-8f),
                      "4 g raw accelerometer counts use 0.122 mg/LSB");
    failures += check(near(active_config.gyro_rad_s_per_lsb,
                           0.00875f * inertial::kPi / 180.0f, 1e-9f),
                      "245 dps raw gyro counts use 8.75 mdps/LSB");

    const auto active_settings = lsm6ds3_config::eskf_settings(active_config);
    failures += check(near(active_settings.max_accel_axis_mps2,
                           0.98f * 4.0f * inertial::kGravity, 1e-5f),
                      "ESKF acceleration fault limit derives from the selected 4 g range");
    failures += check(near(active_settings.max_gyro_axis_rps,
                           0.98f * 245.0f * inertial::kPi / 180.0f, 1e-5f),
                      "ESKF gyro fault limit derives from the selected 245 dps range");

    failures += check(broad_config.supported && broad_config.ctrl1_xl_value == 0x54
                          && broad_config.ctrl2_g_value == 0x5c,
                      "16 g / 2000 dps profile encodes its distinct register ranges");
    const auto broad_settings = lsm6ds3_config::eskf_settings(broad_config);
    failures += check(near(broad_settings.max_accel_axis_mps2,
                           0.98f * 16.0f * inertial::kGravity, 1e-5f),
                      "ESKF acceleration limit follows a changed profile");
    failures += check(near(broad_settings.max_gyro_axis_rps,
                           0.98f * 2000.0f * inertial::kPi / 180.0f, 1e-4f),
                      "ESKF gyro limit follows a changed profile");
    failures += check(!unsupported_config.supported,
                      "unsupported full-scale selections are rejected");

    if (failures == 0) std::puts("PASS LSM6DS3 register, decoder and ESKF ranges share one profile");
    return failures == 0 ? 0 : 1;
}
