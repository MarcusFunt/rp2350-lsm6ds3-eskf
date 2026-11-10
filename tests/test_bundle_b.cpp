#include <cassert>
#include <cmath>
#include <cstdio>
#include "../eskf15.hpp"
using namespace inertial;

static void feed(Eskf15 &f,unsigned begin,unsigned end,Vec3 a={0,0,kGravity},Vec3 w={}) {
    for(unsigned i=begin;i<=end;i++)f.process({1000000ull+i*5000ull,a,w});
}
static float tilt(Quat q){
    const Vec3 up=q.rotate({0,0,1});
    const float v=std::fmax(-1.0f,std::fmin(1.0f,up.z));
    return std::acos(v);
}
static void test_bias_opt_in(){
    const Vec3 b{.018f,-.010f,.024f};
    Eskf15 no_opt;feed(no_opt,1,120,{0,0,kGravity},b);
    assert(no_opt.ready() && !no_opt.startup_bias_calibrated());
    assert(no_opt.state().gyro_bias.norm()==0.0f);
    Settings cfg;cfg.startup_gyro_bias_calibration=true;
    Eskf15 opt(cfg);opt.set_external_stationary_confirmed(true);feed(opt,1,120,{0,0,kGravity},b);
    opt.set_external_stationary_confirmed(false);
    assert(opt.ready()&&opt.startup_bias_calibrated());
    assert((opt.state().gyro_bias-b).norm()<1e-6f);
    for(unsigned i=121;i<=1120;i++) {
        const Imu s{1000000ull+i*5000ull,{0,0,kGravity},b};
        no_opt.process(s);opt.process(s);
    }
    assert(std::fabs(opt.state().orientation.yaw())<.008f);
    assert(std::fabs(no_opt.state().orientation.yaw())>.05f);
    std::puts("PASS startup gyro-bias estimation requires explicit opt-in");
}
static void test_false_tilt(){
    Settings c;c.gravity_policy=GravityPolicy::Conservative;
    Settings l=c;l.gravity_policy=GravityPolicy::LegacyHeuristic;
    Eskf15 conservative(c),legacy(l);
    feed(conservative,1,120);feed(legacy,1,120);
    const Vec3 a{.17f*kGravity,0,kGravity};
    feed(conservative,121,1720,a);feed(legacy,121,1720,a);
    assert(conservative.ready()&&legacy.ready());
    assert(conservative.gravity_suppressed_updates()>0);
    assert(tilt(conservative.state().orientation)<.08f);
    assert(tilt(legacy.state().orientation)>.1f);
    // A slow enough apparent acceleration cannot be perfectly detected by
    // a six-axis IMU. This test claims only suppression of this particular case.
    std::puts("PASS sustained 0.17 g false tilt suppressed without external aiding");
}
static void test_external_stationary_confirmation(){
    Settings cfg;cfg.gravity_policy=GravityPolicy::ConfirmedOnly;
    Eskf15 f(cfg);feed(f,1,120);
    feed(f,121,300,{0,0,kGravity});
    assert(f.gravity_applied_updates()==0);
    f.set_external_stationary_confirmed(true);
    feed(f,301,520);
    assert(f.gravity_applied_updates()>0);
    f.set_external_stationary_confirmed(false);
    const auto before=f.gravity_applied_updates();
    feed(f,521,720);
    assert(f.gravity_applied_updates()==before);
    std::puts("PASS independently confirmed stationary-only gravity aiding");
}
static void test_bias_requires_stable_window(){
    Settings cfg;cfg.startup_gyro_bias_calibration=true;
    cfg.startup_gyro_stddev_limit=.010f;
    Eskf15 f(cfg);f.set_external_stationary_confirmed(true);
    // Motion with plausible 1 g acceleration but varying gyro must NOT be
    // interpreted as a zero-rate calibration window.
    for(unsigned i=1;i<=160;i++) {
        const float gyro=(i%2)?0.06f:-0.06f;
        f.process({1000000ull+i*5000ull,{0,0,kGravity},{0,0,gyro}});
    }
    assert(f.ready());
    assert(!f.startup_bias_calibrated());
    std::puts("PASS excessive gyro variance rejects startup calibration");
}
int main(){
    test_bias_opt_in();test_false_tilt();
    test_external_stationary_confirmation();test_bias_requires_stable_window();
    std::puts("Bundle B unit tests passed.");
}
