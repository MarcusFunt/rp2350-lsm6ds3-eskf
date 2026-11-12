// Host-only forensic replay of the frozen PR1 protocol-v2 pure-roll stream.
// The same raw record is passed through all three ESKF configurations.
#include "../eskf15.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
using namespace inertial;

constexpr std::uint64_t kEpochUs = 1000000;
constexpr std::uint32_t kExpectedSamples = 2400;
constexpr std::uint32_t kHeadingSource = 0x48454144u;
constexpr float kRateHz = 200.0f;
constexpr float kDt = 1.0f / kRateHz;
constexpr float kHeadingSigmaRad = 0.04f;
constexpr double kHeadingNisGate = 9.0;
constexpr float kPureRollRateRadS = 0.18f;

struct InputRecord {
    std::uint64_t timestamp_us = 0;
    Vec3 accel{};
    Vec3 gyro{};
    float independent_heading = 0.0f;
    std::uint32_t flags = 0;
};

struct Run {
    const char* id;
    const char* source;
    bool apply_heading;
    bool use_oracle;
    Eskf15 filter;
    std::uint32_t accepted = 0;
    std::uint32_t rejected = 0;
    std::uint32_t valid = 0;
    std::uint32_t expected = 0;
    double tilt_sq = 0.0;
    double yaw_sq = 0.0;
    double max_tilt = 0.0;
    bool all_covariances_valid = true;

    Run(const char* name, const char* measurement_source, bool aiding, bool oracle)
        : id(name), source(measurement_source), apply_heading(aiding), use_oracle(oracle), filter(settings()) {}

    static Settings settings() {
        Settings cfg{};
        // Match the frozen PR1 protocol-v2 model used to create this raw stream.
        cfg.accel_noise = 0.0015f;
        cfg.gyro_noise = 0.00025f;
        cfg.accel_bias_walk = 0.00008f;
        cfg.gyro_bias_walk = 0.00003f;
        cfg.gravity_policy = GravityPolicy::Conservative;
        cfg.startup_gyro_bias_calibration = false;
        cfg.expected_period_us = 5000;
        return cfg;
    }
};

std::uint32_t read_u32(std::istream& in) {
    std::uint32_t value = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) {
        const int byte = in.get();
        if (byte == std::char_traits<char>::eof()) throw std::runtime_error("truncated PR1 record");
        value |= static_cast<std::uint32_t>(static_cast<unsigned char>(byte)) << shift;
    }
    return value;
}

std::uint64_t read_u64(std::istream& in) {
    std::uint64_t value = 0;
    for (unsigned shift = 0; shift < 64; shift += 8) {
        const int byte = in.get();
        if (byte == std::char_traits<char>::eof()) throw std::runtime_error("truncated PR1 record");
        value |= static_cast<std::uint64_t>(static_cast<unsigned char>(byte)) << shift;
    }
    return value;
}

float read_f32(std::istream& in) {
    const std::uint32_t bits = read_u32(in);
    float value = 0.0f;
    static_assert(sizeof(bits) == sizeof(value), "float32 required");
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

InputRecord read_record(std::istream& in) {
    InputRecord sample;
    sample.timestamp_us = read_u64(in);
    sample.accel = {read_f32(in), read_f32(in), read_f32(in)};
    sample.gyro = {read_f32(in), read_f32(in), read_f32(in)};
    sample.independent_heading = read_f32(in);
    sample.flags = read_u32(in);
    return sample;
}

void csv_double(std::ostream& out, double value) {
    if (std::isfinite(value)) out << value;
}

void csv_float(std::ostream& out, float value) {
    if (std::isfinite(value)) out << value;
}

double norm3(const double* values) {
    return std::sqrt(values[0] * values[0] + values[1] * values[1] + values[2] * values[2]);
}

bool finite_vec(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

double crossblock_norm(const Eskf15& filter, int row_start, int col_start) {
    double sum = 0.0;
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) {
        const double value = filter.covariance(row_start + r, col_start + c);
        sum += value * value;
    }
    return std::sqrt(sum);
}

void advance_truth_orientation(Quat& truth, float time_s) {
    // Keep the generator's per-sample midpoint integration and normalization
    // so the simulator-oracle heading matches the frozen truth trace.
    const float interval_time = time_s - 0.5f * kDt;
    const Vec3 body_rate = interval_time >= 2.0f && interval_time < 8.0f
        ? Vec3{kPureRollRateRadS, 0.0f, 0.0f} : Vec3{};
    truth = truth * Quat::exp(body_rate * kDt);
    truth.normalize();
}

double projected_tilt_deg(Quat estimate, Quat truth) {
    const Vec3 up_est = estimate.unrotate({0.0f, 0.0f, 1.0f});
    const Vec3 up_truth = truth.unrotate({0.0f, 0.0f, 1.0f});
    const double cosine = std::clamp(static_cast<double>(dot(up_est, up_truth)), -1.0, 1.0);
    return std::acos(cosine) * 180.0 / static_cast<double>(kPi);
}

void event_header(std::ostream& out) {
    out << "input_sha256,aid_mode,measurement_source,sample_index,time_s,timestamp_us,heading_available,update_attempted,update_accepted,"
           "measurement_sigma_rad,nis_gate,measured_yaw_rad,predicted_yaw_rad,wrapped_innovation_rad,H_valid,S_rad2,nis,production_last_nis,"
           "gain_position_norm,gain_velocity_norm,gain_attitude_norm,gain_accel_bias_norm,gain_gyro_bias_norm,"
           "q_pre_w,q_pre_x,q_pre_y,q_pre_z,q_post_w,q_post_x,q_post_y,q_post_z,tilt_pre_deg,tilt_post_deg,delta_tilt_deg,"
           "accel_bias_pre_x,accel_bias_pre_y,accel_bias_pre_z,accel_bias_post_x,accel_bias_post_y,accel_bias_post_z,"
           "gyro_bias_pre_x,gyro_bias_pre_y,gyro_bias_pre_z,gyro_bias_post_x,gyro_bias_post_y,gyro_bias_post_z";
    for (int i = 0; i < kDim; ++i) out << ",H_" << i;
    for (int i = 0; i < kDim; ++i) out << ",K_" << i;
    for (const char* prefix : {"dx_proposed", "dx_injected"})
        for (int i = 0; i < kDim; ++i) out << ',' << prefix << '_' << i;
    for (const char* block : {"theta_ba", "theta_bg"}) {
        for (const char* stage : {"pre", "post"})
            for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c)
                out << ",P_" << block << '_' << stage << '_' << r << '_' << c;
    }
    out << ",P_theta_ba_fro_pre,P_theta_ba_fro_post,P_theta_bg_fro_pre,P_theta_bg_fro_post\n";
}

void trace_header(std::ostream& out) {
    out << "input_sha256,aid_mode,sample_index,time_s,timestamp_us,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,"
           "heading_available,measurement_source,update_attempted,update_accepted,"
           "q_truth_w,q_truth_x,q_truth_y,q_truth_z,q_pre_w,q_pre_x,q_pre_y,q_pre_z,q_post_w,q_post_x,q_post_y,q_post_z,"
           "predicted_yaw_pre_rad,measured_yaw_rad,wrapped_innovation_rad,tilt_pre_deg,tilt_post_deg,tilt_deg,yaw_error_deg,"
           "accel_bias_x,accel_bias_y,accel_bias_z,gyro_bias_x,gyro_bias_y,gyro_bias_z,"
           "P_theta_ba_fro,P_theta_bg_fro,P_theta_bg_zz,gravity_updates_delta,gravity_updates_total,covariance_positive_definite\n";
}

void summary_header(std::ostream& out) {
    out << "input_sha256,aid_mode,measurement_source,expected_samples,valid_samples,availability,heading_events,heading_accepted,heading_rejected,"
           "tilt_rms_deg,tilt_max_deg,yaw_rms_deg,health_end,control_state_valid,covariance_positive_definite,"
           "accel_bias_x,accel_bias_y,accel_bias_z,gyro_bias_x,gyro_bias_y,gyro_bias_z\n";
}

void write_event(std::ostream& out, const std::string& input_sha, const Run& run,
                 const InputRecord& sample, std::uint32_t sample_index, float time_s,
                 const char* measurement_source, float measurement, const State& pre,
                 const double pre_theta_ba[3][3], const double pre_theta_bg[3][3],
                 const double post_theta_ba[3][3], const double post_theta_bg[3][3],
                 const float H[3][kDim], bool h_valid, double innovation_variance,
                 double nis, const double gain[kDim], const double dx[kDim], bool accepted,
                 double tilt_pre, double tilt_post) {
    const State& post = run.filter.state();
    out << input_sha << ',' << run.id << ',' << measurement_source << ',' << sample_index << ',' << time_s << ','
        << sample.timestamp_us << ",true," << (run.apply_heading ? "true" : "false") << ','
        << (accepted ? "true" : "false") << ',' << kHeadingSigmaRad << ',' << kHeadingNisGate << ','
        << measurement << ',' << pre.orientation.yaw() << ',';
    csv_float(out, h_valid ? H[0][0] * 0.0f + wrap_pi(measurement - pre.orientation.yaw()) : NAN);
    out << ',' << (h_valid ? "true" : "false") << ',';
    csv_double(out, innovation_variance); out << ','; csv_double(out, nis); out << ',';
    csv_float(out, run.apply_heading ? run.filter.last_nis() : NAN); out << ',';

    const double gain_blocks[] = {
        norm3(gain + 0), norm3(gain + 3), norm3(gain + 6), norm3(gain + 9), norm3(gain + 12),
    };
    for (double block : gain_blocks) { csv_double(out, block); out << ','; }
    const Quat qpre = pre.orientation, qpost = post.orientation;
    for (float q : {qpre.w, qpre.x, qpre.y, qpre.z, qpost.w, qpost.x, qpost.y, qpost.z}) {
        csv_float(out, q); out << ',';
    }
    csv_double(out, tilt_pre); out << ','; csv_double(out, tilt_post); out << ',';
    csv_double(out, tilt_post - tilt_pre); out << ',';
    for (float v : {pre.accel_bias.x, pre.accel_bias.y, pre.accel_bias.z,
                    post.accel_bias.x, post.accel_bias.y, post.accel_bias.z,
                    pre.gyro_bias.x, pre.gyro_bias.y, pre.gyro_bias.z,
                    post.gyro_bias.x, post.gyro_bias.y, post.gyro_bias.z}) {
        csv_float(out, v); out << ',';
    }
    for (int i = 0; i < kDim; ++i) { csv_float(out, H[0][i]); out << ','; }
    for (int i = 0; i < kDim; ++i) { csv_double(out, gain[i]); out << ','; }
    for (int i = 0; i < kDim; ++i) { csv_double(out, dx[i]); out << ','; }
    for (int i = 0; i < kDim; ++i) { csv_double(out, accepted ? dx[i] : 0.0); out << ','; }
    for (const auto* matrix : {pre_theta_ba, post_theta_ba, pre_theta_bg, post_theta_bg})
        for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) { csv_double(out, matrix[r][c]); out << ','; }
    const auto frobenius = [](const double p[3][3]) {
        double sum = 0.0;
        for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) sum += p[r][c] * p[r][c];
        return std::sqrt(sum);
    };
    csv_double(out, frobenius(pre_theta_ba)); out << ','; csv_double(out, frobenius(post_theta_ba)); out << ',';
    csv_double(out, frobenius(pre_theta_bg)); out << ','; csv_double(out, frobenius(post_theta_bg)); out << '\n';
}

void write_trace(std::ostream& out, const std::string& input_sha, const Run& run,
                 const InputRecord& sample, std::uint32_t sample_index, float time_s,
                 Quat truth, bool heading_event, const char* measurement_source,
                 float measurement, const State& pre, bool attempted, bool accepted,
                 double tilt_pre, double tilt_post, std::uint32_t gravity_delta,
                 std::uint32_t gravity_total) {
    const State& state = run.filter.state();
    out << input_sha << ',' << run.id << ',' << sample_index << ',' << time_s << ',' << sample.timestamp_us << ',';
    for (float v : {sample.accel.x, sample.accel.y, sample.accel.z,
                    sample.gyro.x, sample.gyro.y, sample.gyro.z}) { csv_float(out, v); out << ','; }
    out << (heading_event ? "true" : "false") << ',' << measurement_source << ','
        << (attempted ? "true" : "false") << ',' << (accepted ? "true" : "false") << ',';
    for (float q : {truth.w, truth.x, truth.y, truth.z,
                    pre.orientation.w, pre.orientation.x, pre.orientation.y, pre.orientation.z,
                    state.orientation.w, state.orientation.x, state.orientation.y, state.orientation.z}) {
        csv_float(out, q); out << ',';
    }
    csv_float(out, pre.orientation.yaw()); out << ','; csv_float(out, heading_event ? measurement : NAN); out << ',';
    csv_float(out, heading_event ? wrap_pi(measurement - pre.orientation.yaw()) : NAN); out << ',';
    csv_double(out, tilt_pre); out << ','; csv_double(out, tilt_post); out << ','; csv_double(out, tilt_post); out << ',';
    csv_float(out, wrap_pi(state.orientation.yaw() - truth.yaw()) * 180.0f / kPi); out << ',';
    for (float v : {state.accel_bias.x, state.accel_bias.y, state.accel_bias.z,
                    state.gyro_bias.x, state.gyro_bias.y, state.gyro_bias.z}) { csv_float(out, v); out << ','; }
    csv_double(out, crossblock_norm(run.filter, 6, 9)); out << ',';
    csv_double(out, crossblock_norm(run.filter, 6, 12)); out << ',';
    csv_double(out, run.filter.covariance(8, 14)); out << ',';
    out << gravity_delta << ',' << gravity_total << ',';
    out << (run.filter.covariance_positive_definite() ? "true" : "false") << '\n';
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::fprintf(stderr, "usage: pr3_heading_forensics INPUT_40BYTE_STREAM.bin OUTPUT_DIR INPUT_SHA256\n");
        return 2;
    }
    const std::string input_path = argv[1], output_dir = argv[2], input_sha = argv[3];
    if (input_sha.size() != 64 || input_sha.find_first_not_of("0123456789abcdef") != std::string::npos) {
        std::fputs("input SHA-256 must be 64 lowercase hexadecimal characters\n", stderr);
        return 2;
    }
    try {
        std::ifstream in(input_path, std::ios::binary);
        if (!in) throw std::runtime_error("cannot open input stream");
        in.seekg(0, std::ios::end);
        if (in.tellg() != static_cast<std::streamoff>(kExpectedSamples * 40u))
            throw std::runtime_error("selected input must contain exactly 2400 40-byte PR1 records");
        in.seekg(0, std::ios::beg);

        std::ofstream events(output_dir + "/heading_events_raw.csv", std::ios::trunc);
        std::ofstream trace(output_dir + "/heading_trace_raw.csv", std::ios::trunc);
        std::ofstream summary(output_dir + "/heading_replay_summary_raw.csv", std::ios::trunc);
        if (!events || !trace || !summary) throw std::runtime_error("cannot create diagnostic output files");
        events << std::fixed << std::setprecision(10);
        trace << std::fixed << std::setprecision(10);
        summary << std::fixed << std::setprecision(10);
        event_header(events); trace_header(trace); summary_header(summary);

        std::array<Run, 3> runs{{
            Run("no_heading_aid", "INDEPENDENT_COUNTERFACTUAL", false, false),
            Run("independent_noisy_heading", "INDEPENDENT_MEASUREMENT", true, false),
            Run("simulator_oracle_heading", "SIMULATOR_ORACLE", true, true),
        }};
        Quat truth{};
        std::uint32_t heading_events = 0;
        std::uint64_t previous_timestamp = 0;
        for (std::uint32_t n = 0; n < kExpectedSamples; ++n) {
            const InputRecord sample = read_record(in);
            const std::uint32_t index = n + 1;
            const std::uint64_t expected_timestamp = kEpochUs + static_cast<std::uint64_t>(index) * 5000u;
            if (sample.timestamp_us != expected_timestamp || (previous_timestamp && sample.timestamp_us <= previous_timestamp)
                || (sample.flags & ~1u) != 0 || !finite_vec(sample.accel) || !finite_vec(sample.gyro)
                || !std::isfinite(sample.independent_heading))
                throw std::runtime_error("input sample timestamp, flag, or value is invalid");
            const float time_s = static_cast<float>(index) * kDt;
            const bool heading_event = (sample.flags & 1u) != 0;
            const bool expected_event = time_s >= 2.0f && index % 200u == 0u;
            if (heading_event != expected_event)
                throw std::runtime_error("frozen heading event flag disagrees with 1 Hz protocol-v2 schedule");
            if (heading_event) ++heading_events;
            advance_truth_orientation(truth, time_s);

            for (Run& run : runs) {
                run.filter.set_external_stationary_confirmed(time_s < 2.0f);
                const std::uint32_t gravity_before = run.filter.gravity_applied_updates();
                // process() returns false while the filter is still gathering
                // its startup window; it is not an input-rejection signal.
                run.filter.process({sample.timestamp_us, sample.accel, sample.gyro});
                const State pre = run.filter.state();
                double pre_theta_ba[3][3]{}, pre_theta_bg[3][3]{};
                for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) {
                    pre_theta_ba[r][c] = run.filter.covariance(6 + r, 9 + c);
                    pre_theta_bg[r][c] = run.filter.covariance(6 + r, 12 + c);
                }
                float H[3][kDim]{};
                float residual[3]{};
                double S = std::numeric_limits<double>::quiet_NaN();
                double nis = std::numeric_limits<double>::quiet_NaN();
                double gain[kDim]{};
                double dx[kDim]{};
                bool h_valid = false;
                bool accepted = false;
                float measurement = sample.independent_heading;
                if (run.use_oracle) measurement = truth.yaw();
                const char* measurement_source = run.source;
                if (heading_event) {
                    h_valid = Eskf15::heading_measurement_model(pre.orientation, measurement, residual, H);
                    if (!h_valid) throw std::runtime_error("heading measurement model rejected a non-singular pure-roll event");
                    S = static_cast<double>(kHeadingSigmaRad) * kHeadingSigmaRad;
                    for (int i = 0; i < kDim; ++i) for (int j = 0; j < kDim; ++j)
                        S += static_cast<double>(H[0][i]) * run.filter.covariance(i, j) * H[0][j];
                    if (!(std::isfinite(S) && S > 1e-12)) throw std::runtime_error("computed heading innovation variance is invalid");
                    nis = static_cast<double>(residual[0]) * residual[0] / S;
                    for (int i = 0; i < kDim; ++i) {
                        for (int j = 0; j < kDim; ++j) gain[i] += run.filter.covariance(i, j) * H[0][j] / S;
                        dx[i] = gain[i] * residual[0];
                    }
                    if (run.apply_heading) {
                        accepted = run.filter.update_heading_at({sample.timestamp_us, kHeadingSource, 0}, measurement, kHeadingSigmaRad);
                        if (std::fabs(static_cast<double>(run.filter.last_nis()) - nis) > 2e-4 * std::max(1.0, nis))
                            throw std::runtime_error("independent analytic NIS disagrees with production update NIS");
                        if (accepted) ++run.accepted;
                        else ++run.rejected;
                        if (accepted && nis > kHeadingNisGate + 1e-5)
                            throw std::runtime_error("production accepted a heading update above its scalar NIS gate");
                    }
                    const double tilt_pre = projected_tilt_deg(pre.orientation, truth);
                    const double tilt_post = projected_tilt_deg(run.filter.state().orientation, truth);
                    double post_theta_ba[3][3]{}, post_theta_bg[3][3]{};
                    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) {
                        post_theta_ba[r][c] = run.filter.covariance(6 + r, 9 + c);
                        post_theta_bg[r][c] = run.filter.covariance(6 + r, 12 + c);
                    }
                    write_event(events, input_sha, run, sample, index, time_s, measurement_source,
                        measurement, pre, pre_theta_ba, pre_theta_bg, post_theta_ba, post_theta_bg,
                        H, h_valid, S, nis, gain, dx, accepted, tilt_pre, tilt_post);
                }

                if (time_s >= 2.0f) {
                    ++run.expected;
                    const bool valid = run.filter.control_state_valid();
                    const bool covariance_valid = run.filter.covariance_positive_definite();
                    run.all_covariances_valid = run.all_covariances_valid && covariance_valid;
                    if (valid && covariance_valid) {
                        const double tilt = projected_tilt_deg(run.filter.state().orientation, truth);
                        const double yaw = wrap_pi(run.filter.state().orientation.yaw() - truth.yaw());
                        ++run.valid;
                        run.tilt_sq += tilt * tilt;
                        run.yaw_sq += yaw * yaw;
                        run.max_tilt = std::max(run.max_tilt, tilt);
                    }
                    const double tilt_pre = heading_event ? projected_tilt_deg(pre.orientation, truth)
                        : projected_tilt_deg(run.filter.state().orientation, truth);
                    const double tilt_post = projected_tilt_deg(run.filter.state().orientation, truth);
                    const float trace_measurement = run.use_oracle ? truth.yaw() : sample.independent_heading;
                    write_trace(trace, input_sha, run, sample, index, time_s, truth,
                        heading_event, heading_event ? measurement_source : "NONE", trace_measurement,
                        pre, run.apply_heading && heading_event, accepted, tilt_pre, tilt_post,
                        run.filter.gravity_applied_updates() - gravity_before,
                        run.filter.gravity_applied_updates());
                }
            }
            previous_timestamp = sample.timestamp_us;
        }
        if (in.peek() != std::char_traits<char>::eof()) throw std::runtime_error("input has trailing bytes");
        if (heading_events != 11) throw std::runtime_error("expected exactly 11 frozen 1 Hz heading events");
        for (const Run& run : runs) {
            const State& state = run.filter.state();
            summary << input_sha << ',' << run.id << ',' << run.source << ',' << run.expected << ',' << run.valid << ',';
            csv_double(summary, run.expected ? static_cast<double>(run.valid) / run.expected : 0.0); summary << ',';
            summary << heading_events << ',' << run.accepted << ',' << run.rejected << ',';
            csv_double(summary, run.valid ? std::sqrt(run.tilt_sq / run.valid) : NAN); summary << ',';
            csv_double(summary, run.max_tilt); summary << ',';
            csv_double(summary, run.valid ? std::sqrt(run.yaw_sq / run.valid) * 180.0 / kPi : NAN); summary << ',';
            summary << (run.filter.health() == Health::Nominal ? "Nominal" :
                run.filter.health() == Health::Aligning ? "Aligning" :
                run.filter.health() == Health::Degraded ? "Degraded" : "Fault") << ','
                << (run.filter.control_state_valid() ? "true" : "false") << ','
                << (run.all_covariances_valid ? "true" : "false") << ',';
            for (float v : {state.accel_bias.x, state.accel_bias.y, state.accel_bias.z,
                            state.gyro_bias.x, state.gyro_bias.y, state.gyro_bias.z}) {
                csv_float(summary, v); summary << ',';
            }
            summary << '\n';
        }
        events.flush(); trace.flush(); summary.flush();
        if (!events || !trace || !summary) throw std::runtime_error("failed writing forensic traces");
        std::printf("PASS A5 replay: %u samples x %zu aid modes, %u heading events, input_sha256=%s\n",
            kExpectedSamples, runs.size(), heading_events, input_sha.c_str());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL A5 heading forensic replay: %s\n", error.what());
        return 1;
    }
    return 0;
}
