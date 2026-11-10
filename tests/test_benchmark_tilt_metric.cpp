#define main benchmark_bundle_b_main
#include "../tools/benchmark_bundle_b.cpp"
#undef main

#include <cassert>
#include <cmath>
#include <cstdio>

static float attitude_angle(Quat a, Quat b) {
    const float d = std::fabs(a.w*b.w + a.x*b.x + a.y*b.y + a.z*b.z);
    return 2.0f * std::acos(std::fmax(-1.0f, std::fmin(1.0f, d)));
}

int main() {
    const Quat truth = Quat::exp({0.41f, -0.23f, 0.18f});
    const Quat world_yaw = Quat::exp({0.0f, 0.0f, 0.9f});
    const Quat estimate = world_yaw * truth;

    // Changing only world yaw leaves the body-frame gravity direction intact.
    assert(tilt_error(estimate, truth) < 1e-4f);
    assert(attitude_angle(estimate, truth) > 0.5f);

    const Quat common_yaw = Quat::exp({0.0f, 0.0f, -0.7f});
    const float original = tilt_error(estimate, truth);
    const float shifted = tilt_error(common_yaw * estimate, common_yaw * truth);
    assert(std::fabs(original - shifted) < 1e-4f);

    std::puts("PASS yaw-invariant tilt metric and common-world-yaw invariance");
}
