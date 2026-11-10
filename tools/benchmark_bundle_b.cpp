// Deterministic, host-only sensor fusion comparison using a single physical IMU
// stream for each estimator. NOT measured hardware, nor flight certification.
#include "../eskf15.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numeric>
#include <random>
#include <string>
#include <vector>

using namespace inertial;
constexpr float kRadToDeg = 180.0f/kPi;
constexpr float kHz=200.0f;
constexpr float kDt=1.0f/kHz;

// True uncorrelated sensor noise densities, measured with respect to sqrt(Hz).
// Values are illustrative, not calibrated LSM6DS3 characteristics.
struct SensorModel {
    float accel_density=.0015f;     // m/s^2/sqrt(Hz)
    float gyro_density=.00025f;     // rad/s/sqrt(Hz)
    float accel_walk=.00008f;       // m/s^2/sqrt(s)
    float gyro_walk=.00003f;        // rad/s/sqrt(s)
};

struct Motion {Vec3 rate, acceleration;};
Motion motion(const std::string& scenario, float t) {
    if(t < 2.0f) return {};
    const float u=t-2.0f;
    if(scenario=="static") return {};
    if(scenario=="slow_yaw") return {{0,0,.035f},{}};
    if(scenario=="lateral_accel")
        return {{},(u<10.0f)?Vec3{.17f*kGravity,0,0}:Vec3{}};
    if(scenario=="maneuver" || scenario=="timing_jitter")
        return {{.35f*std::sin(1.3f*u),.27f*std::cos(.7f*u),.35f+.12f*std::sin(.8f*u)},
                {0.75f*std::sin(1.2f*u),0.65f*std::cos(.9f*u),.25f*std::sin(1.8f*u)}};
    if(scenario=="vibration")
        return {{.20f*std::sin(.8f*u),.15f*std::sin(1.1f*u),.25f},
                {0.20f*std::sin(.5f*u),0.3f*std::cos(1.1f*u),0}};
    std::fprintf(stderr,"Unknown scenario: %s\n",scenario.c_str()); std::exit(2);
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
    std::string scenario,model;
    unsigned seed=0;
    unsigned expected=0,valid=0,initialized=0;
    double sum_tilt_sq=0,sum_yaw_sq=0,nees_sum=0,nis_sum=0;
    unsigned nees_count=0,nees95=0,nis_count=0;
    float max_tilt=0;
    std::vector<float> tilt_errors;
    float last_gyro_bias_error=std::numeric_limits<float>::quiet_NaN();
    unsigned suppressed=0,accepted_gravity=0;
    double tilt_rms()const{return valid?std::sqrt(sum_tilt_sq/valid):NAN;}
    double yaw_rms()const{return valid?std::sqrt(sum_yaw_sq/valid):NAN;}
    double p95() {if(tilt_errors.empty())return NAN;std::sort(tilt_errors.begin(),tilt_errors.end());return tilt_errors[static_cast<size_t>(.95*(tilt_errors.size()-1))];}
    void add(float tilt_deg,float yaw_deg){++valid;sum_tilt_sq+=tilt_deg*tilt_deg;sum_yaw_sq+=yaw_deg*yaw_deg;
        max_tilt=std::max(max_tilt,tilt_deg);tilt_errors.push_back(tilt_deg);}
};

float tilt_error(Quat est,Quat truth){
    const Vec3 z=est.rotate({0,0,1}), ztruth=truth.rotate({0,0,1});
    return std::acos(std::max(-1.0f,std::min(1.0f,dot(z,ztruth))))*kRadToDeg;
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
Comparison simulate(const std::string& scene,unsigned seed,bool startup_bias) {
    SensorModel model;
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
    a.model="eskf_conservative";b.model="mahony";c.model="eskf_legacy";
    a.seed=b.seed=c.seed=seed;
    std::mt19937 rng(seed);
    std::normal_distribution<float> standard(0.0f,1.0f);
    const auto gaussian=[&rng,&standard](){return standard(rng);};
    const float acc_sigma=model.accel_density*std::sqrt(kHz);
    const float gyr_sigma=model.gyro_density*std::sqrt(kHz);
    const float acc_step=model.accel_walk*std::sqrt(kDt);
    const float gyr_step=model.gyro_walk*std::sqrt(kDt);
    Quat truth{};
    Vec3 accel_bias{.018f,-.012f,.024f},gyro_bias{.008f,-.006f,.018f};
    for(unsigned i=1;i<=3200;i++) { // 16 seconds at 200 Hz
        const float t=i*kDt;
        const Motion m=motion(scene,t);
        truth=truth*Quat::exp(m.rate*kDt);truth.normalize();
        accel_bias=accel_bias+Vec3{gaussian()*acc_step,gaussian()*acc_step,gaussian()*acc_step};
        gyro_bias=gyro_bias+Vec3{gaussian()*gyr_step,gaussian()*gyr_step,gaussian()*gyr_step};
        const Vec3 proper=truth.unrotate(m.acceleration+Vec3{0,0,kGravity});
        Vec3 accel=proper+accel_bias+
            Vec3{gaussian()*acc_sigma,gaussian()*acc_sigma,gaussian()*acc_sigma};
        Vec3 gyro=m.rate+gyro_bias+
            Vec3{gaussian()*gyr_sigma,gaussian()*gyr_sigma,gaussian()*gyr_sigma};
        if(scene=="vibration" && t>2.0f){
            // Deterministic, correlated high-frequency disturbance only.
            const float v=.40f*std::sin(2*kPi*43.0f*t);
            accel=accel+Vec3{v,-.3f*v,.2f*v};
            gyro=gyro+Vec3{.012f*std::sin(2*kPi*31.0f*t),0,0};
        }
        // Only in timing_jitter: timestamps drift by up to +/-150 us around
        // the real 5 ms acquisition instants. This models measurement-time
        // metadata error, NOT a proven RP2350 interrupt-jitter distribution.
        const int64_t timestamp_jitter=(scene=="timing_jitter") ?
            static_cast<int64_t>(std::lround(150.0*std::sin(2.0*kPi*2.3*t))) : 0;
        const Imu sample{static_cast<uint64_t>(1000000ull+static_cast<uint64_t>(i)*5000ull+
            timestamp_jitter),accel,gyro};
        ekf.set_external_stationary_confirmed(t<=2.0f);
        legacy.set_external_stationary_confirmed(t<=2.0f);
        ekf.process(sample);legacy.process(sample);mahony.process(sample,t<=2.0f);
        if(t<2.0f)continue;
        ++a.expected;++b.expected;++c.expected;
        if(ekf.control_state_valid()) {
            a.add(tilt_error(ekf.state().orientation,truth),wrap_pi(ekf.state().orientation.yaw()-truth.yaw())*kRadToDeg);
            update_nees(ekf,truth,a);
            if(std::isfinite(ekf.last_nis()) && ekf.gravity_applied_updates()>a.accepted_gravity) {
                a.nis_sum+=ekf.last_nis();++a.nis_count;
            }
            a.accepted_gravity=ekf.gravity_applied_updates();
            a.suppressed=ekf.gravity_suppressed_updates();
            a.last_gyro_bias_error=(ekf.state().gyro_bias-gyro_bias).norm();
        }
        if(legacy.control_state_valid()){
            c.add(tilt_error(legacy.state().orientation,truth),wrap_pi(legacy.state().orientation.yaw()-truth.yaw())*kRadToDeg);
            c.accepted_gravity=legacy.gravity_applied_updates();
        }
        if(mahony.ready)b.add(tilt_error(mahony.q,truth),wrap_pi(mahony.q.yaw()-truth.yaw())*kRadToDeg);
    }
    return {a,b,c};
}

int main(int argc,char**argv) {
    unsigned trials=5,seed=20261110;
    bool startup_bias=false;
    std::string output="bundle_b_results.csv";
    for(int i=1;i<argc;i++) {
        const std::string a=argv[i];
        if(a=="--trials" && i+1<argc)trials=static_cast<unsigned>(std::strtoul(argv[++i],nullptr,10));
        else if(a=="--seed" && i+1<argc)seed=static_cast<unsigned>(std::strtoul(argv[++i],nullptr,10));
        else if(a=="--output" && i+1<argc)output=argv[++i];
        else if(a=="--startup-bias")startup_bias=true;
        else {std::fprintf(stderr,"Usage: benchmark_bundle_b [--trials N] [--seed N] [--output file.csv] [--startup-bias]\n");return 2;}
    }
    if(!trials || trials>200){std::fputs("trials must be between 1 and 200\n",stderr);return 2;}
    std::ofstream out(output);
    if(!out){std::fprintf(stderr,"Cannot create %s\n",output.c_str());return 2;}
    out<<"scenario,model,seed,startup_bias,expected,valid,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,yaw_rms_deg,tilt_nees_mean,tilt_nees_coverage95,gravity_nis_mean,gyro_bias_error_rps,gravity_applied,gravity_suppressed\n";
    out<<std::fixed<<std::setprecision(8);
    for(const char* scene:{"static","slow_yaw","lateral_accel","maneuver","vibration","timing_jitter"}) {
        for(unsigned trial=0;trial<trials;trial++) {
            Comparison results=simulate(scene,seed+1009*trial+103*static_cast<unsigned>(std::string(scene).size()),startup_bias);
            for(Metrics* m:{&results.ekf,&results.mahony,&results.legacy}){
                out<<m->scenario<<","<<m->model<<","<<m->seed<<","<<startup_bias<<","<<m->expected<<","<<m->valid<<","<<m->tilt_rms()<<","<<m->p95()<<","<<m->max_tilt<<","<<m->yaw_rms()<<",";
                if(m->nees_count)out<<m->nees_sum/m->nees_count<<","<<static_cast<double>(m->nees95)/m->nees_count;
                out<<",";
                if(m->nis_count)out<<m->nis_sum/m->nis_count;
                out<<",";
                if(std::isfinite(m->last_gyro_bias_error))out<<m->last_gyro_bias_error;
                out<<","<<m->accepted_gravity<<","<<m->suppressed<<"\n";
            }
        }
    }
    std::printf("Wrote %s: %u trials per scenario, 6 scenarios, 3 estimator variants; startup bias %s\n",
        output.c_str(),trials,startup_bias?"enabled":"disabled");
}
