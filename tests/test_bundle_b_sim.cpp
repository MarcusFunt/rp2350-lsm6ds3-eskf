#define BUNDLE_B_NO_MAIN
#include "../tools/benchmark_bundle_b.cpp"

#include <cassert>
#include <cmath>
#include <cstdio>

using namespace inertial;

static float reference_tilt_error_deg(Quat estimated,Quat truth) {
    Vec3 g_est=estimated.unrotate({0,0,1});
    Vec3 g_true=truth.unrotate({0,0,1});
    g_est=g_est*(1.0f/g_est.norm());
    g_true=g_true*(1.0f/g_true.norm());
    return std::acos(std::max(-1.0f,std::min(1.0f,dot(g_est,g_true))))*kRadToDeg;
}

static void test_identity_and_single_axis_tilt() {
    const Quat identity{};
    assert(std::fabs(tilt_error_deg(identity,identity))<1e-5f);
    const Quat roll=Quat::exp({.3f,0,0});
    const Quat pitch=Quat::exp({0,-.25f,0});
    assert(std::fabs(tilt_error_deg(identity,roll)-.3f*kRadToDeg)<1e-3f);
    assert(std::fabs(tilt_error_deg(identity,pitch)-.25f*kRadToDeg)<1e-3f);
}

static void test_world_yaw_gauge_is_not_tilt() {
    const Quat truth=Quat::exp({0,0,.4f})*Quat::exp({0,.3f,0})*Quat::exp({-.2f,0,0});
    const Quat common_world_yaw=Quat::exp({0,0,.8f});
    Quat estimated=common_world_yaw*truth;
    estimated.normalize();
    assert(estimated.unrotate({0,0,1}).norm()>0.99f);
    assert(tilt_error_deg(estimated,truth)<1e-3f);
}

static void test_combined_attitude_matches_body_gravity_geometry() {
    Quat estimated=Quat::exp({0,0,-.45f})*Quat::exp({.35f,0,0})*Quat::exp({0,-.28f,0});
    Quat truth=Quat::exp({0,0,.2f})*Quat::exp({-.12f,0,0})*Quat::exp({0,.31f,0});
    estimated.normalize();truth.normalize();
    assert(std::fabs(tilt_error_deg(estimated,truth)-
                     reference_tilt_error_deg(estimated,truth))<1e-3f);
}

static void test_parallel_and_antiparallel_are_finite() {
    const Quat identity{};
    const Quat near=Quat::exp({1e-7f,-2e-7f,1e-7f});
    const Quat opposite=Quat::exp({kPi,0,0});
    assert(std::isfinite(tilt_error_deg(near,identity)));
    assert(std::isfinite(tilt_error_deg(opposite,identity)));
    assert(std::fabs(tilt_error_deg(opposite,identity)-180.0f)<1e-3f);
}

static void test_exact_stationary_start_boundary() {
    assert(in_verified_stationary_window(1.995f));
    assert(!in_verified_stationary_window(2.0f));
    assert(!in_verified_stationary_window(2.005f));
    for(const char* scene:kScenarioNames) {
        const Motion before=motion(scene,1.995f);
        assert(before.rate.norm()==0.0f&&before.acceleration.norm()==0.0f);
        assert(!in_verified_stationary_window(2.0f));
    }
    assert(motion("slow_yaw",2.0f).rate.norm()>0.0f);
    assert(motion("lateral_accel",2.0f).acceleration.norm()>0.0f);
}

static void test_original_scenario_equations_are_preserved() {
    const float t=5.0f,u=t-2.0f;
    const Motion stationary=motion("static",t);
    assert(stationary.rate.norm()==0.0f&&stationary.acceleration.norm()==0.0f);
    const Motion yaw=motion("slow_yaw",t);
    assert(yaw.rate.x==0.0f&&yaw.rate.y==0.0f&&std::fabs(yaw.rate.z-.035f)<1e-7f);
    const Motion lateral=motion("lateral_accel",t);
    assert(std::fabs(lateral.acceleration.x-.17f*kGravity)<1e-6f);
    assert(motion("lateral_accel",13.0f).acceleration.norm()==0.0f);
    const Motion maneuver=motion("maneuver",t);
    const Motion timing=motion("timing_jitter",t);
    const Motion maneuver_reference{
        {.35f*std::sin(1.3f*u),.27f*std::cos(.7f*u),.35f+.12f*std::sin(.8f*u)},
        {.75f*std::sin(1.2f*u),.65f*std::cos(.9f*u),.25f*std::sin(1.8f*u)}};
    for(const Motion actual:{maneuver,timing}) {
        assert(std::fabs(actual.rate.x-maneuver_reference.rate.x)<1e-6f);
        assert(std::fabs(actual.rate.y-maneuver_reference.rate.y)<1e-6f);
        assert(std::fabs(actual.rate.z-maneuver_reference.rate.z)<1e-6f);
        assert(std::fabs(actual.acceleration.x-maneuver_reference.acceleration.x)<1e-6f);
        assert(std::fabs(actual.acceleration.y-maneuver_reference.acceleration.y)<1e-6f);
        assert(std::fabs(actual.acceleration.z-maneuver_reference.acceleration.z)<1e-6f);
    }
    const Motion vibration=motion("vibration",t);
    assert(std::fabs(vibration.rate.x-.20f*std::sin(.8f*u))<1e-6f);
    assert(std::fabs(vibration.rate.y-.15f*std::sin(1.1f*u))<1e-6f);
    assert(std::fabs(vibration.rate.z-.25f)<1e-6f);
    assert(std::fabs(vibration.acceleration.x-.20f*std::sin(.5f*u))<1e-6f);
    assert(std::fabs(vibration.acceleration.y-.3f*std::cos(1.1f*u))<1e-6f);
}

static void test_legacy_vibration_and_timestamp_jitter_signals() {
    const ScenarioVibration before_start=scenario_vibration("vibration",2.0f);
    assert(before_start.accel_mps2.norm()==0.0f&&before_start.gyro_rps.norm()==0.0f);
    const ScenarioVibration at_peak=scenario_vibration("vibration",2.25f);
    assert(std::fabs(at_peak.accel_mps2.x+.4f)<1e-4f);
    assert(std::fabs(at_peak.accel_mps2.y-.12f)<1e-4f);
    assert(std::fabs(at_peak.accel_mps2.z+.08f)<1e-4f);
    assert(std::fabs(at_peak.gyro_rps.x+.012f)<1e-4f);
    assert(at_peak.gyro_rps.y==0.0f&&at_peak.gyro_rps.z==0.0f);

    assert(scenario_timestamp_jitter_us("vibration",2.5f)==0);
    assert(scenario_timestamp_jitter_us("maneuver",2.5f)==0);
    assert(scenario_timestamp_jitter_us("timing_jitter",2.5f)==-150);
    for(unsigned i=1;i<=3200;i++) {
        const int64_t jitter=scenario_timestamp_jitter_us("timing_jitter",i/200.0f);
        assert(jitter>=-150&&jitter<=150);
    }
}

static void test_velocity_pulse_derivative_and_rest_phases() {
    constexpr float start=.4f,ramp=.8f,hold=2.2f,peak=1.0f;
    assert(smooth_velocity_pulse(start-.01f,start,ramp,hold,peak).velocity_mps==0.0f);
    const auto mid=smooth_velocity_pulse(start+ramp*.5f,start,ramp,hold,peak);
    assert(std::fabs(mid.velocity_mps-.5f*peak)<1e-5f);
    assert(std::fabs(mid.acceleration_mps2-1.875f*peak/ramp)<1e-4f);
    const float h=1e-4f;
    const float v_before=smooth_velocity_pulse(start+ramp*.5f-h,start,ramp,hold,peak).velocity_mps;
    const float v_after=smooth_velocity_pulse(start+ramp*.5f+h,start,ramp,hold,peak).velocity_mps;
    assert(std::fabs((v_after-v_before)/(2*h)-mid.acceleration_mps2)<1e-3f);
    const float finish=start+2*ramp+hold;
    const auto stopped=smooth_velocity_pulse(finish,start,ramp,hold,peak);
    assert(std::fabs(stopped.velocity_mps)<1e-6f);
    assert(std::fabs(stopped.acceleration_mps2)<1e-6f);
}

static void test_scenarios_and_truth_are_bounded() {
    const char* scenes[]={"static","slow_yaw","lateral_accel","maneuver",
                          "vibration","timing_jitter","stop_start","compound_motion"};
    constexpr float dt=1.0f/200.0f;
    for(const char* scene:scenes) {
        Quat truth{};
        for(unsigned i=0;i<3200;i++) {
            const float t=(i+1)*dt;
            const Motion sample=motion(scene,t);
            assert(std::isfinite(sample.rate.norm())&&sample.rate.norm()<1.0f);
            assert(std::isfinite(sample.acceleration.norm())&&sample.acceleration.norm()<7.0f);
            truth=advance_truth(truth,scene,i*dt,dt);
            const float qnorm=std::sqrt(truth.w*truth.w+truth.x*truth.x+truth.y*truth.y+truth.z*truth.z);
            assert(std::isfinite(qnorm)&&std::fabs(qnorm-1.0f)<1e-5f);
        }
    }
    const Motion coupled=motion("compound_motion",4.0f);
    assert(std::fabs(coupled.rate.x)>0.1f&&std::fabs(coupled.rate.y)>0.1f&&std::fabs(coupled.rate.z)>0.1f);
    assert(std::fabs(coupled.acceleration.x)>0.1f&&std::fabs(coupled.acceleration.y)>0.1f);
    const Motion end=motion("stop_start",10.5f);
    assert(end.rate.norm()<1e-6f&&end.acceleration.norm()<1e-6f);
    assert(motion("stop_start",2.0f+.4f+.8f*.5f).acceleration.x>0.0f);
    assert(motion("stop_start",2.0f+.4f+.8f+1.0f).acceleration.norm()<1e-6f);
    assert(motion("stop_start",2.0f+6.0f+.6f+1.0f+.3f).acceleration.y<0.0f);
}

static float quaternion_difference_rad(Quat a,Quat b) {
    Quat e=Quat{a.w,-a.x,-a.y,-a.z}*b;
    e.normalize();
    return 2.0f*std::atan2(std::sqrt(e.x*e.x+e.y*e.y+e.z*e.z),std::fabs(e.w));
}

static void test_truth_step_matches_finer_reference() {
    constexpr float coarse_dt=1.0f/200.0f;
    constexpr float fine_dt=coarse_dt/10.0f;
    for(const char* scene:{"stop_start","compound_motion"}) {
        Quat coarse{};
        for(unsigned i=0;i<3200;i++)coarse=advance_truth(coarse,scene,i*coarse_dt,coarse_dt);
        Quat fine{};
        for(unsigned i=0;i<32000;i++) {
            const float midpoint=(i+.5f)*fine_dt;
            const Motion sample=motion(scene,midpoint);
            fine=fine*Quat::exp(sample.rate*fine_dt);
            fine.normalize();
        }
        assert(quaternion_difference_rad(coarse,fine)<.01f);
    }
}

static bool near(float a,float b,float eps=1e-5f) { return std::fabs(a-b)<eps; }
static void test_nominal_sensor_equations_and_temperature_truth() {
    const SensorModel nominal=sensor_model(SensorProfile::Nominal);
    assert(nominal.accel_axes.apply({1.0f,-2.0f,3.0f}).x==1.0f);
    assert(temperature_delta_c(nominal,16.0f)==0.0f);
    const Vec3 proper{1.2f,-.8f,9.5f},rate{.2f,-.1f,.3f};
    const Vec3 accel_bias{.03f,-.02f,.01f},gyro_bias{.004f,-.003f,.002f};
    const Vec3 accel_noise{.001f,-.002f,.003f},gyro_noise{.0001f,-.0002f,.0003f};
    const Vec3 accel_vibration{.04f,0,-.02f},gyro_vibration{0,.003f,0};
    const SensorReading reading=apply_sensor_model(nominal,proper,rate,accel_bias,gyro_bias,
        accel_noise,gyro_noise,8.0f,accel_vibration,gyro_vibration);
    const Vec3 accel_expected=proper+accel_bias+accel_noise+accel_vibration;
    const Vec3 gyro_expected=rate+gyro_bias+gyro_noise+gyro_vibration;
    assert(near(reading.accel_mps2.x,accel_expected.x)&&near(reading.accel_mps2.y,accel_expected.y)&&near(reading.accel_mps2.z,accel_expected.z));
    assert(near(reading.gyro_rps.x,gyro_expected.x)&&near(reading.gyro_rps.y,gyro_expected.y)&&near(reading.gyro_rps.z,gyro_expected.z));
    assert(!reading.accel_clipped&&!reading.gyro_clipped);
    assert(near(temperature_delta_c(sensor_model(SensorProfile::Stress),2.0f),0.0f));
    assert(near(temperature_delta_c(sensor_model(SensorProfile::Stress),16.0f),6.0f));
    SensorModel stress=sensor_model(SensorProfile::Stress);
    stress.accel_clip_limit_mps2=std::numeric_limits<float>::infinity();
    stress.gyro_clip_limit_rps=std::numeric_limits<float>::infinity();
    stress.accel_quantum_mps2=stress.gyro_quantum_rps=0.0f;
    const SensorReading drifted=apply_sensor_model(stress,proper,rate,accel_bias,gyro_bias,
        accel_noise,gyro_noise,16.0f,{},{});
    assert(near(drifted.true_gyro_bias_rps.x,gyro_bias.x+stress.gyro_temp_bias_per_c.x*6.0f));
    assert(near(drifted.true_accel_bias_mps2.z,accel_bias.z+stress.accel_temp_bias_per_c.z*6.0f));
    const Vec3 expected_measured_accel=stress.accel_axes.apply(proper)+drifted.true_accel_bias_mps2+accel_noise;
    const Vec3 expected_measured_gyro=stress.gyro_axes.apply(rate)+drifted.true_gyro_bias_rps+gyro_noise;
    assert(near(drifted.accel_mps2.x,expected_measured_accel.x)&&near(drifted.accel_mps2.y,expected_measured_accel.y)&&near(drifted.accel_mps2.z,expected_measured_accel.z));
    assert(near(drifted.gyro_rps.x,expected_measured_gyro.x)&&near(drifted.gyro_rps.y,expected_measured_gyro.y)&&near(drifted.gyro_rps.z,expected_measured_gyro.z));
    const SensorReading repeated=apply_sensor_model(stress,proper,rate,accel_bias,gyro_bias,
        accel_noise,gyro_noise,16.0f,{},{});
    assert(near(drifted.accel_mps2.x,repeated.accel_mps2.x));
    assert(near(drifted.gyro_rps.z,repeated.gyro_rps.z));
}

static void test_scale_alignment_and_saturation_contract() {
    AxisTransform transform{2.0f,3.0f,4.0f,.5f,0.0f,-.25f,0.0f,0.0f,.1f};
    const Vec3 mapped=transform.apply({1.0f,2.0f,3.0f});
    assert(near(mapped.x,3.0f)&&near(mapped.y,5.75f)&&near(mapped.z,12.2f));
    unsigned clipped=0;
    const Vec3 bounded=clip_quantize({10.26f,-10.26f,.025f},10.0f,.05f,clipped);
    assert(clipped==1); // one vector sample even though two axes saturate
    assert(near(bounded.x,10.0f)&&near(bounded.y,-10.0f));
    assert(near(bounded.z,.05f)); // half-step ties round away from zero
    const Vec3 negative_tie=clip_quantize({-.025f,0,0},10.0f,.05f,clipped);
    assert(near(negative_tie.x,-.05f));
}

static void test_seed_schedule_and_numeric_parsing() {
    assert(seed_for_trial(20261110u,0,"static")==20261728u);
    assert(seed_for_trial(20261110u,1,"static")==20262737u);
    assert(seed_for_trial(20261110u,0,"compound_motion")==20262655u);
    unsigned parsed=0;
    assert(parse_unsigned_arg("0",parsed)&&parsed==0);
    assert(parse_unsigned_arg("4294967295",parsed)&&parsed==std::numeric_limits<unsigned>::max());
    assert(!parse_unsigned_arg("",parsed));
    assert(!parse_unsigned_arg("-1",parsed));
    assert(!parse_unsigned_arg("12x",parsed));
    assert(!parse_unsigned_arg("4294967296",parsed));
    assert(!parse_unsigned_arg(" 12",parsed));
    assert(!parse_unsigned_arg("+12",parsed));
    assert(seed_schedule_fits(20261110u,200u));
    assert(!seed_schedule_fits(std::numeric_limits<unsigned>::max(),1u));
}

static void test_profiles_reuse_identical_random_draws() {
    SensorModel changed_profile=sensor_model(SensorProfile::Stress);
    const uint64_t original_model_hash=sensor_model_hash(changed_profile);
    changed_profile.gyro_temp_bias_per_c.x+=.00001f;
    assert(sensor_model_hash(changed_profile)!=original_model_hash);
    const unsigned seed=static_cast<unsigned>(seed_for_trial(20261110u,0,"static"));
    const Comparison nominal=simulate("static",0,seed,false,SensorProfile::Nominal);
    const Comparison stress=simulate("static",0,seed,false,SensorProfile::Stress);
    for(const Metrics* model:{&nominal.ekf,&nominal.mahony,&nominal.legacy,
                              &stress.ekf,&stress.mahony,&stress.legacy})
        assert(model->noise_draw_hash==nominal.ekf.noise_draw_hash);
    assert(nominal.ekf.stream_hash==nominal.mahony.stream_hash);
    assert(nominal.ekf.stream_hash==nominal.legacy.stream_hash);
    assert(stress.ekf.stream_hash==stress.mahony.stream_hash);
    assert(stress.ekf.stream_hash==stress.legacy.stream_hash);
    assert(nominal.ekf.stream_hash!=stress.ekf.stream_hash);
}

int main() {
    test_identity_and_single_axis_tilt();
    test_world_yaw_gauge_is_not_tilt();
    test_combined_attitude_matches_body_gravity_geometry();
    test_parallel_and_antiparallel_are_finite();
    test_exact_stationary_start_boundary();
    test_original_scenario_equations_are_preserved();
    test_legacy_vibration_and_timestamp_jitter_signals();
    test_velocity_pulse_derivative_and_rest_phases();
    test_scenarios_and_truth_are_bounded();
    test_truth_step_matches_finer_reference();
    test_nominal_sensor_equations_and_temperature_truth();
    test_scale_alignment_and_saturation_contract();
    test_seed_schedule_and_numeric_parsing();
    test_profiles_reuse_identical_random_draws();
    std::puts("PASS v2 tilt metric geometry");
}
