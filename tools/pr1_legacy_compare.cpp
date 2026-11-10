// Replay protocol-v2 sample streams through the pre-Bundle-B default ESKF.
#include "legacy_eskf15.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace inertial;
namespace {
constexpr uint64_t kEpochUs = 1000000;
constexpr float kAccel = 0.2f * kGravity;
constexpr float kRateToDeg = 180.0f / kPi;

uint32_t read_u32(std::istream& in) {
    uint32_t value = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) {
        const int byte = in.get();
        if (byte == EOF) throw std::runtime_error("short binary stream");
        value |= static_cast<uint32_t>(static_cast<uint8_t>(byte)) << shift;
    }
    return value;
}
uint64_t read_u64(std::istream& in) {
    uint64_t value = 0;
    for (unsigned shift = 0; shift < 64; shift += 8) {
        const int byte = in.get();
        if (byte == EOF) throw std::runtime_error("short binary stream");
        value |= static_cast<uint64_t>(static_cast<uint8_t>(byte)) << shift;
    }
    return value;
}
float read_f32(std::istream& in) {
    const uint32_t bits = read_u32(in);
    float value = 0.0f;
    static_assert(sizeof(bits) == sizeof(value), "float32 required");
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}
const char* health_name(Health h) {
    switch (h) {
    case Health::Aligning: return "Aligning";
    case Health::Nominal: return "Nominal";
    case Health::Degraded: return "Degraded";
    case Health::Fault: return "Fault";
    }
    return "unknown";
}
float tilt_error_deg(Quat estimate, Quat truth) {
    const Vec3 g_est = estimate.unrotate({0.0f, 0.0f, 1.0f});
    const Vec3 g_truth = truth.unrotate({0.0f, 0.0f, 1.0f});
    return std::acos(std::max(-1.0f, std::min(1.0f, dot(g_est, g_truth)))) * kRateToDeg;
}
float percentile(std::vector<float> values, float p) {
    if (values.empty()) return std::numeric_limits<float>::quiet_NaN();
    std::sort(values.begin(), values.end());
    return values[static_cast<size_t>(p * static_cast<float>(values.size() - 1))];
}
struct Trial {
    std::string id, scenario, noise, split;
    unsigned seed = 0;
    uint64_t offset = 0;
    uint32_t records = 0, record_bytes = 0;
};
std::vector<Trial> read_index(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open sample index");
    std::string line;
    std::getline(in, line); // header
    std::vector<Trial> trials;
    while (std::getline(in, line)) {
        std::stringstream row(line);
        Trial t;
        std::string seed, offset, records, record_bytes;
        std::getline(row, t.id, ',');
        std::getline(row, t.scenario, ',');
        std::getline(row, t.noise, ',');
        std::getline(row, t.split, ',');
        std::getline(row, seed, ',');
        std::getline(row, offset, ',');
        std::getline(row, records, ',');
        std::getline(row, record_bytes, ',');
        if (t.id.empty()) continue;
        t.seed = static_cast<unsigned>(std::stoul(seed));
        t.offset = std::stoull(offset);
        t.records = static_cast<uint32_t>(std::stoul(records));
        t.record_bytes = static_cast<uint32_t>(std::stoul(record_bytes));
        trials.push_back(t);
    }
    return trials;
}
Quat truth_orientation(const Trial& t, float seconds) {
    if (t.scenario == "pure_roll") {
        const float duration = std::max(0.0f, std::min(6.0f, seconds - 2.0f));
        return Quat::exp({0.18f * duration, 0.0f, 0.0f});
    }
    return {};
}
Vec3 truth_position(const Trial& t, float seconds) {
    if (t.scenario != "lateral_accel_0p2g") return {};
    const float duration = std::max(0.0f, std::min(6.0f, seconds - 2.0f));
    const float coast = std::max(0.0f, seconds - 8.0f);
    return {0.5f * kAccel * duration * duration + kAccel * duration * coast, 0.0f, 0.0f};
}
bool selected(const Trial& t) {
    if (t.scenario == "lateral_accel_0p2g")
        return t.noise == "clean" && t.split == "reference" && t.seed == 0;
    if (t.scenario != "pure_roll") return false;
    if (t.noise != "accel_only" && t.noise != "gyro_only" && t.noise != "combined") return false;
    return (t.split == "development" && t.seed >= 101 && t.seed <= 116)
        || (t.split == "held_out" && t.seed >= 1001 && t.seed <= 1016);
}

void replay(const Trial& trial, std::ifstream& samples, std::ostream& out) {
    if (trial.record_bytes != 40) throw std::runtime_error("unexpected sample record size");
    samples.clear();
    samples.seekg(static_cast<std::streamoff>(trial.offset));
    Eskf15 filter; // defaults from the historical source revision
    std::vector<float> tilt, yaw_abs, position;
    double tilt_sq = 0.0, yaw_sq = 0.0, position_sq = 0.0;
    uint32_t expected = 0, valid = 0;
    float final_position_error = std::numeric_limits<float>::quiet_NaN();
    float final_gyro_bias_norm = std::numeric_limits<float>::quiet_NaN();
    bool propagated = false;
    for (uint32_t i = 0; i < trial.records; ++i) {
        const uint64_t timestamp = read_u64(samples);
        const Vec3 accel{read_f32(samples), read_f32(samples), read_f32(samples)};
        const Vec3 gyro{read_f32(samples), read_f32(samples), read_f32(samples)};
        (void)read_f32(samples); // independent heading stream is not sent to IMU_ONLY
        (void)read_u32(samples); // heading-present flag
        const Imu sample{timestamp, accel, gyro};
        propagated = filter.process(sample);
        const float t = static_cast<float>(timestamp - kEpochUs) * 1e-6f;
        if (t < 2.0f) continue;
        ++expected;
        if (!propagated || !filter.ready() || filter.health() == Health::Fault) continue;
        ++valid;
        const Quat truth_q = truth_orientation(trial, t);
        const Vec3 truth_p = truth_position(trial, t);
        const float tilt_deg = tilt_error_deg(filter.state().orientation, truth_q);
        const float yaw_deg = wrap_pi(filter.state().orientation.yaw() - truth_q.yaw()) * kRateToDeg;
        const float p_err = (filter.state().position - truth_p).norm();
        tilt.push_back(tilt_deg);
        yaw_abs.push_back(std::fabs(yaw_deg));
        position.push_back(p_err);
        tilt_sq += static_cast<double>(tilt_deg) * tilt_deg;
        yaw_sq += static_cast<double>(yaw_deg) * yaw_deg;
        position_sq += static_cast<double>(p_err) * p_err;
        final_position_error = p_err;
        final_gyro_bias_norm = filter.state().gyro_bias.norm();
    }
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const float tilt_rms = valid ? static_cast<float>(std::sqrt(tilt_sq / valid)) : static_cast<float>(nan);
    const float yaw_rms = valid ? static_cast<float>(std::sqrt(yaw_sq / valid)) : static_cast<float>(nan);
    const float position_rms = valid ? static_cast<float>(std::sqrt(position_sq / valid)) : static_cast<float>(nan);
    const float tilt_max = tilt.empty() ? static_cast<float>(nan) : *std::max_element(tilt.begin(), tilt.end());
    const float yaw_max = yaw_abs.empty() ? static_cast<float>(nan) : *std::max_element(yaw_abs.begin(), yaw_abs.end());
    out << "e90c80eb47e5002738f4a16450714b3149798e28," << trial.scenario << ',' << trial.noise << ','
        << trial.split << ',' << trial.seed << ",IMU_ONLY,UNKNOWN,OFF,NONE," << expected << ',' << valid << ','
        << tilt_rms << ',' << percentile(tilt, 0.95f) << ',' << tilt_max << ',' << yaw_rms << ','
        << percentile(yaw_abs, 0.95f) << ',' << yaw_max << ',' << position_rms << ','
        << percentile(position, 0.95f) << ',' << final_position_error << ',' << final_gyro_bias_norm
        << ',' << health_name(filter.health()) << '\n';
}
} // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::fprintf(stderr, "Usage: pr1_legacy_compare SAMPLE_STREAM SAMPLE_INDEX OUTPUT_CSV\n");
        return 2;
    }
    try {
        const std::vector<Trial> trials = read_index(argv[2]);
        std::ifstream sample_file(argv[1], std::ios::binary);
        if (!sample_file) throw std::runtime_error("cannot open sample stream");
        std::ofstream out(argv[3]);
        if (!out) throw std::runtime_error("cannot open output CSV");
        out << "legacy_core_commit,scenario,noise_mode,seed_split,seed,input_mode,startup_knowledge,startup_calibration,runtime_aid,expected,valid,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,yaw_rms_deg,yaw_abs_p95_deg,yaw_abs_max_deg,position_rms_m,position_p95_m,position_error_end_m,gyro_bias_norm_end_rad_s,health_end\n";
        out.precision(9);
        for (const Trial& trial : trials) if (selected(trial)) replay(trial, sample_file, out);
        std::printf("Wrote historical-default replay for pre-Bundle-B core e90c80e; %zu selected sample streams\n",
            static_cast<size_t>(1 + 3 * 32));
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Legacy replay failed: %s\n", error.what());
        return 1;
    }
    return 0;
}
