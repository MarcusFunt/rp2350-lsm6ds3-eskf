// PR 1 deterministic regression and provenance capture.
// Host simulation only; it does not reproduce missing historical source data.
#include "../eskf15.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <random>
#include <string>
#include <vector>

using namespace inertial;

namespace {
constexpr float kDt = 0.005f;
constexpr float kRateHz = 200.0f;
constexpr unsigned kSamples = 2400; // 0.005 .. 12.000 s
constexpr uint64_t kEpochUs = 1000000;
constexpr uint32_t kHeadingSource = 0x48454144u; // "HEAD"
constexpr float kAccelDensity = 0.0015f;
constexpr float kGyroDensity = 0.00025f;
constexpr float kAccelWalk = 0.00008f;
constexpr float kGyroWalk = 0.00003f;
constexpr float kHeadingSigma = 0.04f;
constexpr float kRadToDeg = 180.0f / kPi;

enum class NoiseMode { Clean, AccelOnly, GyroOnly, Combined };
enum class StartupKnowledge { Unknown, ExternallyVerifiedStatic };

const char* name(NoiseMode value) {
    switch (value) {
    case NoiseMode::Clean: return "clean";
    case NoiseMode::AccelOnly: return "accel_only";
    case NoiseMode::GyroOnly: return "gyro_only";
    case NoiseMode::Combined: return "combined";
    }
    return "unknown";
}
const char* name(StartupKnowledge value) {
    return value == StartupKnowledge::Unknown ? "UNKNOWN" : "EXTERNALLY_VERIFIED_STATIC";
}
const char* name(GravityPolicy value) {
    switch (value) {
    case GravityPolicy::Conservative: return "Conservative";
    case GravityPolicy::LegacyHeuristic: return "LegacyHeuristic";
    case GravityPolicy::ConfirmedOnly: return "ConfirmedOnly";
    }
    return "unknown";
}
const char* name(Health value) {
    switch (value) {
    case Health::Aligning: return "Aligning";
    case Health::Nominal: return "Nominal";
    case Health::Degraded: return "Degraded";
    case Health::Fault: return "Fault";
    }
    return "unknown";
}

struct Scenario {
    const char* id;
};
struct Motion {
    Vec3 body_rate{};
    Vec3 world_acceleration{};
};
Motion motion(const char* scenario, float t) {
    if (std::strcmp(scenario, "pure_roll") == 0 && t >= 2.0f && t < 8.0f)
        return {{0.18f, 0.0f, 0.0f}, {}};
    if (std::strcmp(scenario, "lateral_accel_0p2g") == 0 && t >= 2.0f && t < 8.0f)
        return {{}, {0.2f * kGravity, 0.0f, 0.0f}};
    if (std::strcmp(scenario, "slow_yaw") == 0 && t >= 2.0f && t < 12.0f)
        return {{0.0f, 0.0f, 0.035f}, {}};
    return {};
}

struct Sample {
    Imu imu{};
    float time_s = 0.0f;
    Quat truth_q{};
    Vec3 truth_position{};
    Vec3 truth_velocity{};
    Vec3 truth_accel_bias{};
    Vec3 truth_gyro_bias{};
    bool has_heading = false;
    float heading_rad = 0.0f;
};

bool accel_noise_enabled(NoiseMode mode) {
    return mode == NoiseMode::AccelOnly || mode == NoiseMode::Combined;
}
bool gyro_noise_enabled(NoiseMode mode) {
    return mode == NoiseMode::GyroOnly || mode == NoiseMode::Combined;
}

std::vector<Sample> generate(const Scenario& scenario, NoiseMode noise, unsigned seed) {
    std::mt19937 sensor_rng(seed);
    std::normal_distribution<float> sensor_normal(0.0f, 1.0f);
    std::mt19937 heading_rng(seed ^ 0x91e10da5u);
    std::normal_distribution<float> heading_normal(0.0f, kHeadingSigma);
    const float accel_sigma = kAccelDensity * std::sqrt(kRateHz);
    const float gyro_sigma = kGyroDensity * std::sqrt(kRateHz);
    const float accel_walk_step = kAccelWalk * std::sqrt(kDt);
    const float gyro_walk_step = kGyroWalk * std::sqrt(kDt);
    std::vector<Sample> samples;
    samples.reserve(kSamples);
    Quat truth_q{};
    Vec3 truth_position{}, truth_velocity{}, accel_bias{}, gyro_bias{};

    for (unsigned i = 1; i <= kSamples; ++i) {
        const float t = static_cast<float>(i) * kDt;
        const Motion sample_motion = motion(scenario.id, t);
        const Motion interval_motion = motion(scenario.id, t - 0.5f * kDt);
        truth_q = truth_q * Quat::exp(interval_motion.body_rate * kDt);
        truth_q.normalize();
        truth_position = truth_position + truth_velocity * kDt
            + interval_motion.world_acceleration * (0.5f * kDt * kDt);
        truth_velocity = truth_velocity + interval_motion.world_acceleration * kDt;

        if (accel_noise_enabled(noise)) {
            accel_bias = accel_bias + Vec3{sensor_normal(sensor_rng) * accel_walk_step,
                sensor_normal(sensor_rng) * accel_walk_step,
                sensor_normal(sensor_rng) * accel_walk_step};
        }
        if (gyro_noise_enabled(noise)) {
            gyro_bias = gyro_bias + Vec3{sensor_normal(sensor_rng) * gyro_walk_step,
                sensor_normal(sensor_rng) * gyro_walk_step,
                sensor_normal(sensor_rng) * gyro_walk_step};
        }

        Vec3 accel = truth_q.unrotate(sample_motion.world_acceleration + Vec3{0.0f, 0.0f, kGravity})
            + accel_bias;
        Vec3 gyro = sample_motion.body_rate + gyro_bias;
        if (accel_noise_enabled(noise)) {
            accel = accel + Vec3{sensor_normal(sensor_rng) * accel_sigma,
                sensor_normal(sensor_rng) * accel_sigma,
                sensor_normal(sensor_rng) * accel_sigma};
        }
        if (gyro_noise_enabled(noise)) {
            gyro = gyro + Vec3{sensor_normal(sensor_rng) * gyro_sigma,
                sensor_normal(sensor_rng) * gyro_sigma,
                sensor_normal(sensor_rng) * gyro_sigma};
        }

        Sample sample;
        sample.time_s = t;
        sample.imu = {kEpochUs + static_cast<uint64_t>(i) * 5000u, accel, gyro};
        sample.truth_q = truth_q;
        sample.truth_position = truth_position;
        sample.truth_velocity = truth_velocity;
        sample.truth_accel_bias = accel_bias;
        sample.truth_gyro_bias = gyro_bias;
        // Separate synthetic magnetometer-like heading stream, sampled at 1 Hz.
        // It is not injected into IMU_ONLY runs and is not physical hardware data.
        sample.has_heading = t >= 2.0f && i % 200u == 0u;
        if (sample.has_heading)
            sample.heading_rad = wrap_pi(truth_q.yaw() + heading_normal(heading_rng));
        samples.push_back(sample);
    }
    return samples;
}

struct Variant {
    const char* input_mode;
    StartupKnowledge startup;
    bool startup_calibration;
    bool trusted_heading_aid;
    GravityPolicy policy;
};

std::vector<Variant> variants() {
    std::vector<Variant> result;
    for (const char* input_mode : {"IMU_ONLY", "TRUSTED_AIDED"}) {
        for (StartupKnowledge startup : {StartupKnowledge::Unknown,
                 StartupKnowledge::ExternallyVerifiedStatic}) {
            for (bool calibrate : {false, true}) {
                if (calibrate && startup == StartupKnowledge::Unknown) continue;
                for (GravityPolicy policy : {GravityPolicy::Conservative,
                         GravityPolicy::LegacyHeuristic, GravityPolicy::ConfirmedOnly}) {
                    const bool trusted = std::strcmp(input_mode, "TRUSTED_AIDED") == 0;
                    result.push_back({input_mode, startup, calibrate, trusted, policy});
                }
            }
        }
    }
    return result;
}

Settings settings_for(const Variant& variant) {
    Settings settings;
    settings.accel_noise = kAccelDensity;
    settings.gyro_noise = kGyroDensity;
    settings.accel_bias_walk = kAccelWalk;
    settings.gyro_bias_walk = kGyroWalk;
    settings.gravity_policy = variant.policy;
    settings.startup_gyro_bias_calibration = variant.startup_calibration;
    settings.expected_period_us = 5000;
    return settings;
}

struct Metrics {
    uint32_t expected = 0;
    uint32_t valid = 0;
    uint32_t stale = 0;
    uint32_t aid_accepted = 0;
    uint32_t aid_rejected = 0;
    double tilt_sq = 0.0;
    double attitude_sq = 0.0;
    double yaw_sq = 0.0;
    double position_sq = 0.0;
    double velocity_sq = 0.0;
    double gravity_nis_sum = 0.0;
    uint32_t gravity_nis_count = 0;
    std::vector<float> tilt_errors;
    std::vector<float> yaw_abs_errors;
    std::vector<float> position_errors;
    uint32_t gravity_applied = 0;
    uint32_t gravity_suppressed = 0;
    float max_state_age_us = 0.0f;
    float max_abs_yaw_error_deg = 0.0f;
    float final_bias_error_accel = std::numeric_limits<float>::quiet_NaN();
    float final_bias_error_gyro = std::numeric_limits<float>::quiet_NaN();

    static float rms(double sum_sq, uint32_t n) {
        return n ? static_cast<float>(std::sqrt(sum_sq / n))
            : std::numeric_limits<float>::quiet_NaN();
    }
    static float percentile(std::vector<float> values, float p) {
        if (values.empty()) return std::numeric_limits<float>::quiet_NaN();
        std::sort(values.begin(), values.end());
        const size_t index = static_cast<size_t>(p * static_cast<float>(values.size() - 1));
        return values[index];
    }
};

struct FilterRun {
    Variant variant;
    Eskf15 filter;
    Metrics metrics;
    explicit FilterRun(Variant v) : variant(v), filter(settings_for(v)) {}
};

float tilt_error_deg(Quat estimate, Quat truth) {
    const Vec3 gravity_est = estimate.unrotate({0.0f, 0.0f, 1.0f});
    const Vec3 gravity_truth = truth.unrotate({0.0f, 0.0f, 1.0f});
    return std::acos(std::max(-1.0f, std::min(1.0f, dot(gravity_est, gravity_truth)))) * kRadToDeg;
}

float attitude_error_deg(Quat estimate, Quat truth) {
    Quat error = estimate * Quat{truth.w, -truth.x, -truth.y, -truth.z};
    error.normalize();
    if (error.w < 0.0f) error = {-error.w, -error.x, -error.y, -error.z};
    const float sin_half = std::sqrt(error.x * error.x + error.y * error.y + error.z * error.z);
    return 2.0f * std::atan2(sin_half, error.w) * kRadToDeg;
}

void write_u32(std::ofstream& out, uint32_t value) {
    for (unsigned shift = 0; shift < 32; shift += 8)
        out.put(static_cast<char>((value >> shift) & 0xffu));
}
void write_u64(std::ofstream& out, uint64_t value) {
    for (unsigned shift = 0; shift < 64; shift += 8)
        out.put(static_cast<char>((value >> shift) & 0xffu));
}
void write_f32(std::ofstream& out, float value) {
    uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value), "float32 required");
    std::memcpy(&bits, &value, sizeof(bits));
    write_u32(out, bits);
}
void write_sample(std::ofstream& out, const Sample& sample) {
    write_u64(out, sample.imu.timestamp_us);
    for (float v : {sample.imu.accel_mps2.x, sample.imu.accel_mps2.y, sample.imu.accel_mps2.z,
             sample.imu.gyro_rps.x, sample.imu.gyro_rps.y, sample.imu.gyro_rps.z,
             sample.heading_rad}) write_f32(out, v);
    write_u32(out, sample.has_heading ? 1u : 0u);
}

void csv_float(std::ostream& out, float value) {
    if (std::isfinite(value)) out << value;
}
void csv_vec(std::ostream& out, Vec3 v) { out << v.x << ',' << v.y << ',' << v.z; }
void csv_quat(std::ostream& out, Quat q) { out << q.w << ',' << q.x << ',' << q.y << ',' << q.z; }

void write_summary_row(std::ostream& out, const Scenario& scenario, NoiseMode noise,
    const char* split, unsigned seed, const Variant& variant, const Metrics& m,
    const Eskf15& filter) {
    const uint32_t unavailable = m.expected - m.valid;
    out << 2 << ',' << scenario.id << ',' << name(noise) << ',' << split << ',' << seed << ','
        << variant.input_mode << ',' << name(variant.startup) << ','
        << (variant.startup_calibration ? "ON" : "OFF") << ','
        << (variant.trusted_heading_aid ? "independent_heading_1hz" : "NONE") << ','
        << name(variant.policy) << ',' << m.expected << ',' << m.valid << ',' << unavailable << ','
        << m.stale << ',';
    csv_float(out, static_cast<float>(m.valid) / static_cast<float>(m.expected));
    out << ','; csv_float(out, Metrics::rms(m.tilt_sq, m.valid));
    out << ','; csv_float(out, Metrics::percentile(m.tilt_errors, 0.95f));
    out << ','; csv_float(out, m.tilt_errors.empty() ? std::numeric_limits<float>::quiet_NaN()
        : *std::max_element(m.tilt_errors.begin(), m.tilt_errors.end()));
    out << ','; csv_float(out, Metrics::rms(m.attitude_sq, m.valid));
    out << ','; csv_float(out, Metrics::rms(m.yaw_sq, m.valid));
    out << ','; csv_float(out, Metrics::percentile(m.yaw_abs_errors, 0.95f));
    out << ','; csv_float(out, m.max_abs_yaw_error_deg);
    out << ','; csv_float(out, Metrics::rms(m.position_sq, m.valid));
    out << ','; csv_float(out, Metrics::percentile(m.position_errors, 0.95f));
    out << ','; csv_float(out, Metrics::rms(m.velocity_sq, m.valid));
    out << ','; csv_float(out, m.gravity_nis_count ? static_cast<float>(m.gravity_nis_sum / m.gravity_nis_count)
        : std::numeric_limits<float>::quiet_NaN());
    out << ',' << m.gravity_nis_count << ',' << m.gravity_applied << ',' << m.gravity_suppressed << ','
        << m.aid_accepted << ',' << m.aid_rejected << ',' << name(filter.health()) << ','
        << m.max_state_age_us << ',';
    csv_float(out, m.final_bias_error_accel);
    out << ','; csv_float(out, m.final_bias_error_gyro);
    out << '\n';
}

void write_trace_row(std::ostream& out, const Scenario& scenario, NoiseMode noise,
    const char* split, unsigned seed, const Variant& variant, const Sample& sample,
    const Eskf15& filter, const char* gravity_event, float nis, const char* nis_source,
    bool valid) {
    const State& estimate = filter.state();
    const float age = sample.imu.timestamp_us >= filter.state_timestamp_us()
        ? static_cast<float>(sample.imu.timestamp_us - filter.state_timestamp_us())
        : std::numeric_limits<float>::quiet_NaN();
    out << 2 << ',' << scenario.id << ',' << name(noise) << ',' << split << ',' << seed << ','
        << variant.input_mode << ',' << name(variant.startup) << ','
        << (variant.startup_calibration ? "ON" : "OFF") << ','
        << (variant.trusted_heading_aid ? "independent_heading_1hz" : "NONE") << ','
        << name(variant.policy) << ',' << sample.imu.timestamp_us << ',' << sample.time_s << ',';
    csv_quat(out, sample.truth_q); out << ','; csv_vec(out, sample.truth_position); out << ',';
    csv_vec(out, sample.truth_velocity); out << ','; csv_vec(out, sample.imu.accel_mps2); out << ',';
    csv_vec(out, sample.imu.gyro_rps); out << ','; csv_quat(out, estimate.orientation); out << ',';
    csv_vec(out, estimate.position); out << ','; csv_vec(out, estimate.velocity); out << ',';
    csv_vec(out, sample.truth_accel_bias); out << ','; csv_vec(out, estimate.accel_bias); out << ',';
    csv_vec(out, sample.truth_gyro_bias); out << ','; csv_vec(out, estimate.gyro_bias); out << ',';
    out << filter.covariance(0,0) << ',' << filter.covariance(3,3) << ','
        << filter.covariance(6,6) << ',' << filter.covariance(9,9) << ','
        << filter.covariance(12,12) << ',' << filter.covariance(6,12) << ','
        << filter.covariance(3,12) << ',' << gravity_event << ',';
    csv_float(out, nis);
    out << ',' << nis_source << ',' << (sample.has_heading ? "true" : "false") << ','
        << (valid ? "true" : "false") << ',' << name(filter.health()) << ',' << age << ',';
    csv_float(out, tilt_error_deg(estimate.orientation, sample.truth_q));
    out << ','; csv_float(out, attitude_error_deg(estimate.orientation, sample.truth_q));
    out << ','; csv_float(out, wrap_pi(estimate.orientation.yaw() - sample.truth_q.yaw()) * kRadToDeg);
    out << ','; csv_float(out, (estimate.position - sample.truth_position).norm());
    out << ','; csv_float(out, (estimate.velocity - sample.truth_velocity).norm());
    out << '\n';
}

std::vector<unsigned> development_seeds() {
    std::vector<unsigned> v;
    for (unsigned s = 101; s <= 116; ++s) v.push_back(s);
    return v;
}
std::vector<unsigned> heldout_seeds() {
    std::vector<unsigned> v;
    for (unsigned s = 1001; s <= 1016; ++s) v.push_back(s);
    return v;
}

void write_trial(std::ostream& summary, std::ostream& trace, std::ostream& index,
    std::ofstream& sample_file, const Scenario& scenario, NoiseMode noise,
    const char* split, unsigned seed) {
    const std::vector<Sample> samples = generate(scenario, noise, seed);
    const std::streamoff byte_offset = static_cast<std::streamoff>(sample_file.tellp());
    for (const Sample& sample : samples) write_sample(sample_file, sample);
    const std::string trial_id = std::string(scenario.id) + "/" + name(noise) + "/" + split + "/" + std::to_string(seed);
    index << trial_id << ',' << scenario.id << ',' << name(noise) << ',' << split << ',' << seed
          << ',' << byte_offset << ',' << samples.size() << ',' << 40 << '\n';

    std::vector<FilterRun> runs;
    for (const Variant& variant : variants()) runs.emplace_back(variant);
    for (const Sample& sample : samples) {
        const bool in_eval = sample.time_s >= 2.0f;
        const bool combined_trace = seed == 101 && std::strcmp(split, "development") == 0
            && noise == NoiseMode::Combined
            && (std::strcmp(scenario.id, "pure_roll") == 0
                || std::strcmp(scenario.id, "lateral_accel_0p2g") == 0
                || std::strcmp(scenario.id, "slow_yaw") == 0);
        const bool clean_truth_trace = seed == 0 && std::strcmp(split, "reference") == 0
            && noise == NoiseMode::Clean
            && std::strcmp(scenario.id, "lateral_accel_0p2g") == 0;
        for (FilterRun& run : runs) {
            const Variant& variant = run.variant;
            run.filter.set_external_stationary_confirmed(
                variant.startup == StartupKnowledge::ExternallyVerifiedStatic && sample.time_s < 2.0f);
            const uint32_t applied_before = run.filter.gravity_applied_updates();
            const uint32_t suppressed_before = run.filter.gravity_suppressed_updates();
            const uint32_t rejected_before = run.filter.rejected_updates();
            run.filter.process(sample.imu);
            const uint32_t applied_after_process = run.filter.gravity_applied_updates();
            const uint32_t suppressed_after_process = run.filter.gravity_suppressed_updates();
            const uint32_t rejected_after_process = run.filter.rejected_updates();
            const bool gravity_applied = applied_after_process > applied_before;
            const bool gravity_suppressed = suppressed_after_process > suppressed_before;
            const bool gravity_rejected = rejected_after_process > rejected_before
                && !gravity_applied && !gravity_suppressed;
            const char* gravity_event = gravity_applied ? "accepted"
                : (gravity_suppressed ? "suppressed" : (gravity_rejected ? "rejected" : "none"));
            float nis = std::numeric_limits<float>::quiet_NaN();
            const char* nis_source = "";
            if (gravity_applied && std::isfinite(run.filter.last_nis())) {
                nis = run.filter.last_nis();
                nis_source = "gravity";
                run.metrics.gravity_nis_sum += nis;
                ++run.metrics.gravity_nis_count;
            }
            bool aid_accepted = false;
            if (variant.trusted_heading_aid && sample.has_heading) {
                aid_accepted = run.filter.update_heading_at(
                    {sample.imu.timestamp_us, kHeadingSource, 0}, sample.heading_rad, kHeadingSigma);
                if (aid_accepted && std::isfinite(run.filter.last_nis())) {
                    nis = run.filter.last_nis();
                    nis_source = "heading";
                }
            }

            if (in_eval) {
                Metrics& m = run.metrics;
                ++m.expected;
                if (run.filter.control_state_valid()) {
                    ++m.valid;
                    const State& estimate = run.filter.state();
                    const float tilt = tilt_error_deg(estimate.orientation, sample.truth_q);
                    const float attitude = attitude_error_deg(estimate.orientation, sample.truth_q);
                    const float yaw = wrap_pi(estimate.orientation.yaw() - sample.truth_q.yaw()) * kRadToDeg;
                    const float position = (estimate.position - sample.truth_position).norm();
                    const float velocity = (estimate.velocity - sample.truth_velocity).norm();
                    m.tilt_sq += tilt * tilt;
                    m.attitude_sq += attitude * attitude;
                    m.yaw_sq += yaw * yaw;
                    m.position_sq += position * position;
                    m.velocity_sq += velocity * velocity;
                    m.tilt_errors.push_back(tilt);
                    m.yaw_abs_errors.push_back(std::fabs(yaw));
                    m.max_abs_yaw_error_deg = std::max(m.max_abs_yaw_error_deg, std::fabs(yaw));
                    m.position_errors.push_back(position);
                    m.final_bias_error_accel = (estimate.accel_bias - sample.truth_accel_bias).norm();
                    m.final_bias_error_gyro = (estimate.gyro_bias - sample.truth_gyro_bias).norm();
                }
                const uint64_t state_time = run.filter.state_timestamp_us();
                if (state_time < sample.imu.timestamp_us) ++m.stale;
                m.max_state_age_us = std::max(m.max_state_age_us,
                    state_time <= sample.imu.timestamp_us
                        ? static_cast<float>(sample.imu.timestamp_us - state_time) : 0.0f);
                m.gravity_applied = run.filter.gravity_applied_updates();
                m.gravity_suppressed = run.filter.gravity_suppressed_updates();
                if (variant.trusted_heading_aid && sample.has_heading) {
                    if (aid_accepted) ++m.aid_accepted;
                    else ++m.aid_rejected;
                }
            }

            const bool combined_trace_variant = combined_trace
                && variant.startup == StartupKnowledge::ExternallyVerifiedStatic
                && !variant.startup_calibration;
            const bool clean_truth_trace_variant = clean_truth_trace
                && std::strcmp(variant.input_mode, "IMU_ONLY") == 0
                && variant.startup == StartupKnowledge::Unknown
                && !variant.startup_calibration;
            if ((combined_trace_variant || clean_truth_trace_variant) && in_eval) {
                write_trace_row(trace, scenario, noise, split, seed, variant, sample,
                    run.filter, gravity_event, nis, nis_source, run.filter.control_state_valid());
            }
        }
    }
    for (const FilterRun& run : runs)
        write_summary_row(summary, scenario, noise, split, seed, run.variant, run.metrics, run.filter);
}

void ensure_stream(std::ofstream& stream, const char* path) {
    if (!stream) {
        std::fprintf(stderr, "Cannot open output: %s\n", path);
        std::exit(2);
    }
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "Usage: pr1_baseline OUTPUT_DIRECTORY\n");
        return 2;
    }
    const std::string dir = argv[1];
    const std::string summary_path = dir + "/pr1_baseline_protocol_v2.csv";
    const std::string trace_path = dir + "/pr1_representative_traces_protocol_v2.csv";
    const std::string index_path = dir + "/pr1_sample_index_protocol_v2.csv";
    const std::string sample_path = dir + "/pr1_imu_samples_protocol_v2.bin";
    std::ofstream summary(summary_path), trace(trace_path), index(index_path), sample_file(sample_path, std::ios::binary);
    ensure_stream(summary, summary_path.c_str());
    ensure_stream(trace, trace_path.c_str());
    ensure_stream(index, index_path.c_str());
    ensure_stream(sample_file, sample_path.c_str());
    summary << "evaluation_protocol_version,scenario,noise_mode,seed_split,seed,input_mode,startup_knowledge,startup_calibration,runtime_aid,estimator,expected,valid,unavailable,stale,valid_fraction,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,attitude_rms_deg,yaw_rms_deg,yaw_abs_p95_deg,yaw_abs_max_deg,position_rms_m,position_p95_m,velocity_rms_m_s,gravity_nis_mean,gravity_nis_count,gravity_applied,gravity_suppressed,aid_accepted,aid_rejected,health_end,max_state_age_us,accel_bias_error_end_m_s2,gyro_bias_error_end_rad_s\n";
    trace << "evaluation_protocol_version,scenario,noise_mode,seed_split,seed,input_mode,startup_knowledge,startup_calibration,runtime_aid,estimator,timestamp_us,time_s,truth_qw,truth_qx,truth_qy,truth_qz,truth_px,truth_py,truth_pz,truth_vx,truth_vy,truth_vz,imu_ax,imu_ay,imu_az,imu_gx,imu_gy,imu_gz,estimate_qw,estimate_qx,estimate_qy,estimate_qz,estimate_px,estimate_py,estimate_pz,estimate_vx,estimate_vy,estimate_vz,truth_bax,truth_bay,truth_baz,estimate_bax,estimate_bay,estimate_baz,truth_bgx,truth_bgy,truth_bgz,estimate_bgx,estimate_bgy,estimate_bgz,cov_p_x,cov_v_x,cov_theta_x,cov_ba_x,cov_bg_x,cov_theta_bg_x,cov_v_bg_x,gravity_event,nis,nis_source,heading_sample_present,output_valid,health,state_age_us,tilt_error_deg,attitude_error_deg,euler_yaw_error_deg,position_error_m,velocity_error_m_s\n";
    index << "trial_id,scenario,noise_mode,seed_split,seed,offset_bytes,record_count,record_bytes\n";
    summary << std::fixed << std::setprecision(8);
    trace << std::fixed << std::setprecision(8);

    const std::array<Scenario, 4> scenarios{{{"static"}, {"pure_roll"},
        {"lateral_accel_0p2g"}, {"slow_yaw"}}};
    for (const Scenario& scenario : scenarios)
        write_trial(summary, trace, index, sample_file, scenario, NoiseMode::Clean, "reference", 0);
    const std::array<NoiseMode, 3> noisy{{NoiseMode::AccelOnly, NoiseMode::GyroOnly, NoiseMode::Combined}};
    for (const Scenario& scenario : scenarios) {
        if (std::strcmp(scenario.id, "static") == 0) continue;
        for (NoiseMode noise : noisy) {
            for (unsigned seed : development_seeds())
                write_trial(summary, trace, index, sample_file, scenario, noise, "development", seed);
            for (unsigned seed : heldout_seeds())
                write_trial(summary, trace, index, sample_file, scenario, noise, "held_out", seed);
        }
    }
    std::printf("Wrote protocol-v2 PR1 baseline: 4 scenarios, 292 input streams, 16 development and 16 held-out seeds per noisy motion cell, 3 gravity policies, IMU_ONLY and TRUSTED_AIDED\n");
    return 0;
}
