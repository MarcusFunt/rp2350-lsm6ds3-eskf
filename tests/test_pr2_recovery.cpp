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
static void check_finite_covariance(const Eskf15& f) {
    assert(f.covariance_positive_definite());
    for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++)
        assert(std::fabs(f.covariance(i,j)-f.covariance(j,i))<2e-4f);
    for(int i=0;i<kDim;i++) assert(std::isfinite(f.variance(i)) && f.variance(i)>0.0f);
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

static void test_slow_yaw_with_changing_bias_and_heading() {
    Settings settings; settings.expected_period_us=5000;
    settings.gravity_policy=GravityPolicy::Conservative;
    Eskf15 imu_only(settings),heading_aided(settings);
    unsigned a=0,b=0; initialize(imu_only,a); initialize(heading_aided,b);
    constexpr unsigned count=2400;
    constexpr float true_rate=0.035f;
    double max_imu_only_error=0,max_aided_error=0;
    uint32_t heading_updates=0;
    for(unsigned i=0;i<count;i++) {
        const float phase=static_cast<float>(i)/static_cast<float>(count-1);
        const float gyro_bias=0.001f+0.003f*phase;
        const float truth_yaw=true_rate*0.005f*static_cast<float>(i+1);
        const Vec3 gyro{0,0,true_rate+gyro_bias};
        assert(imu_only.process(sample(++a,{0,0,kGravity},gyro)));
        assert(heading_aided.process(sample(++b,{0,0,kGravity},gyro)));
        assert(imu_only.control_state_valid() && heading_aided.control_state_valid());
        if(i%20==19) {
            if(heading_aided.update_heading_at(
                    {heading_aided.state_timestamp_us(),17,0},truth_yaw,0.025f))
                ++heading_updates;
        }
        max_imu_only_error=std::fmax(max_imu_only_error,
            std::fabs(wrap_pi(imu_only.state().orientation.yaw()-truth_yaw)));
        max_aided_error=std::fmax(max_aided_error,
            std::fabs(wrap_pi(heading_aided.state().orientation.yaw()-truth_yaw)));
    }
    assert(heading_updates>100);
    // Availability is asserted above. Accuracy requires an absolute heading
    // source; six-axis IMU-only yaw remains a gauge and accumulates bias.
    assert(max_imu_only_error>0.02);
    assert(max_aided_error<max_imu_only_error*0.5);
    assert(max_aided_error<0.02);
    assert(std::isfinite(heading_aided.state().gyro_bias.z));
    check_finite_covariance(imu_only); check_finite_covariance(heading_aided);
    std::printf("PASS slow yaw with changing gyro bias: IMU-only max %.4f rad, heading-aided max %.4f rad (%u aids)\n",
                max_imu_only_error,max_aided_error,heading_updates);
}

static void test_repeated_reset_reinitialization() {
    Settings settings; settings.expected_period_us=5000;
    settings.gravity_policy=GravityPolicy::ConfirmedOnly;
    Eskf15 f(settings); unsigned k=0;
    for(unsigned cycle=0;cycle<3;cycle++) {
        initialize(f,k);
        assert(f.control_state_valid() && f.health()==Health::Nominal);
        check_finite_covariance(f);
        f.set_external_stationary_confirmed(true);
        for(unsigned i=0;i<12;i++)
            assert(f.process(sample(++k,{0.4f*kGravity,0,kGravity},{0,0,0})));
        assert(f.external_stationary_conflicts()==12);
        assert(f.health()==Health::Nominal && f.control_state_valid());
        f.reset();
        assert(!f.ready() && !f.control_state_valid());
        assert(f.health()==Health::Aligning && !f.reset_required());
        assert(f.external_stationary_conflicts()==0);
    }
    initialize(f,k);
    assert(f.ready() && f.control_state_valid());
    check_finite_covariance(f);
    std::puts("PASS repeated reset and static reinitialization clears lifecycle state");
}

int main() {
    test_obvious_motion_conflicts_with_stationary_hint();
    test_wrong_initial_tilt_requires_trusted_static_recovery();
    test_in_tolerance_acceleration_remains_unobservable();
    test_slow_yaw_with_changing_bias_and_heading();
    test_repeated_reset_reinitialization();
}
