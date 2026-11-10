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

static float protocol_v1_tilt_metric_deg(Quat estimate, Quat truth) {
    const Vec3 estimate_up = estimate.rotate({0.0f, 0.0f, 1.0f});
    const Vec3 truth_up = truth.rotate({0.0f, 0.0f, 1.0f});
    const float cosine = std::fmax(-1.0f, std::fmin(1.0f, dot(estimate_up, truth_up)));
    return std::acos(cosine) * 180.0f / kPi;
}

int main() {
    const Quat truth = Quat::exp({0.41f, -0.23f, 0.18f});
    const Quat world_yaw = Quat::exp({0.0f, 0.0f, 0.9f});
    const Quat estimate = world_yaw * truth;

    // Changing only world yaw leaves the body-frame gravity direction intact.
    assert(tilt_error(estimate, truth) < 1e-4f);
    assert(attitude_angle(estimate, truth) > 0.5f);
    const float v1_error = protocol_v1_tilt_metric_deg(estimate, truth);
    assert(v1_error > 5.0f);

    const Quat common_yaw = Quat::exp({0.0f, 0.0f, -0.7f});
    const float original = tilt_error(estimate, truth);
    const float shifted = tilt_error(common_yaw * estimate, common_yaw * truth);
    assert(std::fabs(original - shifted) < 1e-4f);

    std::printf("PASS yaw-invariant tilt metric; protocol-v1 would report %.3f deg for yaw-only change\n", v1_error);
}
