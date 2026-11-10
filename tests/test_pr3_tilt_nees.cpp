#define main pr3_evaluator_cli_hidden_main
#include "../tools/pr3_evaluate_stream.cpp"
#undef main

#include <cassert>
#include <cmath>
#include <cstdio>

int main() {
    using namespace inertial;
    Eskf15 filter{};
    const double yaw_only=tilt_nees(filter,Quat::exp({0.0f,0.0f,0.7f}));
    assert(std::isfinite(yaw_only) && yaw_only<1e-5);
    const Quat tilt_truth=Quat::exp({0.06f,-0.08f,0.8f});
    const double observed=tilt_nees(filter,tilt_truth);
    const double expected=(0.06*0.06+0.08*0.08)/(0.15*0.15);
    assert(std::fabs(observed-expected)<1e-4);
    std::printf("PASS analytic 2D tilt NEES: yaw gauge=%.8g, tilted reference=%.8g\n",yaw_only,observed);
}
