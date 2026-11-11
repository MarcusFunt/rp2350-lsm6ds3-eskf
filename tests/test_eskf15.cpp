#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include "../eskf15.hpp"

using namespace inertial;
static uint64_t stamp(unsigned k) {return static_cast<uint64_t>(k)*5000;} // 200Hz fixture
static bool near(float a,float b,float tol) {return std::fabs(a-b)<tol;}
static Imu at(unsigned k,Vec3 a={0,0,kGravity},Vec3 w={0,0,0}) {return {stamp(k),a,w};}
static void init(Eskf15& f,unsigned &k) {
    for(unsigned i=0;i<120;i++) f.process(at(++k));
    assert(f.ready());
    assert(f.health()==Health::Nominal);
}
static void check_cov(const Eskf15& f) {
    assert(f.covariance_positive_definite());
    for(int i=0;i<kDim;i++) {
        assert(std::isfinite(f.variance(i)) && f.variance(i)>0.0f);
        for(int j=0;j<kDim;j++)
            assert(std::fabs(f.covariance(i,j)-f.covariance(j,i))<2e-4f);
    }
}
static void test_initialization_and_tilt() {
    Eskf15 f;
    unsigned k=0;
    // A moving startup with big angular rate must not create a false alignment.
    for(int i=0;i<200;i++) f.process(at(++k,{0,0,kGravity},{0,0,1.0f}));
    assert(!f.ready() && f.health()==Health::Aligning);
    constexpr float roll=0.5235987756f;
    const Vec3 tilted{0,std::sin(roll)*kGravity,std::cos(roll)*kGravity};
    for(int i=0;i<120;i++) f.process(at(++k,tilted));
    assert(f.ready());
    const Quat& q=f.state().orientation;
    const float recovered=std::atan2(2*(q.w*q.x+q.y*q.z),1-2*(q.x*q.x+q.y*q.y));
    assert(near(recovered,roll,0.01f));
    assert(f.variance(8)>1.0f); // no compass; yaw is gauge
    check_cov(f);
    std::puts("PASS stable startup gate, static roll alignment, free yaw");
}
static void test_initialization_rejects_slowly_changing_specific_force() {
    Eskf15 f;unsigned k=0;
    // Keep the measured specific-force magnitude at g while its direction
    // changes smoothly. The per-sample change stays below the legacy 0.20
    // m/s^2 limit, but the startup window is not stationary.
    for(unsigned i=1;i<=80;i++) {
        const float x=3.0f*static_cast<float>(i)/80.0f;
        const float z=std::sqrt(kGravity*kGravity-x*x);
        f.process(at(++k,{x,0,z}));
    }
    assert(!f.ready());
    assert(f.health()==Health::Aligning);
    std::puts("PASS startup gate rejects slowly changing specific force");
}
static void test_yaw_and_heading() {
    Eskf15 f;unsigned k=0;init(f,k);
    constexpr float r=kPi/4.0f;
    for(int i=0;i<400;i++) f.process(at(++k,{0,0,kGravity},{0,0,r}));
    assert(near(f.state().orientation.yaw(),kPi/2,0.03f));
    assert(f.update_heading_at({f.state_timestamp_us(),10,0},0.0f,0.05f));
    assert(std::fabs(f.state().orientation.yaw())<0.05f);
    assert(f.accepted_updates()>0);
    check_cov(f);
    std::puts("PASS gyro yaw, independent heading aid, NIS/PSD");
}
static void test_static_noise_bias() {
    Settings cfg; cfg.heuristic_zero_rate=true; // explicit opt-in only
    Eskf15 f(cfg);unsigned k=0;init(f,k);
    for(int i=0;i<1000;i++) f.process(at(++k,{0,0,kGravity},{0,0,0.02f}));
    assert(f.imu_stationary_candidate());
    assert(std::fabs(f.state().gyro_bias.z-0.02f)<0.01f);
    const Quat before=f.state().orientation;
    for(int i=0;i<400;i++) f.process(at(++k,{5,0,kGravity}));
    assert(!f.imu_stationary_candidate());
    assert(std::fabs(f.state().orientation.x-before.x)<0.04f);
    assert(std::fabs(f.state().orientation.y-before.y)<0.04f);
    check_cov(f);
    std::puts("PASS explicitly opted gyro-bias calibration and dynamic tilt gate");
}
static void test_slow_yaw() {
    Eskf15 f;unsigned k=0;init(f,k);
    constexpr float omega=.035f;
    for(int i=0;i<2000;i++) f.process(at(++k,{0,0,kGravity},{0,0,omega}));
    assert(std::fabs(f.state().orientation.yaw()-omega*10.0f)<0.02f);
    std::puts("PASS slow yaw remains enabled by default");
}
static void test_gravity_normalization() {
    // A sudden 10-degree change with zero gyro is not a physically credible
    // IMU trajectory; exercise the legacy correction independently of the
    // conservative motion-aware gate.
    Settings config;config.gravity_policy=GravityPolicy::LegacyHeuristic;
    Eskf15 f(config);unsigned k=0;init(f,k);
    constexpr float roll=0.1745329252f;
    const Vec3 rotated{0,std::sin(roll)*kGravity,std::cos(roll)*kGravity};
    for(int i=0;i<650;i++) f.process(at(++k,rotated));
    const Quat q=f.state().orientation;
    const float recovered=std::atan2(2*(q.w*q.x+q.y*q.z),1-2*(q.x*q.x+q.y*q.y));
    assert(std::fabs(recovered-roll)<0.07f);
    check_cov(f);
    std::puts("PASS normalized gravity-direction correction");
}
static void test_aiding_contract() {
    Settings cfg;cfg.calibration_id=0x1234;
    Eskf15 f(cfg);unsigned k=0;init(f,k);
    const auto now=f.state_timestamp_us();
    assert(!f.update_position_world_at({now-3000,1,0x1234},{2,0,0},.15f));
    assert(!f.update_position_world_at({now+100,1,0x1234},{2,0,0},.15f));
    assert(!f.update_position_world_at({now,1,0xABCD},{2,0,0},.15f));
    assert(f.stale_aiding_updates()==3);
    assert(f.update_position_world_at({now,1,0x1234},{2,1,-1},.15f));
    assert(f.update_velocity_world_at({now,2,0x1234},{1,-1,0.5f},.1f));
    assert(f.state().position.x>1.95f);
    assert(f.state().velocity.y<-.9f);
    assert(f.last_accepted_aid_source()==2);
    assert(f.last_accepted_aid_timestamp_us()==now);
    // Contradictory high-confidence ZUPT is rejected instead of silently applied.
    assert(!f.update_zero_velocity_at({now,3,0x1234},0.02f));
    assert(f.rejected_updates()>0);
    assert(f.last_accepted_aid_source()==2); // rejected aid never replaces provenance
    assert(std::isfinite(f.last_nis()) && f.last_nis()>f.last_nis_gate());
    check_cov(f);
    std::puts("PASS timestamped aids, calibration hash gate, NIS outliers");
}
static void test_gap_faults() {
    Eskf15 f;unsigned k=0;init(f,k);
    const float v0=f.variance(3),theta0=f.variance(6);
    assert(f.process(at(++k)));
    const uint64_t now=f.state_timestamp_us();
    assert(!f.process({now,{0,0,kGravity},{0,0,0}}));
    assert(f.invalid_imu_count()>0);
    assert(f.health()==Health::Degraded);
    assert(!f.process({now+250000,{0,0,kGravity},{0,0,0}}));
    assert(f.gap_count()>0);
    assert(f.state_timestamp_us()==now); // no fake propagation across outage
    assert(f.last_received_timestamp_us()==now+250000);
    assert(f.variance(3)>v0 && f.variance(6)>theta0);
    assert(f.health()==Health::Fault && f.reset_required());
    assert(!f.control_state_valid());
    assert(!f.process({now+255000,{0,0,kGravity},{0,0,0}}));
    assert(f.state_timestamp_us()==now); // explicitly no silent resume
    assert(!f.update_heading_at({now,1,0},0,0.1f));
    f.reset();
    assert(!f.ready() && !f.reset_required());
    for(int i=1;i<=120;i++) f.process({now+260000+static_cast<uint64_t>(i)*5000,{0,0,kGravity},{0,0,0}});
    assert(f.ready() && f.health()==Health::Nominal);
    assert(!f.process({f.state_timestamp_us()+5000,{4*kGravity,0,0},{0,0,0}}));
    assert(f.saturation_count()==1 && f.health()==Health::Fault && f.reset_required());
    check_cov(f);
    std::puts("PASS duplicate timestamp, missing data uncertainty, saturation fault");
}
static void test_missing_single_frame() {
    Eskf15 f;unsigned k=0;init(f,k);
    for(int i=0;i<4;i++) f.process(at(++k));
    ++k; // missing sample in a 200Hz stream
    assert(f.process(at(++k)));
    assert(f.gap_count()==1 && f.health()==Health::Degraded);
    std::puts("PASS single missing sample detected");
}
static void test_replay_determinism() {
    Eskf15 a,b;
    for(unsigned i=1;i<=1800;i++) {
        const Imu sample={stamp(i),
                          {0.10f*std::sin(i*.017f),0.10f*std::cos(i*.011f),kGravity},
                          {0.03f*std::sin(i*.021f),0.02f*std::cos(i*.019f),0.025f}};
        const bool ra=a.process(sample),rb=b.process(sample);
        assert(ra==rb);
    }
    assert(a.ready()&&b.ready());
    assert(a.state().orientation.w==b.state().orientation.w);
    assert(a.state().velocity.x==b.state().velocity.x);
    assert(a.last_nis()==b.last_nis());
    check_cov(a);
    std::puts("PASS deterministic synthetic IMU replay, covariance positive definite");
}

static void test_tilted_yaw_gauge() {
    Eskf15 f;unsigned k=0;
    const float roll=0.872664626f; // 50 degrees
    const Vec3 accel{0,std::sin(roll)*kGravity,std::cos(roll)*kGravity};
    for(int i=0;i<90;i++) f.process(at(++k,accel));
    assert(f.ready());
    const Vec3 u=f.state().orientation.unrotate({0,0,1});
    const float axis[3]={u.x,u.y,u.z};
    float gauge_variance=0;
    for(int i=0;i<3;i++) for(int j=0;j<3;j++)
        gauge_variance+=axis[i]*f.covariance(6+i,6+j)*axis[j];
    assert(near(gauge_variance,kPi*kPi,0.02f));
    assert(std::fabs(f.covariance(7,8))>1.0f);
    check_cov(f);
    std::puts("PASS yaw gauge correctly rotated into tilted body-error frame");
}
static void test_outage_contract() {
    // Short gaps remain usable but degraded; longer ones latch and require
    // explicit reset, never presenting the old state as a current prediction.
    Eskf15 f;unsigned k=0;init(f,k);
    assert(f.control_state_valid());
    const uint64_t t=f.state_timestamp_us();
    assert(f.process({t+20000,{0,0,kGravity},{0,0,0}}));
    assert(f.state_timestamp_us()==t+20000);
    assert(f.health()==Health::Degraded && f.control_state_valid());
    assert(!f.process({t+20000+30000,{0,0,kGravity},{0,0,0}}));
    assert(f.reset_required() && !f.control_state_valid());
    const auto stale=f.state_timestamp_us();
    for(int i=1;i<=10;i++) assert(!f.process({t+50000ull+i*5000ull,{0,0,kGravity},{0,0,0}}));
    assert(f.state_timestamp_us()==stale && f.last_received_timestamp_us()>stale);
    f.reset();
    assert(!f.ready());
    std::puts("PASS short-gap recovery, long-gap latch, reset and timestamp invariants");
}

int main() {
    test_initialization_and_tilt();test_initialization_rejects_slowly_changing_specific_force();
    test_yaw_and_heading();test_static_noise_bias();
    test_slow_yaw();test_gravity_normalization();test_aiding_contract();
    test_gap_faults();test_missing_single_frame();test_replay_determinism();
    test_tilted_yaw_gauge();test_outage_contract();
    std::puts("All report-revision ESKF host tests passed.");
}
