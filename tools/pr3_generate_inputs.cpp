// Generate one protocol-driven PR3 truth/IMU/aiding stream. Host-only.
#include "../eskf15.hpp"
#include "pr3_scenario_protocol.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <random>
#include <string>

namespace {
using inertial::Quat;
using inertial::Vec3;
constexpr std::size_t kHeaderBytes=128, kRecordBytes=128;

void write_u32(std::ostream& out,std::uint32_t value) {
    for(unsigned i=0;i<4;i++) out.put(static_cast<char>(value>>(8*i)));
}
void write_u64(std::ostream& out,std::uint64_t value) {
    for(unsigned i=0;i<8;i++) out.put(static_cast<char>(value>>(8*i)));
}
void write_f32(std::ostream& out,float value) {
    std::uint32_t bits=0;
    static_assert(sizeof(bits)==sizeof(value),"float32 required");
    std::memcpy(&bits,&value,sizeof(bits));
    write_u32(out,bits);
}
void write_header(std::ostream& out,int scenario,int rate_mode,bool stress,
                  std::uint32_t seed,std::uint32_t samples) {
    out.write("PR3INP02",8);
    for(std::uint32_t value:{2u,static_cast<std::uint32_t>(scenario),
            static_cast<std::uint32_t>(rate_mode),stress?1u:0u,seed,samples,
            static_cast<std::uint32_t>(kRecordBytes),samples,0u}) write_u32(out,value);
    out.write(pr3_protocol::kProtocolSha256,64);
    for(std::size_t i=8+9*4+64;i<kHeaderBytes;i++) out.put('\0');
}
void write_vec(std::ostream& out,Vec3 v) {write_f32(out,v.x);write_f32(out,v.y);write_f32(out,v.z);}
float normal(std::mt19937& rng,std::normal_distribution<float>& distribution) {return distribution(rng);}

bool in_seed_range(const std::string& split,std::uint32_t seed) {
    if(split=="development") return seed>=pr3_protocol::kDevelopmentFirstSeed && seed<=pr3_protocol::kDevelopmentLastSeed;
    if(split=="held_out") return seed>=pr3_protocol::kHeldOutFirstSeed && seed<=pr3_protocol::kHeldOutLastSeed;
    if(split=="final_confirmation") return seed>=pr3_protocol::kConfirmationFirstSeed && seed<=pr3_protocol::kConfirmationLastSeed;
    return false;
}

std::uint32_t fnv_byte(std::uint32_t state,std::uint8_t byte) {
    return (state^byte)*16777619u;
}
std::uint32_t fnv_text(std::uint32_t state,const char* text) {
    for(const unsigned char* p=reinterpret_cast<const unsigned char*>(text);*p;p++) state=fnv_byte(state,*p);
    return fnv_byte(state,0xffu);
}
std::uint32_t trial_rng_seed(std::uint32_t seed,const char* scenario,const char* rate,
                             const std::string& stress,const std::string& split,const char* stream) {
    std::uint32_t state=2166136261u;
    for(unsigned shift=0;shift<32;shift+=8) state=fnv_byte(state,static_cast<std::uint8_t>(seed>>shift));
    state=fnv_text(state,scenario);state=fnv_text(state,rate);state=fnv_text(state,stress.c_str());
    state=fnv_text(state,split.c_str());state=fnv_text(state,stream);
    return state;
}

int generate(const char* output,const std::string& split,const char* scenario_name,
             int rate_mode,bool stress,std::uint32_t seed) {
    using namespace pr3_protocol;
    const int scenario=scenario_index(scenario_name);
    if(scenario<0 || rate_mode<0 || rate_mode>=3 || !in_seed_range(split,seed)) {
        std::fprintf(stderr,"invalid scenario, rate mode, split, or seed\n"); return 2;
    }
    const int rate=kRateHz[rate_mode];
    const std::uint32_t count=static_cast<std::uint32_t>(rate*static_cast<int>(kDurationS));
    const double white_a=stress?kAccelNoiseStress:1.0;
    const double white_g=stress?kGyroNoiseStress:1.0;
    const double walk=stress?kBiasWalkStress:1.0;
    const double disturbance_scale=stress?kDisturbanceStress:1.0;
    const double timestamp_scale=stress?kTimestampStress:1.0;
    const float accel_sigma=static_cast<float>(kAccelDensity*white_a*std::sqrt(rate));
    const float gyro_sigma=static_cast<float>(kGyroDensity*white_g*std::sqrt(rate));
    const std::uint32_t sensor_seed=trial_rng_seed(seed,scenario_name,kRateIds[rate_mode],stress?"stress":"nominal",split,"imu");
    const std::uint32_t aid_seed=trial_rng_seed(seed,scenario_name,kRateIds[rate_mode],stress?"stress":"nominal",split,"independent_heading");
    std::mt19937 sensor_rng(sensor_seed);
    std::normal_distribution<float> sensor_normal(0.0f,1.0f);
    std::mt19937 aid_rng(aid_seed);
    std::normal_distribution<float> aid_normal(0.0f,static_cast<float>(kIndependentHeadingSigma));

    std::ofstream out(output,std::ios::binary|std::ios::trunc);
    if(!out) {std::fprintf(stderr,"cannot create output %s\n",output);return 2;}
    write_header(out,scenario,rate_mode,stress,seed,count);
    Quat q{};
    Vec3 position{},velocity{};
    Vec3 accel_bias{static_cast<float>(kAccelInitialBias[0]),static_cast<float>(kAccelInitialBias[1]),static_cast<float>(kAccelInitialBias[2])};
    Vec3 gyro_bias{static_cast<float>(kGyroInitialBias[0]),static_cast<float>(kGyroInitialBias[1]),static_cast<float>(kGyroInitialBias[2])};
    std::int64_t previous_physical_us=static_cast<std::int64_t>(kEpochUs);
    std::int64_t previous_reported_us=previous_physical_us;
    for(std::uint32_t i=1;i<=count;i++) {
        const std::int64_t nominal_us=nominal_timestamp_us(i,rate);
        const std::int64_t rate_offset=rate_jitter_us(rate_mode,i,timestamp_scale);
        const std::int64_t physical_us=nominal_us+rate_offset;
        const std::int64_t scenario_offset=scenario_jitter_us(scenario,i,rate,timestamp_scale);
        const std::int64_t reported_us=physical_us+scenario_offset;
        const std::int64_t dt_us=physical_us-previous_physical_us;
        const std::int64_t reported_dt=reported_us-previous_reported_us;
        if(dt_us<=0 || reported_dt<kMinimumInterSampleDtUs) {
            std::fprintf(stderr,"timestamp rule violated at sample %u (physical=%lld reported=%lld)\n",
                i,static_cast<long long>(dt_us),static_cast<long long>(reported_dt));return 3;
        }
        const double dt=static_cast<double>(dt_us)*1e-6;
        const double physical_t=static_cast<double>(physical_us-static_cast<std::int64_t>(kEpochUs))*1e-6;
        const double previous_t=static_cast<double>(previous_physical_us-static_cast<std::int64_t>(kEpochUs))*1e-6;
        const auto interval_motion=motion(scenario,(physical_t+previous_t)*0.5);
        const auto sample_motion=motion(scenario,physical_t);
        q=q*Quat::exp(Vec3{static_cast<float>(interval_motion.body_rate_rad_s.x),
            static_cast<float>(interval_motion.body_rate_rad_s.y),static_cast<float>(interval_motion.body_rate_rad_s.z)}*static_cast<float>(dt));
        q.normalize();
        const Vec3 acceleration{static_cast<float>(interval_motion.world_acceleration_m_s2.x),
            static_cast<float>(interval_motion.world_acceleration_m_s2.y),static_cast<float>(interval_motion.world_acceleration_m_s2.z)};
        position=position+velocity*static_cast<float>(dt)+acceleration*static_cast<float>(0.5*dt*dt);
        velocity=velocity+acceleration*static_cast<float>(dt);

        const float accel_walk_step=static_cast<float>(kAccelWalk*walk*std::sqrt(dt));
        const float gyro_walk_step=static_cast<float>(kGyroWalk*walk*std::sqrt(dt));
        accel_bias=accel_bias+Vec3{normal(sensor_rng,sensor_normal)*accel_walk_step,
            normal(sensor_rng,sensor_normal)*accel_walk_step,normal(sensor_rng,sensor_normal)*accel_walk_step};
        gyro_bias=gyro_bias+Vec3{normal(sensor_rng,sensor_normal)*gyro_walk_step,
            normal(sensor_rng,sensor_normal)*gyro_walk_step,normal(sensor_rng,sensor_normal)*gyro_walk_step};
        const Vec3 truth_acceleration{static_cast<float>(sample_motion.world_acceleration_m_s2.x),
            static_cast<float>(sample_motion.world_acceleration_m_s2.y),static_cast<float>(sample_motion.world_acceleration_m_s2.z)};
        Vec3 accel=q.unrotate(truth_acceleration+Vec3{0,0,inertial::kGravity})+accel_bias;
        Vec3 gyro{static_cast<float>(sample_motion.body_rate_rad_s.x),static_cast<float>(sample_motion.body_rate_rad_s.y),static_cast<float>(sample_motion.body_rate_rad_s.z)};
        gyro=gyro+gyro_bias;
        for(int axis=0;axis<3;axis++) {
            float* a=axis==0?&accel.x:(axis==1?&accel.y:&accel.z);
            float* g=axis==0?&gyro.x:(axis==1?&gyro.y:&gyro.z);
            *a+=normal(sensor_rng,sensor_normal)*accel_sigma+static_cast<float>(disturbance(scenario,axis,false,physical_t,disturbance_scale));
            *g+=normal(sensor_rng,sensor_normal)*gyro_sigma+static_cast<float>(disturbance(scenario,axis,true,physical_t,disturbance_scale));
        }
        const bool heading=(physical_t>=2.0 && i%static_cast<std::uint32_t>(rate)==0);
        const float oracle_yaw=q.yaw();
        const float independent_yaw=heading?inertial::wrap_pi(oracle_yaw+normal(aid_rng,aid_normal)):0.0f;
        write_u32(out,i);
        write_u64(out,static_cast<std::uint64_t>(nominal_us));
        write_u64(out,static_cast<std::uint64_t>(reported_us));
        write_u64(out,static_cast<std::uint64_t>(physical_us));
        write_f32(out,q.w);write_f32(out,q.x);write_f32(out,q.y);write_f32(out,q.z);
        write_vec(out,position);write_vec(out,velocity);write_vec(out,accel_bias);write_vec(out,gyro_bias);
        write_vec(out,accel);write_vec(out,gyro);
        write_f32(out,independent_yaw);write_f32(out,oracle_yaw);write_u32(out,heading?1u:0u);
        previous_physical_us=physical_us;previous_reported_us=reported_us;
    }
    out.flush();
    if(!out) {std::fprintf(stderr,"failed writing output stream\n");return 4;}
    std::printf("PASS generated %s scenario=%s rate=%s stress=%s split=%s seed=%u samples=%u record_bytes=%zu protocol_sha256=%s\n",
        output,scenario_name,kRateIds[rate_mode],stress?"stress":"nominal",split.c_str(),seed,count,kRecordBytes,kProtocolSha256);
    return 0;
}
} // namespace

int main(int argc,char**argv) {
    if(argc!=7) {
        std::fprintf(stderr,"usage: pr3_generate_inputs OUTPUT SPLIT SCENARIO RATE_MODE_INDEX nominal|stress SEED\n");
        return 2;
    }
    char* end=nullptr;
    const long rate=std::strtol(argv[4],&end,10);
    if(!end || *end || rate<0 || rate>2) return 2;
    const std::string stress=argv[5];
    if(stress!="nominal" && stress!="stress") return 2;
    end=nullptr;
    const unsigned long seed=std::strtoul(argv[6],&end,10);
    if(!end || *end || seed>0xfffffffful) return 2;
    return generate(argv[1],argv[2],argv[3],static_cast<int>(rate),stress=="stress",static_cast<std::uint32_t>(seed));
}
