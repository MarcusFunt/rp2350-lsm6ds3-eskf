#pragma once

// Portable, no-heap 15-state inertial error-state Kalman filter (ESKF).
// Nominal state: world position p, world velocity v, world-from-body quaternion q,
// body-frame accelerometer bias ba and gyro bias bg.
// Error state (right-multiplicative attitude): [dp, dv, dtheta, dba, dbg].
// Frames: world Z up; gravity=(0,0,-9.80665) m/s^2; an upright stationary
// accelerometer reports approximately (0,0,+9.80665) m/s^2.
// Inputs: sensor specific force [m/s^2] and angular velocity [rad/s].
// This is an inertial estimator, NOT observable position/yaw with a 6-axis IMU.
// It provides external position, velocity and heading update APIs for aiding.

#include <cmath>
#include <cstdint>

namespace inertial {

constexpr float kGravity = 9.80665f;
constexpr float kPi = 3.14159265358979323846f;
constexpr int kDim = 15;

struct Vec3 {
    float x = 0, y = 0, z = 0;
    Vec3 operator+(Vec3 b) const { return {x+b.x,y+b.y,z+b.z}; }
    Vec3 operator-(Vec3 b) const { return {x-b.x,y-b.y,z-b.z}; }
    Vec3 operator*(float s) const { return {x*s,y*s,z*s}; }
    float norm() const { return std::sqrt(x*x+y*y+z*z); }
};
inline float dot(Vec3 a, Vec3 b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
inline Vec3 cross(Vec3 a, Vec3 b) {
    return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x};
}

struct Quat { // w,x,y,z; rotates body vectors into world frame
    float w=1, x=0, y=0, z=0;
    Quat operator*(Quat b) const {
        return {w*b.w-x*b.x-y*b.y-z*b.z,
                w*b.x+x*b.w+y*b.z-z*b.y,
                w*b.y-x*b.z+y*b.w+z*b.x,
                w*b.z+x*b.y-y*b.x+z*b.w};
    }
    void normalize() {
        const float n = std::sqrt(w*w+x*x+y*y+z*z);
        if (n > 1e-12f && std::isfinite(n)) { w/=n; x/=n; y/=n; z/=n; }
        else { w=1; x=y=z=0; }
    }
    static Quat exp(Vec3 angle) { // rotation vector in radians
        const float r=angle.norm();
        if (r < 1e-6f) return {1,angle.x*.5f,angle.y*.5f,angle.z*.5f};
        const float s=std::sin(.5f*r)/r;
        return {std::cos(.5f*r),angle.x*s,angle.y*s,angle.z*s};
    }
    static Quat from_to(Vec3 from, Vec3 to) {
        const float n=from.norm()*to.norm();
        if (!(n > 1e-9f)) return {};
        from=from*(1.0f/from.norm()); to=to*(1.0f/to.norm());
        const float d=dot(from,to);
        if (d < -0.9999f) {
            Vec3 axis=(std::fabs(from.x)<.9f) ? cross(from,{1,0,0}) : cross(from,{0,1,0});
            axis=axis*(1.0f/axis.norm());
            return {0,axis.x,axis.y,axis.z};
        }
        Vec3 c=cross(from,to);
        Quat q{1.0f+d,c.x,c.y,c.z}; q.normalize(); return q;
    }
    Vec3 rotate(Vec3 b) const {
        const Vec3 qv{x,y,z};
        const Vec3 t=cross(qv,b)*2.0f;
        return b+t*w+cross(qv,t);
    }
    Vec3 unrotate(Vec3 world) const { return Quat{w,-x,-y,-z}.rotate(world); }
    float yaw() const {
        return std::atan2(2.0f*(w*z+x*y),1.0f-2.0f*(y*y+z*z));
    }
};
inline float wrap_pi(float r) {
    while (r > kPi) r-=2*kPi;
    while (r < -kPi) r+=2*kPi;
    return r;
}

struct Imu {
    uint64_t timestamp_us=0;
    Vec3 accel_mps2{};
    Vec3 gyro_rps{};
};

// Gravity direction is only a valid absolute tilt observation when linear
// acceleration is negligible. The default conservative heuristic explicitly
// limits its influence; a constant small acceleration remains unobservable.
enum class GravityPolicy : uint8_t {
    Conservative=0,       // automatic, strongly gated and adaptively downweighted
    LegacyHeuristic=1,    // Bundle-A comparison baseline: norm/gyro/step tests
    ConfirmedOnly=2      // updates ONLY when independently asserted stationary
};

struct Settings {
    // White-noise densities (per sqrt(Hz)); initial engineering tuning values,
    // NOT certified LSM6DS3 noise specs. Calibrate from your own stationary logs.
    float accel_noise=0.12f;         // m/s^2 / sqrt(Hz)
    float gyro_noise=0.008f;         // rad/s / sqrt(Hz)
    float accel_bias_walk=0.002f;    // m/s^2 / sqrt(s)
    float gyro_bias_walk=0.0002f;    // rad/s / sqrt(s)
    float gravity_update_sigma=0.05f; // unit-vector direction noise (dimensionless)
    float zero_rate_sigma=0.025f;     // rad/s at ~10 Hz
    float static_accel_tolerance=0.06f; // fraction of gravity
    float static_gyro_limit=0.12f;     // rad/s raw gyro threshold
    float static_accel_step_limit=0.20f; // m/s^2 between adjacent samples
    unsigned static_min_samples=35;    // ~170 ms at 208 Hz
    unsigned aid_every_samples=21;     // ~10 Hz at 208 Hz
    GravityPolicy gravity_policy=GravityPolicy::Conservative;
    float gravity_unverified_max_angle_rad=0.08f; // ~4.6 deg, not motion detection
    float gravity_motion_noise_multiplier=4.0f; // soft downweight near heuristic limits
    bool startup_gyro_bias_calibration=false; // require externally VERIFIED static startup
    float startup_gyro_stddev_limit=0.020f;   // reject noisy/transient startup window
    float startup_bias_sigma_floor=0.015f;    // floor on std dev after initialization
    bool heuristic_zero_rate=false;    // unsafe during very slow rotation; opt in
    unsigned init_min_samples=80;     // require stable ~0.38s before alignment at 208Hz
    float init_gyro_limit=0.12f;      // only a provisional quasi-static test
    float init_accel_step_limit=0.20f;
    uint32_t expected_period_us=4808; // 208Hz; used for missing-sample detection
    float period_gap_ratio=1.70f;
    float max_accel_axis_mps2=0.98f*4.0f*kGravity; // actual +/-4g setting
    float max_gyro_axis_rps=0.98f*245.0f*(kPi/180.0f);
    float gap_unmodeled_accel_mps2=3.0f; // outage covariance inflation bounds, tune
    float gap_unmodeled_rate_rps=1.0f;
    float max_continuous_predict_dt_s=0.025f; // a longer gap must explicitly reset
    uint64_t max_aiding_age_us=1000; // no delayed-state replay yet; reject stale aids
    uint32_t calibration_id=0;      // zero disables version check; set after calibration

};

// Operational status only: alignment, continuity and numeric/input faults.
// Nominal does not certify attitude accuracy, observability or control safety.
enum class Health : uint8_t { Aligning=0, Nominal=1, Degraded=2, Fault=3 };

struct AidingStamp {
    uint64_t timestamp_us=0;  // must match propagated state to within max_aiding_age_us
    uint32_t source_id=0;     // external sensor identifier, for caller-side ownership audit
    uint32_t calibration_id=0;
};

struct State {
    Vec3 position{}, velocity{};
    Quat orientation{};
    Vec3 accel_bias{}, gyro_bias{};
};

class Eskf15 {
public:
    explicit Eskf15(Settings settings={}) : config_(settings) { reset(); }

    void reset() {
        state_={};
        initialized_=false;
        reset_required_=false;
        last_time_us_=0;
        state_time_us_=0;
        static_count_=0;
        aid_count_=0;
        stationary_=false;
        have_previous_accel_=false;
        rejected_updates_=0;
        accepted_updates_=0;
        stale_aiding_updates_=0;
        gap_count_=0;
        saturation_count_=0;
        invalid_imu_count_=0;
        init_count_=0;
        init_verified_count_=0;
        init_accel_sum_={};
        init_gyro_sum_={};
        init_gyro_sq_sum_={};
        startup_bias_calibrated_=false;
        external_stationary_confirmed_=false;
        gravity_suppressed_updates_=0;
        gravity_applied_updates_=0;
        external_stationary_conflicts_=0;
        init_last_accel_={};
        health_=Health::Aligning;
        last_nis_=NAN;
        last_nis_gate_=NAN;
        last_accepted_aid_source_=0;
        last_accepted_aid_time_us_=0;
        samples_propagated_=0;
        for (int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) P_[i][j]=0;
        for (int i=0;i<3;i++) {
            P_[i][i]=4.0f;           // position: 2 m standard deviation
            P_[3+i][3+i]=1.0f;       // velocity: 1 m/s
            P_[6+i][6+i]=0.15f*0.15f;
            P_[9+i][9+i]=0.3f*0.3f;
            P_[12+i][12+i]=0.06f*0.06f;
        }
        P_[8][8]=kPi*kPi; // yaw has no 6-axis absolute reference
    }

    // True ONLY when a valid propagation occurred. False during initialization,
    // duplicate timestamps, long gaps, saturation, or invalid data.
    bool process(const Imu &imu) {
        if (!finite(imu.accel_mps2) || !finite(imu.gyro_rps)) {
            ++invalid_imu_count_;
            health_=Health::Fault;
            reset_required_=initialized_;
            return false;
        }
        // Once motion has been unobserved for too long, carrying a stale state
        // forward as though it were current would be misleading. Explicit
        // reset/reinitialization is required; no automatic pose teleportation.
        if (reset_required_) {
            if (imu.timestamp_us>last_time_us_) last_time_us_=imu.timestamp_us;
            return false;
        }
        if (saturated(imu)) {
            ++saturation_count_;
            health_=Health::Fault;
            reset_required_=initialized_; // a clipped sample breaks continuity
            // Crucially do not interpret clipped measurements as real motion.
            if (initialized_ && imu.timestamp_us > last_time_us_) {
                const float dt=(imu.timestamp_us-last_time_us_)*1e-6f;
                inflate_gap(dt);
                last_time_us_=imu.timestamp_us;
            }
            init_count_=0;
            return false;
        }
        if (!initialized_) {
            // Require multiple stable samples. This cannot prove lack of a
            // constant acceleration: caller must still verify at-rest startup.
            if (last_time_us_ && imu.timestamp_us<=last_time_us_) return false;
            const bool time_valid = !last_time_us_ ||
                (imu.timestamp_us-last_time_us_ <=
                    static_cast<uint64_t>(config_.expected_period_us*config_.period_gap_ratio));
            const float norm=imu.accel_mps2.norm();
            const bool stable = time_valid &&
                std::fabs(norm-kGravity)<config_.static_accel_tolerance*kGravity &&
                imu.gyro_rps.norm()<config_.init_gyro_limit &&
                (!init_count_ || (imu.accel_mps2-init_last_accel_).norm()<config_.init_accel_step_limit);
            last_time_us_=imu.timestamp_us;
            init_last_accel_=imu.accel_mps2;
            if (!stable) {
                init_count_=0; init_verified_count_=0; init_accel_sum_={};
                init_gyro_sum_={}; init_gyro_sq_sum_={};
                return false;
            }
            if (external_stationary_confirmed_)++init_verified_count_;
            init_accel_sum_=init_accel_sum_+imu.accel_mps2;
            init_gyro_sum_=init_gyro_sum_+imu.gyro_rps;
            init_gyro_sq_sum_=init_gyro_sq_sum_ + Vec3{
                imu.gyro_rps.x*imu.gyro_rps.x,
                imu.gyro_rps.y*imu.gyro_rps.y,
                imu.gyro_rps.z*imu.gyro_rps.z};
            if (++init_count_ < config_.init_min_samples) return false;
            const Vec3 avg=init_accel_sum_*(1.0f/init_count_);
            state_.orientation=Quat::from_to(avg,{0,0,kGravity});
            // The global-yaw gauge axis is world Z expressed in body-error
            // coordinates. It is NOT generally body Z when starting tilted.
            const Vec3 gauge=state_.orientation.unrotate({0,0,1});
            const float u[3]={gauge.x,gauge.y,gauge.z};
            const float tilt_var=0.15f*0.15f;
            const float yaw_var=kPi*kPi;
            for(int i=0;i<3;i++) for(int j=0;j<3;j++)
                P_[6+i][6+j]=(i==j?tilt_var:0.0f)
                    +(yaw_var-tilt_var)*u[i]*u[j];
            // Bias initialization is OPT-IN: zero motion cannot be proven by
            // gyro and acceleration readings on their own. The caller must
            // independently confirm the start interval was actually still.
            if (config_.startup_gyro_bias_calibration && init_verified_count_==init_count_) {
                const Vec3 mean=init_gyro_sum_*(1.0f/init_count_);
                const Vec3 squared=init_gyro_sq_sum_*(1.0f/init_count_);
                const float limit2=config_.startup_gyro_stddev_limit*config_.startup_gyro_stddev_limit;
                const Vec3 variance{squared.x-mean.x*mean.x,
                    squared.y-mean.y*mean.y,squared.z-mean.z*mean.z};
                if (std::isfinite(variance.x) && std::isfinite(variance.y) &&
                    std::isfinite(variance.z) && variance.x>=-1e-8f &&
                    variance.y>=-1e-8f && variance.z>=-1e-8f &&
                    variance.x<=limit2 && variance.y<=limit2 && variance.z<=limit2) {
                    state_.gyro_bias=mean;
                    startup_bias_calibrated_=true;
                    const float minimum=config_.startup_bias_sigma_floor;
                    const float bound=minimum*minimum;
                    for(int i=0;i<3;i++) P_[12+i][12+i]=bound;
                }
            }
            // Zero yaw is an arbitrary local gauge, not magnetic north.
            previous_accel_=imu.accel_mps2;
            have_previous_accel_=true;
            initialized_=true;
            state_time_us_=imu.timestamp_us;
            health_=Health::Nominal;
            return false;
        }
        if (imu.timestamp_us <= last_time_us_) {
            ++invalid_imu_count_;
            health_=Health::Degraded;
            return false;
        }
        const float dt=static_cast<float>(imu.timestamp_us-last_time_us_)*1e-6f;
        last_time_us_=imu.timestamp_us;
        if (!(dt > .0001f && dt <= config_.max_continuous_predict_dt_s)) {
            // Cannot reconstruct unobserved dynamics from the new sample.
            // Latch fault and keep state_time_us_ at the last real propagation.
            // There is NO automatic resume across an unobservable interval.
            ++gap_count_;
            inflate_gap(dt);
            reset_required_=true;
            health_=Health::Fault;
            static_count_=0;
            stationary_=false;
            have_previous_accel_=false;
            return false;
        }
        if (config_.expected_period_us &&
            dt*1.0e6f > config_.expected_period_us*config_.period_gap_ratio) {
            ++gap_count_;
            // Nominal prediction integrates the current reading as a ZOH
            // approximation; extra uncertainty captures unknown intermediate motion.
            inflate_gap(dt-config_.expected_period_us*1e-6f);
            degrade();
        }
        predict(imu.accel_mps2,imu.gyro_rps,dt);
        state_time_us_=imu.timestamp_us;
        ++samples_propagated_;

        const float an=imu.accel_mps2.norm();
        const float gn=imu.gyro_rps.norm();
        const float step=have_previous_accel_ ?
            (imu.accel_mps2-previous_accel_).norm() : 1e9f;
        previous_accel_=imu.accel_mps2;
        have_previous_accel_=true;
        const bool candidate =
            std::fabs(an-kGravity)<config_.static_accel_tolerance*kGravity &&
            gn<config_.static_gyro_limit &&
            step<config_.static_accel_step_limit;
        static_count_ = candidate ? static_count_+1 : 0;
        // Treat a zero dwell setting as one consistent sample. A direct
        // comparison with zero would make every sample, including an obvious
        // motion contradiction, appear stationary.
        const unsigned stationary_dwell=config_.static_min_samples ?
            config_.static_min_samples : 1u;
        stationary_ = static_count_ >= stationary_dwell;
        // The independent stationarity hint may come from e.g. a verified
        // stationary calibration rig. The normal IMU heuristic cannot prove
        // stationary motion during a sustained translational acceleration.
        // External stationarity is trusted only when the current IMU sample
        // does not visibly contradict it. This catches large acceleration,
        // rapid rotation and discontinuities; it cannot detect a constant
        // in-tolerance acceleration, which remains physically ambiguous.
        const bool external_stationary_consistent=external_stationary_confirmed_ && candidate;
        if(external_stationary_confirmed_ && !candidate) ++external_stationary_conflicts_;
        const bool allow_gravity = (config_.gravity_policy==GravityPolicy::ConfirmedOnly) ?
            external_stationary_consistent : (stationary_ || external_stationary_consistent);
        if (allow_gravity && ++aid_count_ >= config_.aid_every_samples) {
            aid_count_=0;
            // A true external confirmation permits gravity realignment even
            // when the estimate has large roll/pitch error. Without one,
            // reject large innovations rather than following apparent gravity.
            correct_gravity_direction(imu.accel_mps2,an,step);
            if (config_.heuristic_zero_rate && (stationary_ || external_stationary_consistent))
                correct_zero_angular_rate(imu.gyro_rps,config_.zero_rate_sigma);
        }
        if (!allow_gravity) aid_count_=0;
        return true;
    }

    // Timestamped external measurements: the current version does NOT retain
    // covariance-consistent state history. Only near-current aiding is accepted.
    // Source identity is recorded by the application; do not fuse an external
    // VIO posterior as independent of shared IMU history without justification.
    bool update_position_world_at(AidingStamp stamp,Vec3 pos,float sigma_m) {
        if (!aiding_time_ok(stamp) || !finite(pos) || !valid_sigma(sigma_m)) return false;
        float r[3]={pos.x-state_.position.x,pos.y-state_.position.y,pos.z-state_.position.z};
        float H[3][kDim]={};
        for(int i=0;i<3;i++) H[i][i]=1;
        return update_external(stamp,r,H,3,sigma_m,16.0f);
    }
    bool update_velocity_world_at(AidingStamp stamp,Vec3 vel,float sigma_mps) {
        if (!aiding_time_ok(stamp) || !finite(vel) || !valid_sigma(sigma_mps)) return false;
        float r[3]={vel.x-state_.velocity.x,vel.y-state_.velocity.y,vel.z-state_.velocity.z};
        float H[3][kDim]={};
        for(int i=0;i<3;i++) H[i][3+i]=1;
        return update_external(stamp,r,H,3,sigma_mps,16.0f);
    }
    // Expose the heading linearization used by the production update path.
    static bool heading_measurement_model(Quat q,float yaw_rad,
                      float residual[3],float H[3][kDim]) {
        if (!std::isfinite(yaw_rad)) return false;
        const float r00=1-2*(q.y*q.y+q.z*q.z);
        const float r10=2*(q.x*q.y+q.w*q.z);
        const float r01=2*(q.x*q.y-q.w*q.z);
        const float r11=1-2*(q.x*q.x+q.z*q.z);
        const float r02=2*(q.x*q.z+q.w*q.y);
        const float r12=2*(q.y*q.z-q.w*q.x);
        const float denom=r00*r00+r10*r10;
        if(denom<0.05f) return false; // heading undefined near vertical body X
        for(int i=0;i<3;i++) {
            residual[i]=0;
            for(int j=0;j<kDim;j++) H[i][j]=0;
        }
        H[0][7]=(r10*r02-r00*r12)/denom;
        H[0][8]=(r00*r11-r10*r01)/denom;
        residual[0]=wrap_pi(yaw_rad-q.yaw());
        return true;
    }
    bool update_heading_at(AidingStamp stamp,float yaw_rad,float sigma_rad) {
        if (!aiding_time_ok(stamp) || !valid_sigma(sigma_rad)) return false;
        float residual[3],H[3][kDim];
        if(!heading_measurement_model(state_.orientation,yaw_rad,residual,H)) return false;
        return update_external(stamp,residual,H,1,sigma_rad,9.0f);
    }
    bool update_zero_angular_rate_at(AidingStamp stamp,Vec3 gyro,float sigma=0.025f) {
        if (!aiding_time_ok(stamp) || !finite(gyro) || !valid_sigma(sigma)) return false;
        const bool ok=correct_zero_angular_rate(gyro,sigma);
        if(ok) {last_accepted_aid_source_=stamp.source_id;last_accepted_aid_time_us_=stamp.timestamp_us;}
        return ok;
    }
    bool update_zero_velocity_at(AidingStamp stamp,float sigma=0.03f) {
        return update_velocity_world_at(stamp,{0,0,0},sigma);
    }
    // Compatibility: these mean a measurement specifically acquired at the
    // current state time. Use *_at() in production; these are NOT for stale VIO.
    bool update_position_world(Vec3 v,float s) {return update_position_world_at({state_time_us_,0,config_.calibration_id},v,s);}
    bool update_velocity_world(Vec3 v,float s) {return update_velocity_world_at({state_time_us_,0,config_.calibration_id},v,s);}
    bool update_heading(float v,float s) {return update_heading_at({state_time_us_,0,config_.calibration_id},v,s);}
    bool update_zero_angular_rate(Vec3 v,float s=0.025f) {return update_zero_angular_rate_at({state_time_us_,0,config_.calibration_id},v,s);}
    bool update_zero_velocity(float s=0.03f) {return update_zero_velocity_at({state_time_us_,0,config_.calibration_id},s);}

    const State &state() const { return state_; }
    bool ready() const { return initialized_; }
    // This is an externally supplied assertion, NOT inferred from the IMU.
    // It affects only future measurements; clear it as soon as motion begins.
    void set_external_stationary_confirmed(bool confirmed) {
        external_stationary_confirmed_=confirmed;
    }
    bool startup_bias_calibrated() const { return startup_bias_calibrated_; }
    uint32_t gravity_applied_updates() const { return gravity_applied_updates_; }
    uint32_t gravity_suppressed_updates() const { return gravity_suppressed_updates_; }
    uint32_t external_stationary_conflicts() const { return external_stationary_conflicts_; }
    bool imu_stationary_candidate() const { return stationary_; }
    uint32_t rejected_updates() const { return rejected_updates_; }
    uint32_t accepted_updates() const { return accepted_updates_; }
    uint32_t last_accepted_aid_source() const {return last_accepted_aid_source_;}
    uint64_t last_accepted_aid_timestamp_us() const {return last_accepted_aid_time_us_;}
    uint32_t stale_aiding_updates() const { return stale_aiding_updates_; }
    uint32_t gap_count() const { return gap_count_; }
    uint32_t saturation_count() const { return saturation_count_; }
    uint32_t invalid_imu_count() const { return invalid_imu_count_; }
    uint32_t samples_propagated() const { return samples_propagated_; }
    uint64_t state_timestamp_us() const { return state_time_us_; }
    uint64_t last_received_timestamp_us() const { return last_time_us_; }
    Health health() const { return health_; }
    bool reset_required() const { return reset_required_; }
    // True means the state is initialized, current and not fault-latched.
    // It is an availability/freshness contract, not an accuracy guarantee.
    bool control_state_valid() const {
        return initialized_ && !reset_required_ && health_!=Health::Fault
            && state_time_us_==last_time_us_;
    }
    float last_nis() const { return last_nis_; }
    float last_nis_gate() const { return last_nis_gate_; }
    bool covariance_positive_definite() const {
        // Keep the covariance and PD check in FP64. Repeated propagation under
        // an unobservable yaw gauge can make its FP32 congruence numerically indefinite.
        double L[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<=i;j++) {
            double sum=P_[i][j];
            for(int k=0;k<j;k++) sum-=L[i][k]*L[j][k];
            if(i==j) { if(!std::isfinite(sum)||sum<=0.0) return false; L[i][j]=std::sqrt(sum); }
            else L[i][j]=sum/L[j][j];
        }
        return true;
    }
    double variance(int index) const {
        return (index>=0 && index<kDim) ? P_[index][index] : NAN;
    }
    double covariance(int row,int col) const { return P_[row][col]; }
    // Audit interface: continuous right-error transition Jacobian with a
    // specific linearization quaternion and debiased IMU input. Matrix order
    // [p,v,theta,ba,bg]. No heap allocations, deterministic execution.
    static void continuous_error_jacobian(Quat q,Vec3 f,Vec3 w,float A[kDim][kDim]) {
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) A[i][j]=0;
        for(int i=0;i<3;i++) A[i][3+i]=1;
        float R[3][3],Sf[3][3],Sw[3][3];
        rotation_matrix(q,R);
        skew(f,Sf);skew(w,Sw);
        for(int i=0;i<3;i++) for(int j=0;j<3;j++) {
            float rs=0;
            for(int k=0;k<3;k++) rs+=R[i][k]*Sf[k][j];
            A[3+i][6+j]=-rs;
            A[3+i][9+j]=-R[i][j];
            A[6+i][6+j]=-Sw[i][j];
        }
        for(int i=0;i<3;i++) A[6+i][12+i]=-1;
    }

    // Exact right-error covariance reset Jacobian for q <- q*Exp(dtheta).
    // With a right-multiplicative error, the reset is
    // Exp(-dtheta)*Exp(dtheta+epsilon), whose first derivative is J_r(dtheta).
    // The Taylor branch avoids cancellation for small corrections.
    static void attitude_reset_jacobian(Vec3 dtheta,float G[3][3]) {
        const float theta2=dot(dtheta,dtheta);
        const float theta=std::sqrt(theta2);
        float a,b;
        if(theta2<1.0e-4f) {
            const float theta4=theta2*theta2;
            a=0.5f-theta2/24.0f+theta4/720.0f;
            b=1.0f/6.0f-theta2/120.0f+theta4/5040.0f;
        } else {
            a=(1.0f-std::cos(theta))/theta2;
            b=(theta-std::sin(theta))/(theta2*theta);
        }
        const float S[3][3]={{0.0f,-dtheta.z,dtheta.y},
            {dtheta.z,0.0f,-dtheta.x},{-dtheta.y,dtheta.x,0.0f}};
        for(int i=0;i<3;i++) for(int j=0;j<3;j++) {
            float s2=0.0f;
            for(int k=0;k<3;k++) s2+=S[i][k]*S[k][j];
            G[i][j]=(i==j?1.0f:0.0f)-a*S[i][j]+b*s2;
        }
    }


private:
    void degrade() { if(health_!=Health::Fault) health_=Health::Degraded; }
    bool saturated(const Imu &im) const {
        const float a=config_.max_accel_axis_mps2,g=config_.max_gyro_axis_rps;
        return std::fabs(im.accel_mps2.x)>=a||std::fabs(im.accel_mps2.y)>=a||
               std::fabs(im.accel_mps2.z)>=a||std::fabs(im.gyro_rps.x)>=g||
               std::fabs(im.gyro_rps.y)>=g||std::fabs(im.gyro_rps.z)>=g;
    }
    void inflate_gap(float dt) {
        if (!(dt>0 && std::isfinite(dt))) return;
        const float t=dt>1.0f?1.0f:dt; // cap per-event growth, continue reporting FAULT
        const float a=config_.gap_unmodeled_accel_mps2;
        const float w=config_.gap_unmodeled_rate_rps;
        for(int i=0;i<3;i++) {
            P_[i][i]+=0.25f*a*a*t*t*t*t;
            P_[3+i][3+i]+=a*a*t*t;
            P_[6+i][6+i]+=w*w*t*t;
        }
    }
    bool aiding_time_ok(AidingStamp st) {
        if(!initialized_ || reset_required_) return false;
        if(config_.calibration_id && st.calibration_id!=config_.calibration_id) {
            ++stale_aiding_updates_; return false;
        }
        if(st.timestamp_us>state_time_us_ || state_time_us_-st.timestamp_us>config_.max_aiding_age_us) {
            ++stale_aiding_updates_;return false;
        }
        return true;
    }
    bool update_external(AidingStamp stamp,const float r[3],const float H[3][kDim],int m,float sigma,float gate) {
        const bool ok=update(r,H,m,sigma,gate);
        if(ok){last_accepted_aid_source_=stamp.source_id;last_accepted_aid_time_us_=stamp.timestamp_us;}
        return ok;
    }
    static bool finite(Vec3 v) {
        return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);
    }
    static bool valid_sigma(float s) { return std::isfinite(s) && s>1e-6f; }
    static void skew(Vec3 a,float out[3][3]) {
        out[0][0]=0;    out[0][1]=-a.z;out[0][2]=a.y;
        out[1][0]=a.z;  out[1][1]=0;   out[1][2]=-a.x;
        out[2][0]=-a.y; out[2][1]=a.x; out[2][2]=0;
    }
    static void rotation_matrix(Quat q,float R[3][3]) {
        const Vec3 x=q.rotate({1,0,0});
        const Vec3 y=q.rotate({0,1,0});
        const Vec3 z=q.rotate({0,0,1});
        R[0][0]=x.x;R[1][0]=x.y;R[2][0]=x.z;
        R[0][1]=y.x;R[1][1]=y.y;R[2][1]=y.z;
        R[0][2]=z.x;R[1][2]=z.y;R[2][2]=z.z;
    }

    void predict(Vec3 accel,Vec3 gyro,float dt) {
        const Vec3 f=accel-state_.accel_bias;
        const Vec3 w=gyro-state_.gyro_bias;
        // Midpoint orientation for translational integration.
        Quat qmid=state_.orientation*Quat::exp(w*(0.5f*dt));
        qmid.normalize();
        const Vec3 a=qmid.rotate(f)+Vec3{0,0,-kGravity};
        state_.position=state_.position+state_.velocity*dt+a*(0.5f*dt*dt);
        state_.velocity=state_.velocity+a*dt;
        state_.orientation=state_.orientation*Quat::exp(w*dt);
        state_.orientation.normalize();

        // Continuous-time right-error dynamics at the midpoint.
        float A[kDim][kDim];
        continuous_error_jacobian(qmid,f,w,A);

        // Phi = I + A dt + 1/2 A^2 dt^2 (reduced discretization error).
        float Phi[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) {
            float a2=0;
            for(int k=0;k<kDim;k++) a2+=A[i][k]*A[k][j];
            Phi[i][j]=(i==j ? 1.0f:0.0f)+A[i][j]*dt+0.5f*a2*dt*dt;
        }
        // P may be severely ill-conditioned while unobserved global yaw
        // uncertainty couples into position. Keep the congruence transform
        // in double precision so FP32 cancellation cannot turn a valid
        // covariance into an indefinite one; the nominal state and IMU model
        // remain FP32, and the process-noise integral below remains unchanged.
        double AP[kDim][kDim]={};
        double newP[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) {
            double sum=0.0;
            for(int k=0;k<kDim;k++) sum+=static_cast<double>(Phi[i][k])*P_[k][j];
            AP[i][j]=sum;
        }
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) {
            double sum=0.0;
            for(int k=0;k<kDim;k++) sum+=AP[i][k]*Phi[j][k];
            newP[i][j]=sum;
        }
        // Q_d = integral_0^dt Phi(tau) G Qc G' Phi(tau)' d tau.
        // Three-point Gauss-Legendre integration with Phi(tau) approximated
        // by I+A*tau+0.5*A^2*tau^2. The resulting Qd is PSD by construction,
        // unlike an unguarded truncated covariance polynomial. Includes
        // position/velocity, attitude/bias and cross-axis noise couplings.
        // White-noise densities here are continuous-time spectral amplitudes.
        float A2[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++)
            for(int k=0;k<kDim;k++) A2[i][j]+=A[i][k]*A[k][j];
        float B[kDim][12]={};
        float Rmid[3][3]; rotation_matrix(qmid,Rmid);
        for(int i=0;i<3;i++) for(int j=0;j<3;j++) B[3+i][j]=-Rmid[i][j];
        for(int i=0;i<3;i++) {
            B[6+i][3+i]=-1;
            B[9+i][6+i]=1;
            B[12+i][9+i]=1;
        }
        const float n2[4]={config_.accel_noise*config_.accel_noise,
            config_.gyro_noise*config_.gyro_noise,
            config_.accel_bias_walk*config_.accel_bias_walk,
            config_.gyro_bias_walk*config_.gyro_bias_walk};
        // Nodes and weights on the unit interval (weights sum to one).
        constexpr float nodes[3]={0.1127016653792583f,0.5f,0.8872983346207417f};
        constexpr float weights[3]={5.0f/18.0f,8.0f/18.0f,5.0f/18.0f};
        // Precompute A*B and A^2*B to reduce per-node operations.
        float AB[kDim][12]={},A2B[kDim][12]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<12;j++) for(int k=0;k<kDim;k++) {
            AB[i][j]+=A[i][k]*B[k][j];
            A2B[i][j]+=A2[i][k]*B[k][j];
        }
        for(int node=0;node<3;node++) {
            const float tau=dt*nodes[node];
            float V[kDim][12];
            for(int i=0;i<kDim;i++) for(int j=0;j<12;j++)
                V[i][j]=B[i][j]+tau*AB[i][j]+0.5f*tau*tau*A2B[i][j];
            for(int i=0;i<kDim;i++) for(int j=0;j<=i;j++) {
                float contribution=0;
                for(int k=0;k<12;k++) contribution+=V[i][k]*V[j][k]*n2[k/3];
                const float q=dt*weights[node]*contribution;
                newP[i][j]+=q;
                if(i!=j) newP[j][i]+=q;
            }
        }
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) P_[i][j]=newP[i][j];
        symmetrize();
    }

    // Return the residual and Jacobian used by the gravity update. This
    // function is intentionally exposed for independent finite-difference
    // verification; H is the residual-to-right-error model r=H*dx.
public:
    static bool gravity_measurement_model(Quat q,Vec3 accel,Vec3 accel_bias,
                 float residual[3],float H[3][kDim]) {
        const Vec3 predicted=q.unrotate({0,0,1});
        const Vec3 debiased=accel-accel_bias;
        const float magnitude=debiased.norm();
        if (!(magnitude>0.5f*kGravity)) return false;
        const Vec3 measured=debiased*(1.0f/magnitude);
        const float h_pred[3]={predicted.x,predicted.y,predicted.z};
        for(int i=0;i<3;i++) {
            residual[i]=((i==0?measured.x:(i==1?measured.y:measured.z))-h_pred[i]);
            for(int j=0;j<kDim;j++) H[i][j]=0;
        }
        float Sh[3][3];skew(predicted,Sh);
        const float u[3]={measured.x,measured.y,measured.z};
        for(int i=0;i<3;i++) for(int j=0;j<3;j++) {
            H[i][6+j]=Sh[i][j];
            // r = normalized(accel - ba) - h(q), and H = -dr/dx.
            // The bias derivative follows the measured direction, including
            // at finite innovation; using h_pred is valid only at zero residual.
            H[i][9+j]=((i==j?1.0f:0.0f)-u[i]*u[j])/magnitude;
        }
        return true;
    }
private:
    void correct_gravity_direction(Vec3 accel,float raw_accel_norm,float accel_step) {
        float residual[3],H[3][kDim];
        if (!gravity_measurement_model(state_.orientation,accel,state_.accel_bias,residual,H)) {
            ++gravity_suppressed_updates_;return;
        }
        float sigma=config_.gravity_update_sigma;
        const bool independently_stationary=external_stationary_confirmed_;
        if (config_.gravity_policy==GravityPolicy::Conservative && !independently_stationary) {
            const Vec3 g_body=state_.orientation.unrotate({0,0,1});
            const Vec3 debiased=accel-state_.accel_bias;
            const float n=debiased.norm();
            if (!(n>1e-6f)) {++gravity_suppressed_updates_;return;}
            const float c=dot(g_body,debiased)*(1.0f/n);
            const float clipped=(c>1.0f?1.0f:(c< -1.0f?-1.0f:c));
            const float angle=std::acos(clipped);
            if (!std::isfinite(angle) || angle>config_.gravity_unverified_max_angle_rad) {
                ++gravity_suppressed_updates_;return;
            }
            // Larger deviations from 1 g or more sample-to-sample motion
            // reduce confidence; they do NOT prove absence of acceleration.
            const float norm_ratio=std::fabs(raw_accel_norm-kGravity)/
                (config_.static_accel_tolerance*kGravity);
            const float step_ratio=accel_step/config_.static_accel_step_limit;
            const float score=std::fmin(1.0f,std::fmax(norm_ratio,step_ratio));
            sigma*=1.0f + config_.gravity_motion_noise_multiplier*score*score;
        }
        if (update(residual,H,3,sigma,16.0f)) ++gravity_applied_updates_;
    }
    bool correct_zero_angular_rate(Vec3 gyro,float sigma) {
        float residual[3]={gyro.x-state_.gyro_bias.x,
                           gyro.y-state_.gyro_bias.y,
                           gyro.z-state_.gyro_bias.z};
        float H[3][kDim]={};
        for(int i=0;i<3;i++) H[i][12+i]=1;
        return update(residual,H,3,sigma,25.0f);
    }

    bool update(const float residual[3], const float H[3][kDim],
                int m,float sigma,float nis_gate) {
        if (!valid_sigma(sigma)) return false;
        double PHt[kDim][3]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<m;j++) {
            double s=0.0;
            for(int k=0;k<kDim;k++) s+=P_[i][k]*H[j][k];
            PHt[i][j]=s;
        }
        double S[3][3]={};
        for(int i=0;i<m;i++) for(int j=0;j<m;j++) {
            double s=(i==j)?static_cast<double>(sigma)*sigma:0.0;
            for(int k=0;k<kDim;k++) s+=H[i][k]*PHt[k][j];
            S[i][j]=s;
        }
        // SPD solve with Cholesky; reject ill-conditioned/nonphysical S.
        double L[3][3]={};
        for(int i=0;i<m;i++) for(int j=0;j<=i;j++) {
            double v=S[i][j];
            for(int k=0;k<j;k++) v-=L[i][k]*L[j][k];
            if(i==j) {
                if(!std::isfinite(v)||v<=1e-12) {health_=Health::Fault;return false;}
                L[i][j]=std::sqrt(v);
            } else L[i][j]=v/L[j][j];
        }
        double S_inv[3][3]={};
        for(int col=0;col<m;col++) {
            double y[3]={};
            for(int i=0;i<m;i++) {
                double v=(i==col?1.0:0.0);
                for(int k=0;k<i;k++) v-=L[i][k]*y[k];
                y[i]=v/L[i][i];
            }
            for(int i=m-1;i>=0;i--) {
                double v=y[i];
                for(int k=i+1;k<m;k++) v-=L[k][i]*S_inv[k][col];
                S_inv[i][col]=v/L[i][i];
            }
        }
        double nis=0;
        for(int i=0;i<m;i++) for(int j=0;j<m;j++) nis+=residual[i]*S_inv[i][j]*residual[j];
        last_nis_=static_cast<float>(nis);
        last_nis_gate_=nis_gate;
        if (!std::isfinite(nis) || nis>nis_gate) { ++rejected_updates_; return false; }
        double K[kDim][3]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<m;j++)
            for(int k=0;k<m;k++) K[i][j]+=PHt[i][k]*S_inv[k][j];
        double dx[kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<m;j++) dx[i]+=K[i][j]*residual[j];
        for(int i=0;i<kDim;i++) if(!std::isfinite(dx[i])) return false;

        // Joseph stabilized update using FP64 covariance intermediates.
        double J[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) {
            double kh=0.0;
            for(int r=0;r<m;r++) kh+=K[i][r]*H[r][j];
            J[i][j]=(i==j ? 1.0:0.0)-kh;
        }
        double JP[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++)
            for(int k=0;k<kDim;k++) JP[i][j]+=J[i][k]*P_[k][j];
        double next[kDim][kDim]={};
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) {
            double val=0.0;
            for(int k=0;k<kDim;k++) val+=JP[i][k]*J[j][k];
            for(int r=0;r<m;r++) val+=K[i][r]*K[j][r]*static_cast<double>(sigma)*sigma;
            next[i][j]=val;
        }
        for(int i=0;i<kDim;i++) for(int j=0;j<kDim;j++) P_[i][j]=next[i][j];

        state_.position=state_.position+Vec3{static_cast<float>(dx[0]),static_cast<float>(dx[1]),static_cast<float>(dx[2])};
        state_.velocity=state_.velocity+Vec3{static_cast<float>(dx[3]),static_cast<float>(dx[4]),static_cast<float>(dx[5])};
        Vec3 dtheta{static_cast<float>(dx[6]),static_cast<float>(dx[7]),static_cast<float>(dx[8])};
        state_.orientation=state_.orientation*Quat::exp(dtheta);
        state_.orientation.normalize();
        state_.accel_bias=state_.accel_bias+Vec3{static_cast<float>(dx[9]),static_cast<float>(dx[10]),static_cast<float>(dx[11])};
        state_.gyro_bias=state_.gyro_bias+Vec3{static_cast<float>(dx[12]),static_cast<float>(dx[13]),static_cast<float>(dx[14])};

        float G[3][3];
        attitude_reset_jacobian(dtheta,G);
        for(int j=0;j<kDim;j++) {
            const double old[3]={P_[6][j],P_[7][j],P_[8][j]};
            for(int i=0;i<3;i++) P_[6+i][j]=G[i][0]*old[0]+G[i][1]*old[1]+G[i][2]*old[2];
        }
        for(int i=0;i<kDim;i++) {
            const double old[3]={P_[i][6],P_[i][7],P_[i][8]};
            for(int j=0;j<3;j++) P_[i][6+j]=G[j][0]*old[0]+G[j][1]*old[1]+G[j][2]*old[2];
        }
        symmetrize();
        ++accepted_updates_;
        return true;
    }
    void symmetrize() {
        for(int i=0;i<kDim;i++) {
            if (P_[i][i]<1e-12) P_[i][i]=1e-12;
            for(int j=i+1;j<kDim;j++) {
                const double avg=.5*(P_[i][j]+P_[j][i]);
                P_[i][j]=avg;P_[j][i]=avg;
            }
        }
    }

    Settings config_;
    State state_{};
    double P_[kDim][kDim]{};
    bool initialized_=false,stationary_=false,have_previous_accel_=false,reset_required_=false;
    uint64_t last_time_us_=0;   // newest received sensor time (also after rejected gap)
    uint64_t state_time_us_=0;  // latest time at which actual prediction ran
    Vec3 previous_accel_{};
    unsigned static_count_=0,aid_count_=0;
    uint32_t rejected_updates_=0,accepted_updates_=0,stale_aiding_updates_=0;
    uint32_t gap_count_=0,saturation_count_=0,invalid_imu_count_=0,samples_propagated_=0;
    Health health_=Health::Aligning;
    float last_nis_=NAN,last_nis_gate_=NAN;
    uint32_t last_accepted_aid_source_=0;
    uint64_t last_accepted_aid_time_us_=0;
    unsigned init_count_=0,init_verified_count_=0;
    Vec3 init_accel_sum_{},init_last_accel_{};
    Vec3 init_gyro_sum_{},init_gyro_sq_sum_{};
    bool startup_bias_calibrated_=false,external_stationary_confirmed_=false;
    uint32_t gravity_suppressed_updates_=0,gravity_applied_updates_=0;
    uint32_t external_stationary_conflicts_=0;
};
} // namespace inertial
