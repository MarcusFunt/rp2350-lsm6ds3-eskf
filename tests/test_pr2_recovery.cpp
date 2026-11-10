// PR 2 recovery and external-stationarity trust-boundary regressions.
#include "../eskf15.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>

using namespace inertial;

static uint64_t stamp(unsigned k) { return 1000000ull + static_cast<uint64_t>(k)*5000ull; }
static Imu sample(unsigned k, Vec3 accel={0,0,kGravity}, Vec3 gyro={}) {
    return {stamp(k),accel,gyro};
}
static void initialize(Eskf15& f, unsigned& k, Vec3 accel={0,0,kGravity}) {
    for(unsigned i=0;i<120;i++) f.process(sample(++k,accel));
    assert(f.ready());
}
static float tilt_from_upright(const Eskf15& f) {
    const Vec3 up=f.state().orientation.rotate({0,0,1});
    return std::acos(std::fmax(-1.0f,std::fmin(1.0f,up.z)));
}

static void test_obvious_motion_conflicts_with_stationary_hint() {
    Settings settings; settings.expected_period_us=5000;
    settings.gravity_policy=GravityPolicy::ConfirmedOnly;
    Eskf15 f(settings); unsigned k=0; initialize(f,k);
    f.set_external_stationary_confirmed(true);
    for(unsigned i=0;i<300;i++)
        f.process(sample(++k,{0.4f*kGravity,0,kGravity},{0,0,0}));
    assert(f.gravity_applied_updates()==0);
    assert(tilt_from_upright(f)<0.03f);
    assert(f.external_stationary_conflicts()>=300);

    const uint32_t before=f.gravity_applied_updates();
    for(unsigned i=0;i<160;i++)
        f.process(sample(++k,{0,0,kGravity},{0.18f,0,0}));
    assert(f.gravity_applied_updates()==before);
    assert(f.external_stationary_conflicts()>=460);
    std::puts("PASS obvious IMU motion contradicts and suppresses a stationary hint");
}

static void test_wrong_initial_tilt_requires_trusted_static_recovery() {
    const Vec3 misleading_initial_accel{0.2f*kGravity,0,kGravity};
    Settings settings; settings.expected_period_us=5000;
    settings.gravity_policy=GravityPolicy::Conservative;
    Eskf15 imu_only(settings),trusted(settings);
    unsigned a=0,b=0;
    initialize(imu_only,a,misleading_initial_accel);
    initialize(trusted,b,misleading_initial_accel);
    assert(tilt_from_upright(imu_only)>0.15f);
    assert(tilt_from_upright(trusted)>0.15f);

    for(unsigned i=0;i<500;i++) {
        imu_only.process(sample(++a));
        trusted.process(sample(++b));
    }
    // The acceleration was a plausible but false gravity vector at startup.
    // With only six-axis IMU data the conservative gate must not invent a
    // recovery claim; fresh output and Nominal health do not certify accuracy.
    assert(tilt_from_upright(imu_only)>0.15f);
    assert(imu_only.gravity_applied_updates()==0);
    assert(imu_only.gravity_suppressed_updates()>0);
    assert(imu_only.health()==Health::Nominal && imu_only.control_state_valid());

    trusted.set_external_stationary_confirmed(true);
    for(unsigned i=0;i<500;i++) trusted.process(sample(++b));
    trusted.set_external_stationary_confirmed(false);
    assert(tilt_from_upright(trusted)<0.06f);
    assert(trusted.gravity_applied_updates()>0);
    std::puts("PASS wrong initial tilt stays ambiguous IMU-only and recovers with verified static aid");
}

static void test_in_tolerance_acceleration_remains_unobservable() {
    Settings settings; settings.expected_period_us=5000;
    settings.gravity_policy=GravityPolicy::ConfirmedOnly;
    Eskf15 f(settings); unsigned k=0; initialize(f,k);
    f.set_external_stationary_confirmed(true);
    // 0.2 g has only a 1.98% magnitude deviation from 1 g. A constant
    // acceleration and a false stationarity assertion cannot be separated
    // from gravity using this six-axis measurement stream.
    for(unsigned i=0;i<500;i++)
        f.process(sample(++k,{0.2f*kGravity,0,kGravity},{0,0,0}));
    assert(f.gravity_applied_updates()>0);
    assert(tilt_from_upright(f)>0.12f);
    std::puts("PASS in-tolerance constant acceleration remains an explicit observability limit");
}

int main() {
    test_obvious_motion_conflicts_with_stationary_hint();
    test_wrong_initial_tilt_requires_trusted_static_recovery();
    test_in_tolerance_acceleration_remains_unobservable();
}
