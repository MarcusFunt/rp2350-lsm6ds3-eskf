// Deterministic host-only comparison using one synthetic IMU stream shared by
// all estimators in each trial/profile. NOT measured hardware or certification.
#include "../eskf15.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numeric>
#include <random>
#include <sstream>
#include <string>
#include <vector>

using namespace inertial;
constexpr float kRadToDeg = 180.0f/kPi;
constexpr unsigned kSampleRateHz=200;
constexpr unsigned kDurationSeconds=16;
constexpr unsigned kSampleCount=kSampleRateHz*kDurationSeconds;
constexpr float kHz=static_cast<float>(kSampleRateHz);
constexpr float kDt=1.0f/kHz;
constexpr unsigned kSchemaVersion=2;
constexpr unsigned kMetricDefinitionVersion=2;
constexpr unsigned kSeedScheduleVersion=1;
constexpr unsigned kTruthIntegrationVersion=2;
constexpr float kTemperatureRampStartSeconds=2.0f;
constexpr float kTemperatureRampDurationSeconds=14.0f;
constexpr float kStressTemperatureRiseC=6.0f;
constexpr float kAccelNoiseDensityMps2PerSqrtHz=.0015f;
constexpr float kGyroNoiseDensityRpsPerSqrtHz=.00025f;
constexpr float kAccelBiasWalkMps2PerSqrtSecond=.00008f;
constexpr float kGyroBiasWalkRpsPerSqrtSecond=.00003f;
const Vec3 kInitialAccelBiasMps2{.018f,-.012f,.024f};
const Vec3 kInitialGyroBiasRps{.008f,-.006f,.018f};
#define BUNDLE_B_STRINGIFY_IMPL(value) #value
#define BUNDLE_B_STRINGIFY(value) BUNDLE_B_STRINGIFY_IMPL(value)
#if defined(__GLIBCXX__)
constexpr const char* kStandardLibraryVersion="libstdc++-" BUNDLE_B_STRINGIFY(__GLIBCXX__);
#elif defined(_LIBCPP_VERSION)
constexpr const char* kStandardLibraryVersion="libc++-" BUNDLE_B_STRINGIFY(_LIBCPP_VERSION);
#elif defined(_MSVC_STL_VERSION)
constexpr const char* kStandardLibraryVersion="msvc-stl-" BUNDLE_B_STRINGIFY(_MSVC_STL_VERSION);
#else
constexpr const char* kStandardLibraryVersion="unavailable";
#endif
const char* const kScenarioNames[]={"static","slow_yaw","lateral_accel","maneuver",
                                    "vibration","timing_jitter","stop_start","compound_motion"};
float smoothstep01(float x);

uint64_t seed_for_trial(unsigned base_seed,unsigned trial_id,const std::string& scenario) {
    // v1 preserves the historical name-length offsets for the six original scenarios.
    return static_cast<uint64_t>(base_seed)+1009ull*trial_id+103ull*scenario.size();
}
bool seed_schedule_fits(unsigned base_seed,unsigned trials) {
    if(!trials)return false;
    for(const char* scene:kScenarioNames)
        if(seed_for_trial(base_seed,trials-1,scene)>std::numeric_limits<unsigned>::max())return false;
    return true;
}
bool parse_unsigned_arg(const char* text,unsigned& result) {
    if(!text||!*text)return false;
    for(const char* p=text;*p;++p)if(*p<'0'||*p>'9')return false;
    errno=0;
    char* end=nullptr;
    const unsigned long long parsed=std::strtoull(text,&end,10);
    if(errno==ERANGE||end==text||*end!='\0'||parsed>std::numeric_limits<unsigned>::max())return false;
    result=static_cast<unsigned>(parsed);
    return true;
}

enum class SensorProfile { Nominal, Stress };
const char* sensor_profile_name(SensorProfile profile) {
    return profile==SensorProfile::Nominal ? "nominal" : "stress";
}

struct AxisTransform {
    float sx=1.0f,sy=1.0f,sz=1.0f;
    float xy=0.0f,xz=0.0f,yx=0.0f,yz=0.0f,zx=0.0f,zy=0.0f;
    Vec3 apply(Vec3 v) const {
        return {sx*v.x+xy*v.y+xz*v.z,
                yx*v.x+sy*v.y+yz*v.z,
                zx*v.x+zy*v.y+sz*v.z};
    }
};

// Explicitly synthetic residual calibration and temperature parameters.
// Matrix off-diagonal terms are dimensionless axis coupling ratios.
const AxisTransform kStressAccelAxes{1.004f,.997f,1.002f,.0012f,-.0008f,-.0010f,.0009f,.0007f,-.0011f};
const AxisTransform kStressGyroAxes{1.005f,.997f,1.003f,-.0011f,.0008f,.0010f,-.0007f,-.0008f,.0012f};
const Vec3 kStressAccelTempBiasMps2PerC{.012f,-.008f,.015f};
const Vec3 kStressGyroTempBiasRpsPerC{.00045f,-.00025f,.00035f};
constexpr float kStressAccelClipLimitMps2=60.0f;
constexpr float kStressGyroClipLimitRps=10.0f;
constexpr float kStressAccelQuantizationMps2=.005f;
constexpr float kStressGyroQuantizationRps=.00025f;

// Nominal noise values and stress-profile effects are illustrative, not
// calibrated LSM6DS3 characteristics or claims about the firmware range.
struct SensorModel {
    float accel_density=kAccelNoiseDensityMps2PerSqrtHz; // m/s^2/sqrt(Hz)
    float gyro_density=kGyroNoiseDensityRpsPerSqrtHz;     // rad/s/sqrt(Hz)
    float accel_walk=kAccelBiasWalkMps2PerSqrtSecond;     // m/s^2/sqrt(s)
    float gyro_walk=kGyroBiasWalkRpsPerSqrtSecond;        // rad/s/sqrt(s)
    AxisTransform accel_axes,gyro_axes;
    Vec3 accel_temp_bias_per_c{},gyro_temp_bias_per_c{};
    float temperature_rise_c=0.0f; // synthetic rise after the startup window
    float temperature_ramp_start_s=kTemperatureRampStartSeconds;
    float temperature_ramp_duration_s=kTemperatureRampDurationSeconds;
    float accel_clip_limit_mps2=std::numeric_limits<float>::infinity();
    float gyro_clip_limit_rps=std::numeric_limits<float>::infinity();
    float accel_quantum_mps2=0.0f;
    float gyro_quantum_rps=0.0f;
};

SensorModel sensor_model(SensorProfile profile) {
    SensorModel model;
    if(profile==SensorProfile::Stress) {
        model.accel_axes=kStressAccelAxes;
        model.gyro_axes=kStressGyroAxes;
        model.accel_temp_bias_per_c=kStressAccelTempBiasMps2PerC;
        model.gyro_temp_bias_per_c=kStressGyroTempBiasRpsPerC;
        model.temperature_rise_c=kStressTemperatureRiseC;
        model.accel_clip_limit_mps2=kStressAccelClipLimitMps2;
        model.gyro_clip_limit_rps=kStressGyroClipLimitRps;
        model.accel_quantum_mps2=kStressAccelQuantizationMps2;
        model.gyro_quantum_rps=kStressGyroQuantizationRps;
    }
    return model;
}

float temperature_delta_c(const SensorModel& model,float t) {
    return model.temperature_rise_c*
           smoothstep01((t-model.temperature_ramp_start_s)/model.temperature_ramp_duration_s);
}

Vec3 clip_quantize(Vec3 value,float limit,float quantum,unsigned& clipped_samples) {
    bool clipped=false;
    const auto convert=[&](float component) {
        const float bounded=std::max(-limit,std::min(limit,component));
        clipped=clipped || bounded!=component;
        return quantum>0.0f ? std::round(bounded/quantum)*quantum : bounded;
    };
    const Vec3 result{convert(value.x),convert(value.y),convert(value.z)};
    if(clipped)++clipped_samples; // vector samples with at least one saturated axis
    return result;
}

struct SensorReading {
    Vec3 accel_mps2{},gyro_rps{};
    Vec3 true_accel_bias_mps2{},true_gyro_bias_rps{};
    bool accel_clipped=false,gyro_clipped=false;
};
SensorReading apply_sensor_model(const SensorModel& model,Vec3 proper_accel,Vec3 angular_rate,
                                 Vec3 accel_bias,Vec3 gyro_bias,Vec3 accel_noise,
                                 Vec3 gyro_noise,float t,Vec3 vibration_accel={},
                                 Vec3 vibration_gyro={}) {
    const float delta_c=temperature_delta_c(model,t);
    const Vec3 thermal_accel=model.accel_temp_bias_per_c*delta_c;
    const Vec3 thermal_gyro=model.gyro_temp_bias_per_c*delta_c;
    const Vec3 true_accel_bias=accel_bias+thermal_accel;
    const Vec3 true_gyro_bias=gyro_bias+thermal_gyro;
    unsigned accel_clips=0,gyro_clips=0;
    const Vec3 accel=clip_quantize(model.accel_axes.apply(proper_accel)+true_accel_bias+
                                   accel_noise+vibration_accel,
                                   model.accel_clip_limit_mps2,model.accel_quantum_mps2,accel_clips);
    const Vec3 gyro=clip_quantize(model.gyro_axes.apply(angular_rate)+true_gyro_bias+
                                  gyro_noise+vibration_gyro,
                                  model.gyro_clip_limit_rps,model.gyro_quantum_rps,gyro_clips);
    return {accel,gyro,true_accel_bias,true_gyro_bias,accel_clips>0,gyro_clips>0};
}

struct Motion {Vec3 rate, acceleration;};
float smoothstep01(float x) {
    x=std::max(0.0f,std::min(1.0f,x));
    return x*x*x*(10.0f+x*(-15.0f+6.0f*x));
}
float smoothstep01_derivative(float x) {
    x=std::max(0.0f,std::min(1.0f,x));
    return 30.0f*x*x*(1.0f-x)*(1.0f-x);
}
float smooth_pulse(float t,float start,float end,float ramp) {
    return smoothstep01((t-start)/ramp)*smoothstep01((end-t)/ramp);
}
bool in_verified_stationary_window(float t) { return t<2.0f; }
struct VelocityPulse {float velocity_mps=0.0f,acceleration_mps2=0.0f;};
VelocityPulse smooth_velocity_pulse(float t,float start,float ramp,float hold,float peak) {
    const float elapsed=t-start;
    if(elapsed<0.0f)return {};
    if(elapsed<ramp) {
        const float phase=elapsed/ramp;
        return {peak*smoothstep01(phase),peak*smoothstep01_derivative(phase)/ramp};
    }
    if(elapsed<ramp+hold)return {peak,0.0f};
    if(elapsed<2.0f*ramp+hold) {
        const float phase=(elapsed-ramp-hold)/ramp;
        return {peak*(1.0f-smoothstep01(phase)),-peak*smoothstep01_derivative(phase)/ramp};
    }
    return {};
}
Motion motion(const std::string& scenario, float t) {
    if(in_verified_stationary_window(t)) return {};
    const float u=t-2.0f;
    if(scenario=="static") return {};
    if(scenario=="slow_yaw") return {{0,0,.035f},{}};
    if(scenario=="lateral_accel")
        return {{},(u<10.0f)?Vec3{.17f*kGravity,0,0}:Vec3{}};
    if(scenario=="stop_start") {
        const auto first=smooth_velocity_pulse(u,.4f,.8f,2.2f,1.2f);
        const auto second=smooth_velocity_pulse(u,6.0f,.6f,1.0f,.75f);
        const float first_turn=smooth_pulse(u,.4f,4.2f,.8f);
        const float second_turn=smooth_pulse(u,6.0f,8.2f,.6f);
        return {{.25f*first_turn,-.18f*second_turn,.20f*first_turn},
                {first.acceleration_mps2,second.acceleration_mps2,0.0f}};
    }
    if(scenario=="compound_motion") {
        // Coupled high-dynamic trajectory remains below the synthetic clip limits.
        const float envelope=smooth_pulse(u,.25f,13.5f,1.0f);
        return {{envelope*.28f*std::sin(.7f*u),
                 envelope*.22f*std::cos(.45f*u),
                 envelope*(.32f+.10f*std::sin(.3f*u))},
                {envelope*4.5f*std::sin(1.0f*u),
                 envelope*3.5f*std::cos(.8f*u),
                 envelope*2.0f*std::sin(1.3f*u)}};
    }
    if(scenario=="maneuver" || scenario=="timing_jitter")
        return {{.35f*std::sin(1.3f*u),.27f*std::cos(.7f*u),.35f+.12f*std::sin(.8f*u)},
                {0.75f*std::sin(1.2f*u),0.65f*std::cos(.9f*u),.25f*std::sin(1.8f*u)}};
    if(scenario=="vibration")
        return {{.20f*std::sin(.8f*u),.15f*std::sin(1.1f*u),.25f},
                {0.20f*std::sin(.5f*u),0.3f*std::cos(1.1f*u),0}};
    std::fprintf(stderr,"Unknown scenario: %s\n",scenario.c_str()); std::exit(2);
}

bool quaternion_is_finite(Quat q) {
    return std::isfinite(q.w)&&std::isfinite(q.x)&&std::isfinite(q.y)&&std::isfinite(q.z);
}
Quat advance_truth(Quat truth,const std::string& scenario,float interval_start,float dt) {
    const Motion midpoint=motion(scenario,interval_start+.5f*dt);
    Quat next=truth*Quat::exp(midpoint.rate*dt);
    const float norm=std::sqrt(next.w*next.w+next.x*next.x+next.y*next.y+next.z*next.z);
    if(!(norm>1e-12f)||!std::isfinite(norm))return {NAN,NAN,NAN,NAN};
    next.normalize();
    return next;
}

// Reference baseline: simple Mahony proportional/integral attitude correction,
// always using the normalized accelerometer. Same samples and initial 2 seconds
// as the ESKF. No heading/reference updates or navigation position estimation.
class Mahony {
public:
    Quat q{};
    Vec3 bias{};
    bool ready=false;
    explicit Mahony(bool startup_bias): startup_bias_(startup_bias) {}
    bool process(const Imu& s, bool allowed_stationary_start) {
        if(!ready) {
            if(!allowed_stationary_start) return false;
            accel_sum_=accel_sum_+s.accel_mps2;
            gyro_sum_=gyro_sum_+s.gyro_rps;
            if(++count_<80) return false;
            q=Quat::from_to(accel_sum_*(1.0f/count_),{0,0,kGravity});
            if(startup_bias_)bias=gyro_sum_*(1.0f/count_);
            ready=true;
            last_us_=s.timestamp_us;
            return false;
        }
        if(s.timestamp_us<=last_us_) return false;
        const float dt=(s.timestamp_us-last_us_)*1e-6f;
        last_us_=s.timestamp_us;
        if(dt>0.025f)return false;
        Vec3 w=s.gyro_rps-bias;
        const float n=s.accel_mps2.norm();
        if(n>1e-4f) {
            const Vec3 a=s.accel_mps2*(1.0f/n);
            const Vec3 g=q.unrotate({0,0,1});
            const Vec3 e=cross(a,g);
            constexpr float kp=1.0f,ki=0.05f;
            w=w+e*kp;
            // bias integrates opposite proportional gyro correction
            bias=bias-e*(ki*dt);
        }
        q=q*Quat::exp(w*dt);q.normalize();
        return true;
    }
private:
    uint64_t last_us_=0;
    unsigned count_=0;
    Vec3 accel_sum_{},gyro_sum_{};
    bool startup_bias_;
};

struct Metrics {
    std::string scenario,sensor_profile,model;
    unsigned trial_id=0,seed=0;
    unsigned expected=0,valid=0,initialized=0;
    unsigned uninitialized_samples=0,invalid_samples=0,degraded_samples=0,faulted_samples=0;
    unsigned accel_clip_samples=0,gyro_clip_samples=0;
    uint64_t stream_hash=14695981039346656037ull,noise_draw_hash=14695981039346656037ull;
    double sum_tilt_sq=0,sum_yaw_sq=0,nees_sum=0,nis_sum=0;
    unsigned nees_count=0,nees95=0,nis_count=0;
    float max_tilt=0;
    std::vector<float> tilt_errors;
    float last_gyro_bias_error=std::numeric_limits<float>::quiet_NaN();
    unsigned suppressed=0,accepted_gravity=0;
    std::string valid_mask;
    double tilt_rms()const{return valid?std::sqrt(sum_tilt_sq/valid):NAN;}
    double yaw_rms()const{return valid?std::sqrt(sum_yaw_sq/valid):NAN;}
    double p95() {if(tilt_errors.empty())return NAN;std::sort(tilt_errors.begin(),tilt_errors.end());return tilt_errors[static_cast<size_t>(.95*(tilt_errors.size()-1))];}
    void add(float tilt_deg,float yaw_deg){++valid;sum_tilt_sq+=tilt_deg*tilt_deg;sum_yaw_sq+=yaw_deg*yaw_deg;
        max_tilt=std::max(max_tilt,tilt_deg);tilt_errors.push_back(tilt_deg);valid_mask.push_back('1');}
    void invalid(bool initialized_state){
        if(initialized_state)++invalid_samples;else ++uninitialized_samples;
        valid_mask.push_back('0');
    }
};

void hash_bytes(uint64_t& hash,const void* data,size_t size) {
    const auto* bytes=static_cast<const unsigned char*>(data);
    for(size_t i=0;i<size;i++){hash^=bytes[i];hash*=1099511628211ull;}
}
void hash_sample(uint64_t& hash,const Imu& sample) {
    hash_bytes(hash,&sample.timestamp_us,sizeof(sample.timestamp_us));
    hash_bytes(hash,&sample.accel_mps2.x,sizeof(float));
    hash_bytes(hash,&sample.accel_mps2.y,sizeof(float));
    hash_bytes(hash,&sample.accel_mps2.z,sizeof(float));
    hash_bytes(hash,&sample.gyro_rps.x,sizeof(float));
    hash_bytes(hash,&sample.gyro_rps.y,sizeof(float));
    hash_bytes(hash,&sample.gyro_rps.z,sizeof(float));
}

float tilt_error(Quat est,Quat truth){
    Vec3 g_est=est.unrotate({0,0,1});
    Vec3 g_truth=truth.unrotate({0,0,1});
    const float n_est=g_est.norm(),n_truth=g_truth.norm();
    if(!(n_est>1e-12f) || !(n_truth>1e-12f) ||
       !std::isfinite(n_est) || !std::isfinite(n_truth))return NAN;
    g_est=g_est*(1.0f/n_est);
    g_truth=g_truth*(1.0f/n_truth);
    const float cosine=std::max(-1.0f,std::min(1.0f,dot(g_est,g_truth)));
    return std::acos(cosine)*kRadToDeg;
}

float tilt_error_deg(Quat est,Quat truth){
    return tilt_error(est,truth);
}

// Only 2D world-horizontal attitude error NEES. World yaw is an unobservable
// gauge, so the full 3D attitude NEES is not meaningful without a heading aid.
// Also note: the gravity pseudo-measurement shares IMU data with propagation;
// hence ideal chi-square coverage is only a diagnostic, not a rigorous test.
void update_nees(const Eskf15 &ekf,Quat truth,Metrics &m){
    Quat e=Quat{ekf.state().orientation.w,-ekf.state().orientation.x,
        -ekf.state().orientation.y,-ekf.state().orientation.z}*truth;
    e.normalize();
    if(e.w<0){e.w=-e.w;e.x=-e.x;e.y=-e.y;e.z=-e.z;}
    const float angle=2.0f*std::atan2(std::sqrt(e.x*e.x+e.y*e.y+e.z*e.z),e.w);
    const float denom=std::sqrt(e.x*e.x+e.y*e.y+e.z*e.z);
    const Vec3 local=(denom>1e-10f)?Vec3{e.x,e.y,e.z}*(angle/denom):Vec3{};
    const Vec3 world=ekf.state().orientation.rotate(local);
    const Vec3 bx=ekf.state().orientation.unrotate({1,0,0});
    const Vec3 by=ekf.state().orientation.unrotate({0,1,0});
    const float U[2][3]={{bx.x,bx.y,bx.z},{by.x,by.y,by.z}};
    float cov[2][2]={};
    for(int i=0;i<2;i++)for(int j=0;j<2;j++)for(int a=0;a<3;a++)for(int b=0;b<3;b++)
        cov[i][j]+=U[i][a]*ekf.covariance(6+a,6+b)*U[j][b];
    const double det=static_cast<double>(cov[0][0])*cov[1][1]-static_cast<double>(cov[0][1])*cov[1][0];
    if(!(det>1e-16))return;
    const double nees=(cov[1][1]*world.x*world.x+
        cov[0][0]*world.y*world.y-2.0*cov[0][1]*world.x*world.y)/det;
    if(std::isfinite(nees)) {m.nees_sum+=nees;++m.nees_count;if(nees<5.99146)++m.nees95;}
}

struct Comparison{Metrics ekf,mahony,legacy;};

struct ScenarioVibration {
    Vec3 accel_mps2{};
    Vec3 gyro_rps{};
};

ScenarioVibration scenario_vibration(const std::string& scene,float t) {
    if(scene!="vibration" || t<=2.0f)return {};
    const float v=.40f*std::sin(2*kPi*43.0f*t);
    return {{v,-.3f*v,.2f*v},{.012f*std::sin(2*kPi*31.0f*t),0,0}};
}

int64_t scenario_timestamp_jitter_us(const std::string& scene,float t) {
    if(scene!="timing_jitter")return 0;
    return static_cast<int64_t>(std::lround(150.0*std::sin(2.0*kPi*2.3*t)));
}

Comparison simulate(const std::string& scene,unsigned trial_id,unsigned seed,
                    bool startup_bias,SensorProfile profile) {
    const SensorModel model=sensor_model(profile);
    Settings cfg;
    cfg.accel_noise=model.accel_density;
    cfg.gyro_noise=model.gyro_density;
    cfg.accel_bias_walk=model.accel_walk;
    cfg.gyro_bias_walk=model.gyro_walk;
    cfg.gravity_policy=GravityPolicy::Conservative;
    cfg.startup_gyro_bias_calibration=startup_bias;
    // Initialization has an independently verified initial 2-second static window
    // in this synthetic ground-truth trajectory (not a sensor-only detector).
    Eskf15 ekf(cfg);
    cfg.gravity_policy=GravityPolicy::LegacyHeuristic;
    Eskf15 legacy(cfg);
    Mahony mahony(startup_bias);
    Metrics a,b,c;
    a.scenario=b.scenario=c.scenario=scene;
    a.sensor_profile=b.sensor_profile=c.sensor_profile=sensor_profile_name(profile);
    a.model="eskf_conservative";b.model="mahony";c.model="eskf_legacy";
    a.trial_id=b.trial_id=c.trial_id=trial_id;
    a.seed=b.seed=c.seed=seed;
    std::mt19937 rng(seed);
    std::normal_distribution<float> standard(0.0f,1.0f);
    uint64_t noise_draw_hash=14695981039346656037ull;
    const auto gaussian=[&rng,&standard,&noise_draw_hash](){
        const float draw=standard(rng);hash_bytes(noise_draw_hash,&draw,sizeof(draw));return draw;
    };
    const float acc_sigma=model.accel_density*std::sqrt(kHz);
    const float gyr_sigma=model.gyro_density*std::sqrt(kHz);
    const float acc_step=model.accel_walk*std::sqrt(kDt);
    const float gyr_step=model.gyro_walk*std::sqrt(kDt);
    Quat truth{};
    Vec3 accel_bias=kInitialAccelBiasMps2,gyro_bias=kInitialGyroBiasRps;
    unsigned accel_clip_samples=0,gyro_clip_samples=0;
    for(unsigned i=1;i<=kSampleCount;i++) { // 16 seconds at 200 Hz
        const float t=i*kDt;
        const Motion m=motion(scene,t);
        truth=advance_truth(truth,scene,t-kDt,kDt);
        if(!quaternion_is_finite(truth)) {
            std::fprintf(stderr,"Non-finite truth orientation in scenario %s at %.6f s\n",scene.c_str(),t);
            std::exit(2);
        }
        accel_bias=accel_bias+Vec3{gaussian()*acc_step,gaussian()*acc_step,gaussian()*acc_step};
        gyro_bias=gyro_bias+Vec3{gaussian()*gyr_step,gaussian()*gyr_step,gaussian()*gyr_step};
        const Vec3 proper=truth.unrotate(m.acceleration+Vec3{0,0,kGravity});
        const Vec3 accel_noise{gaussian()*acc_sigma,gaussian()*acc_sigma,gaussian()*acc_sigma};
        const Vec3 gyro_noise{gaussian()*gyr_sigma,gaussian()*gyr_sigma,gaussian()*gyr_sigma};
        // Deterministic, correlated high-frequency disturbance only.
        const ScenarioVibration vibration=scenario_vibration(scene,t);
        const SensorReading sensor=apply_sensor_model(model,proper,m.rate,accel_bias,gyro_bias,
            accel_noise,gyro_noise,t,vibration.accel_mps2,vibration.gyro_rps);
        if(sensor.accel_clipped)++accel_clip_samples;
        if(sensor.gyro_clipped)++gyro_clip_samples;
        // Only in timing_jitter: timestamps drift by up to +/-150 us around
        // the real 5 ms acquisition instants. This models measurement-time
        // metadata error, NOT a proven RP2350 interrupt-jitter distribution.
        const int64_t timestamp_jitter=scenario_timestamp_jitter_us(scene,t);
        const Imu sample{static_cast<uint64_t>(1000000ull+static_cast<uint64_t>(i)*5000ull+
            timestamp_jitter),sensor.accel_mps2,sensor.gyro_rps};
        hash_sample(a.stream_hash,sample);
        const bool verified_stationary=in_verified_stationary_window(t);
        ekf.set_external_stationary_confirmed(verified_stationary);
        legacy.set_external_stationary_confirmed(verified_stationary);
        ekf.process(sample);legacy.process(sample);mahony.process(sample,verified_stationary);
        if(verified_stationary)continue;
        ++a.expected;++b.expected;++c.expected;
        if(ekf.health()==Health::Degraded)++a.degraded_samples;
        if(ekf.health()==Health::Fault)++a.faulted_samples;
        if(ekf.control_state_valid()) {
            const float tilt=tilt_error(ekf.state().orientation,truth);
            const float yaw=wrap_pi(ekf.state().orientation.yaw()-truth.yaw())*kRadToDeg;
            if(std::isfinite(tilt)&&std::isfinite(yaw)) {
                a.add(tilt,yaw);
                update_nees(ekf,truth,a);
                if(std::isfinite(ekf.last_nis()) && ekf.gravity_applied_updates()>a.accepted_gravity) {
                    a.nis_sum+=ekf.last_nis();++a.nis_count;
                }
            } else {
                a.invalid(true);
            }
            a.accepted_gravity=ekf.gravity_applied_updates();
            a.suppressed=ekf.gravity_suppressed_updates();
            a.last_gyro_bias_error=(ekf.state().gyro_bias-sensor.true_gyro_bias_rps).norm();
        } else a.invalid(ekf.health()!=Health::Aligning);
        if(legacy.health()==Health::Degraded)++c.degraded_samples;
        if(legacy.health()==Health::Fault)++c.faulted_samples;
        if(legacy.control_state_valid()){
            const float tilt=tilt_error(legacy.state().orientation,truth);
            const float yaw=wrap_pi(legacy.state().orientation.yaw()-truth.yaw())*kRadToDeg;
            if(std::isfinite(tilt)&&std::isfinite(yaw))c.add(tilt,yaw);
            else c.invalid(true);
            c.last_gyro_bias_error=(legacy.state().gyro_bias-sensor.true_gyro_bias_rps).norm();
            c.accepted_gravity=legacy.gravity_applied_updates();
        } else c.invalid(legacy.health()!=Health::Aligning);
        if(mahony.ready) {
            const float tilt=tilt_error(mahony.q,truth);
            const float yaw=wrap_pi(mahony.q.yaw()-truth.yaw())*kRadToDeg;
            if(std::isfinite(tilt)&&std::isfinite(yaw))b.add(tilt,yaw);
            else b.invalid(true);
            b.last_gyro_bias_error=(mahony.bias-sensor.true_gyro_bias_rps).norm();
        } else if(b.valid_mask.size()<b.expected)b.invalid(false);
    }
    b.stream_hash=c.stream_hash=a.stream_hash;
    a.noise_draw_hash=b.noise_draw_hash=c.noise_draw_hash=noise_draw_hash;
    a.accel_clip_samples=b.accel_clip_samples=c.accel_clip_samples=accel_clip_samples;
    a.gyro_clip_samples=b.gyro_clip_samples=c.gyro_clip_samples=gyro_clip_samples;
    return {a,b,c};
}

#ifndef BUNDLE_B_NO_MAIN
std::string json_escape(const std::string& value) {
    std::string out;
    for(unsigned char ch:value) {
        if(ch=='"'||ch=='\\'){out.push_back('\\');out.push_back(static_cast<char>(ch));}
        else if(ch=='\n')out+="\\n";
        else if(ch=='\r')out+="\\r";
        else if(ch=='\t')out+="\\t";
        else if(ch>=0x20)out.push_back(static_cast<char>(ch));
    }
    return out;
}
#endif
void write_json_vec3(std::ostream& out,Vec3 value) {
    out<<'['<<std::fixed<<std::setprecision(6)<<value.x<<','<<value.y<<','<<value.z<<']';
}
void write_json_matrix(std::ostream& out,const AxisTransform& axes) {
    out<<'[';
    const float rows[3][3]={{axes.sx,axes.xy,axes.xz},
                            {axes.yx,axes.sy,axes.yz},
                            {axes.zx,axes.zy,axes.sz}};
    for(int row=0;row<3;row++) {
        if(row)out<<',';
        out<<'[';
        for(int col=0;col<3;col++){if(col)out<<',';out<<std::fixed<<std::setprecision(6)<<rows[row][col];}
        out<<']';
    }
    out<<']';
}
void append_sensor_model_config(std::ostringstream& config,const SensorModel& model) {
    config<<std::hexfloat
        <<model.accel_density<<','<<model.gyro_density<<','<<model.accel_walk<<','<<model.gyro_walk<<','
        <<model.accel_axes.sx<<','<<model.accel_axes.sy<<','<<model.accel_axes.sz<<','
        <<model.accel_axes.xy<<','<<model.accel_axes.xz<<','<<model.accel_axes.yx<<','
        <<model.accel_axes.yz<<','<<model.accel_axes.zx<<','<<model.accel_axes.zy<<','
        <<model.gyro_axes.sx<<','<<model.gyro_axes.sy<<','<<model.gyro_axes.sz<<','
        <<model.gyro_axes.xy<<','<<model.gyro_axes.xz<<','<<model.gyro_axes.yx<<','
        <<model.gyro_axes.yz<<','<<model.gyro_axes.zx<<','<<model.gyro_axes.zy<<','
        <<model.accel_temp_bias_per_c.x<<','<<model.accel_temp_bias_per_c.y<<','<<model.accel_temp_bias_per_c.z<<','
        <<model.gyro_temp_bias_per_c.x<<','<<model.gyro_temp_bias_per_c.y<<','<<model.gyro_temp_bias_per_c.z<<','
        <<model.temperature_rise_c<<','<<model.temperature_ramp_start_s<<','<<model.temperature_ramp_duration_s<<','
        <<model.accel_clip_limit_mps2<<','<<model.gyro_clip_limit_rps<<','
        <<model.accel_quantum_mps2<<','<<model.gyro_quantum_rps;
}
uint64_t sensor_model_hash(const SensorModel& model) {
    std::ostringstream config;
    append_sensor_model_config(config,model);
    uint64_t hash=14695981039346656037ull;
    const std::string canonical=config.str();
    hash_bytes(hash,canonical.data(),canonical.size());
    return hash;
}
uint64_t configuration_hash(const std::vector<SensorProfile>& profiles) {
    std::ostringstream config;
    config<<"schema="<<kSchemaVersion<<";metric="<<kMetricDefinitionVersion
          <<";truth="<<kTruthIntegrationVersion<<";seed_schedule="<<kSeedScheduleVersion
          <<";rate_hz="<<kSampleRateHz<<";duration_s="<<kDurationSeconds
          <<";accel_noise="<<std::hexfloat<<kAccelNoiseDensityMps2PerSqrtHz
          <<";gyro_noise="<<kGyroNoiseDensityRpsPerSqrtHz
          <<";accel_walk="<<kAccelBiasWalkMps2PerSqrtSecond
          <<";gyro_walk="<<kGyroBiasWalkRpsPerSqrtSecond
          <<";initial_accel_bias="<<kInitialAccelBiasMps2.x<<','<<kInitialAccelBiasMps2.y<<','<<kInitialAccelBiasMps2.z
          <<";initial_gyro_bias="<<kInitialGyroBiasRps.x<<','<<kInitialGyroBiasRps.y<<','<<kInitialGyroBiasRps.z
          <<";scenarios=";
    for(const char* scene:kScenarioNames)config<<scene<<',';
    config<<";selected_profiles=";
    for(const auto profile:profiles)config<<sensor_profile_name(profile)<<',';
    for(const auto profile:{SensorProfile::Nominal,SensorProfile::Stress}) {
        config<<";profile="<<sensor_profile_name(profile)<<';';
        append_sensor_model_config(config,sensor_model(profile));
    }
    uint64_t hash=14695981039346656037ull;
    const std::string canonical=config.str();
    hash_bytes(hash,canonical.data(),canonical.size());
    return hash;
}
#ifndef BUNDLE_B_NO_MAIN
bool write_metadata(const std::string& path,unsigned trials,unsigned base_seed,bool startup_bias,
                    const std::vector<SensorProfile>& profiles) {
    std::ofstream out(path);
    if(!out)return false;
    const char* git_sha=std::getenv("BUNDLE_B_GIT_SHA");
    if(!git_sha||!*git_sha)git_sha="unavailable";
    const char* worktree_state=std::getenv("BUNDLE_B_GIT_WORKTREE");
    if(!worktree_state||!*worktree_state)worktree_state="unavailable";
    const SensorModel stress=sensor_model(SensorProfile::Stress);
    const SensorModel baseline=sensor_model(SensorProfile::Nominal);
    out<<"{\n  \"schema_version\": "<<kSchemaVersion<<",\n  \"metric_definition_version\": "<<kMetricDefinitionVersion<<",\n"
       <<"  \"truth_integration_version\": "<<kTruthIntegrationVersion<<",\n"
       <<"  \"seed_schedule_version\": "<<kSeedScheduleVersion<<",\n  \"scenario_set\": [";
    for(size_t i=0;i<std::size(kScenarioNames);++i){if(i)out<<", ";out<<'"'<<kScenarioNames[i]<<'"';}
    out<<"],\n  \"duration_seconds\": "<<kDurationSeconds<<",\n  \"sample_rate_hz\": "<<kSampleRateHz<<",\n"
       <<"  \"base_seed\": "<<base_seed<<",\n  \"trials\": "<<trials<<",\n  \"startup_bias\": "<<(startup_bias?"true":"false")<<",\n  \"sensor_profiles\": [";
    for(size_t i=0;i<profiles.size();++i){if(i)out<<", ";out<<'"'<<sensor_profile_name(profiles[i])<<'"';}
    out<<"],\n  \"compiler\": \""<<json_escape(__VERSION__)<<"\",\n"
       <<"  \"standard_library_version\": \""<<json_escape(kStandardLibraryVersion)<<"\",\n"
       <<"  \"git_sha\": \""<<json_escape(git_sha)<<"\",\n"
       <<"  \"git_worktree_state\": \""<<json_escape(worktree_state)<<"\",\n"
       <<"  \"seed_schedule\": \"base_seed + 1009*trial_id + 103*scenario_name_length; version 1 preserves legacy offsets\",\n"
       <<"  \"configuration_hash_fnv1a64\": \""<<std::hex<<std::setw(16)<<std::setfill('0')
       <<configuration_hash(profiles)<<std::dec<<"\",\n"
       <<"  \"sensor_model_parameters\": {\n    \"accel_matrix\": ";
    write_json_matrix(out,stress.accel_axes);
    out<<",\n    \"gyro_matrix\": ";
    write_json_matrix(out,stress.gyro_axes);
    out<<",\n    \"temperature_ramp\": {\"rise_c\": "<<stress.temperature_rise_c
       <<", \"duration_s\": "<<stress.temperature_ramp_duration_s<<", \"start_s\": "<<stress.temperature_ramp_start_s<<"},\n"
       <<"    \"accel_temperature_bias_mps2_per_c\": ";
    write_json_vec3(out,stress.accel_temp_bias_per_c);
    out<<",\n    \"gyro_temperature_bias_rps_per_c\": ";
    write_json_vec3(out,stress.gyro_temp_bias_per_c);
    out<<",\n    \"accel_clip_limit_mps2\": "<<stress.accel_clip_limit_mps2
       <<", \"gyro_clip_limit_rps\": "<<stress.gyro_clip_limit_rps<<",\n"
       <<"    \"accel_quantum_mps2\": "<<stress.accel_quantum_mps2<<", \"gyro_quantum_rps\": "<<stress.gyro_quantum_rps<<",\n"
       <<"    \"accel_white_noise_density_mps2_per_sqrt_hz\": "<<baseline.accel_density<<",\n"
       <<"    \"gyro_white_noise_density_rps_per_sqrt_hz\": "<<baseline.gyro_density<<",\n"
       <<"    \"accel_bias_walk_mps2_per_sqrt_s\": "<<baseline.accel_walk<<",\n"
       <<"    \"gyro_bias_walk_rps_per_sqrt_s\": "<<baseline.gyro_walk<<",\n"
       <<"    \"initial_accel_bias_mps2\": ";
    write_json_vec3(out,kInitialAccelBiasMps2);
    out<<",\n    \"initial_gyro_bias_rps\": ";
    write_json_vec3(out,kInitialGyroBiasRps);
    out<<",\n    \"synthetic_assumption\": true\n  }\n}\n";
    return static_cast<bool>(out);
}
int main(int argc,char**argv) {
    unsigned trials=5,seed=20261110;
    bool startup_bias=false;
    std::string output="bundle_b_results.csv";
    std::string metadata;
    std::string profile_option="both";
    const auto usage=[](){std::fputs("Usage: benchmark_bundle_b [--trials N] [--seed N] [--output file.csv] [--metadata file.json] [--sensor-profile nominal|stress|both] [--startup-bias]\n",stderr);};
    for(int i=1;i<argc;i++) {
        const std::string a=argv[i];
        if(a=="--trials" && i+1<argc){if(!parse_unsigned_arg(argv[++i],trials)){std::fputs("invalid --trials value\n",stderr);usage();return 2;}}
        else if(a=="--seed" && i+1<argc){if(!parse_unsigned_arg(argv[++i],seed)){std::fputs("invalid --seed value\n",stderr);usage();return 2;}}
        else if(a=="--output" && i+1<argc)output=argv[++i];
        else if(a=="--metadata" && i+1<argc)metadata=argv[++i];
        else if(a=="--sensor-profile" && i+1<argc)profile_option=argv[++i];
        else if(a=="--startup-bias")startup_bias=true;
        else {usage();return 2;}
    }
    std::vector<SensorProfile> profiles;
    if(profile_option=="nominal")profiles.push_back(SensorProfile::Nominal);
    else if(profile_option=="stress")profiles.push_back(SensorProfile::Stress);
    else if(profile_option=="both")profiles={SensorProfile::Nominal,SensorProfile::Stress};
    else {std::fprintf(stderr,"Unknown sensor profile: %s\n",profile_option.c_str());usage();return 2;}
    if(!trials || trials>200){std::fputs("trials must be between 1 and 200\n",stderr);usage();return 2;}
    if(!seed_schedule_fits(seed,trials)){std::fputs("seed schedule overflows unsigned range\n",stderr);usage();return 2;}
    if(metadata.empty())metadata=output+".metadata.json";
    std::ofstream out(output);
    if(!out){std::fprintf(stderr,"Cannot create %s\n",output.c_str());return 2;}
    out<<"schema_version,metric_definition_version,scenario,trial_id,sensor_profile,model,seed,startup_bias,expected,valid,invalid,valid_fraction,valid_mask,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,yaw_rms_deg,tilt_nees_mean,tilt_nees_coverage95,tilt_nees_count,gravity_nis_mean,gravity_nis_count,gyro_bias_error_rps,gravity_applied,gravity_suppressed,uninitialized_samples,invalid_samples,degraded_samples,faulted_samples,accel_clip_samples,gyro_clip_samples,imu_stream_hash_fnv1a64,noise_draw_hash_fnv1a64\n";
    out<<std::fixed<<std::setprecision(8);
    for(const char* scene:kScenarioNames) {
        for(const SensorProfile profile:profiles) {
            for(unsigned trial=0;trial<trials;trial++) {
                const unsigned trial_seed=static_cast<unsigned>(seed_for_trial(seed,trial,scene));
                Comparison results=simulate(scene,trial,trial_seed,startup_bias,profile);
                for(Metrics* m:{&results.ekf,&results.mahony,&results.legacy}){
                    const double valid_fraction=m->expected?static_cast<double>(m->valid)/m->expected:NAN;
                    out<<kSchemaVersion<<","<<kMetricDefinitionVersion<<","<<m->scenario<<","<<m->trial_id<<","<<m->sensor_profile<<","<<m->model<<","<<m->seed<<","<<startup_bias<<","<<m->expected<<","<<m->valid<<","<<(m->expected-m->valid)<<","<<valid_fraction<<","<<m->valid_mask<<","<<m->tilt_rms()<<","<<m->p95()<<","<<m->max_tilt<<","<<m->yaw_rms();
                    out<<",";if(m->nees_count)out<<m->nees_sum/m->nees_count;
                    out<<",";if(m->nees_count)out<<static_cast<double>(m->nees95)/m->nees_count;
                    out<<","<<m->nees_count;
                    out<<",";if(m->nis_count)out<<m->nis_sum/m->nis_count;
                    out<<","<<m->nis_count;
                    out<<",";if(std::isfinite(m->last_gyro_bias_error))out<<m->last_gyro_bias_error;
                    out<<","<<m->accepted_gravity<<","<<m->suppressed<<","<<m->uninitialized_samples<<","<<m->invalid_samples<<","<<m->degraded_samples<<","<<m->faulted_samples<<","<<m->accel_clip_samples<<","<<m->gyro_clip_samples<<","<<std::hex<<std::setw(16)<<std::setfill('0')<<m->stream_hash<<","<<std::setw(16)<<m->noise_draw_hash<<std::dec<<"\n";
                }
            }
        }
    }
    out.close();
    if(!out){std::fprintf(stderr,"Failed writing %s\n",output.c_str());return 2;}
    if(!write_metadata(metadata,trials,seed,startup_bias,profiles)){
        std::fprintf(stderr,"Cannot write metadata %s\n",metadata.c_str());return 2;
    }
    std::printf("Wrote %s: %u trials per scenario, 8 scenarios, 3 estimator variants, sensor profile %s; startup bias %s\n",
        output.c_str(),trials,profile_option.c_str(),startup_bias?"enabled":"disabled");
    return 0;
}
#endif
