// Failure-aware paired evaluator for a single frozen PR3 input stream.
#include "../eskf15.hpp"
#include "pr3_scenario_protocol.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace {
using namespace inertial;
constexpr std::size_t kHeaderBytes=128,kRecordBytes=128;
constexpr std::uint32_t kHeadingSource=0x48454144u;
struct InputRecord {
    std::uint32_t index=0;
    std::uint64_t nominal_us=0,reported_us=0,physical_us=0;
    Quat truth_q{};
    Vec3 truth_p{},truth_v{},truth_ba{},truth_bg{},accel{},gyro{};
    float independent_heading=0,oracle_heading=0;
    std::uint32_t flags=0;
};
struct TrialMetrics {
    std::uint32_t expected=0,produced=0,valid=0,control_valid=0,stale=0,covariance_valid=0;
    std::uint32_t faults=0,resets=0,rejected=0,aid_accepted=0,aid_rejected=0;
    std::uint32_t nis_count=0,nees_count=0,nees_95=0;
    double nis_sum=0,nees_sum=0;
    double tilt_sq=0,attitude_sq=0,yaw_sq=0,position_sq=0,velocity_sq=0;
    float accel_bias_error=NAN,gyro_bias_error=NAN;
    float recovery_time_s=NAN;
    bool outage_open=false;
    double outage_start_s=NAN;
    std::uint64_t max_state_age_us=0;
    std::vector<float> tilt,attitude,yaw_abs,position,velocity;
};
struct Run {
    explicit Run(GravityPolicy value):policy(value),filter(Settings{}){}
    GravityPolicy policy;
    Eskf15 filter;
    TrialMetrics metrics{};
    bool first_covariance_failure_written=false;
};

void read_u32(std::istream& in,std::uint32_t& value) {
    value=0;for(unsigned i=0;i<4;i++){const int c=in.get();if(c<0)throw 1;value|=std::uint32_t(static_cast<unsigned char>(c))<<(8*i);}
}
void read_u64(std::istream& in,std::uint64_t& value) {
    value=0;for(unsigned i=0;i<8;i++){const int c=in.get();if(c<0)throw 1;value|=std::uint64_t(static_cast<unsigned char>(c))<<(8*i);}
}
float read_f32(std::istream& in) {
    std::uint32_t bits=0;read_u32(in,bits);float value=0;std::memcpy(&value,&bits,sizeof(value));return value;
}
Vec3 read_vec(std::istream& in) {return {read_f32(in),read_f32(in),read_f32(in)};}
InputRecord read_record(std::istream& in) {
    InputRecord r{};read_u32(in,r.index);read_u64(in,r.nominal_us);read_u64(in,r.reported_us);read_u64(in,r.physical_us);
    r.truth_q={read_f32(in),read_f32(in),read_f32(in),read_f32(in)};
    r.truth_p=read_vec(in);r.truth_v=read_vec(in);r.truth_ba=read_vec(in);r.truth_bg=read_vec(in);
    r.accel=read_vec(in);r.gyro=read_vec(in);r.independent_heading=read_f32(in);r.oracle_heading=read_f32(in);read_u32(in,r.flags);
    return r;
}
bool finite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
bool finite(Quat q) {return std::isfinite(q.w)&&std::isfinite(q.x)&&std::isfinite(q.y)&&std::isfinite(q.z);}
bool hex_digest(const char* value,std::size_t length) {
    if(std::strlen(value)!=length)return false;
    for(std::size_t i=0;i<length;i++)if(!((value[i]>='0'&&value[i]<='9')||(value[i]>='a'&&value[i]<='f')||(value[i]>='A'&&value[i]<='F')))return false;
    return true;
}
float tilt_error_deg(Quat estimate,Quat truth) {
    const Vec3 a=estimate.unrotate({0,0,1}),b=truth.unrotate({0,0,1});
    return std::acos(std::max(-1.0f,std::min(1.0f,dot(a,b))))*180.0f/kPi;
}
float attitude_error_deg(Quat estimate,Quat truth) {
    Quat e=estimate*Quat{truth.w,-truth.x,-truth.y,-truth.z};e.normalize();
    if(e.w<0)e={-e.w,-e.x,-e.y,-e.z};
    return 2.0f*std::atan2(std::sqrt(e.x*e.x+e.y*e.y+e.z*e.z),e.w)*180.0f/kPi;
}
double tilt_nees(const Eskf15& filter,Quat truth) {
    const Quat qe=filter.state().orientation;
    Quat e=Quat{qe.w,-qe.x,-qe.y,-qe.z}*truth;e.normalize();
    if(e.w<0)e={-e.w,-e.x,-e.y,-e.z};
    const float n=std::sqrt(e.x*e.x+e.y*e.y+e.z*e.z);
    const float angle=2.0f*std::atan2(n,e.w);
    const Vec3 local=n>1e-10f?Vec3{e.x,e.y,e.z}*(angle/n):Vec3{};
    const Vec3 world=qe.rotate(local);
    const Vec3 bx=qe.unrotate({1,0,0}),by=qe.unrotate({0,1,0});
    const float U[2][3]={{bx.x,bx.y,bx.z},{by.x,by.y,by.z}};
    double c00=0,c01=0,c11=0;
    for(int a=0;a<3;a++)for(int b=0;b<3;b++) {
        const double p=filter.covariance(6+a,6+b);
        c00+=U[0][a]*p*U[0][b];c01+=U[0][a]*p*U[1][b];c11+=U[1][a]*p*U[1][b];
    }
    const double determinant=c00*c11-c01*c01;
    if(!(determinant>1e-16) || !std::isfinite(determinant)) return NAN;
    const double value=(c11*world.x*world.x+c00*world.y*world.y-2*c01*world.x*world.y)/determinant;
    return std::isfinite(value)?value:NAN;
}
float percentile(std::vector<float> values,float p) {
    if(values.empty())return NAN;
    std::sort(values.begin(),values.end());
    return values[static_cast<std::size_t>(p*static_cast<float>(values.size()-1))];
}
float rms(double sum,std::uint32_t n) {return n?static_cast<float>(std::sqrt(sum/n)):NAN;}
void csv_float(std::ostream& out,float x) {if(std::isfinite(x))out<<x;}
const char* policy_name(GravityPolicy p) {
    switch(p){case GravityPolicy::Conservative:return "eskf_conservative";case GravityPolicy::LegacyHeuristic:return "eskf_legacy";case GravityPolicy::ConfirmedOnly:return "eskf_confirmed_only";}
    return "unknown";
}
const char* health_name(Health h) {
    switch(h){case Health::Aligning:return "Aligning";case Health::Nominal:return "Nominal";case Health::Degraded:return "Degraded";case Health::Fault:return "Fault";}
    return "Unknown";
}
bool cholesky_failure(const Eskf15& filter,int& failed_pivot,float& pivot_value) {
    float L[kDim][kDim]={};
    for(int i=0;i<kDim;i++) for(int j=0;j<=i;j++) {
        float value=filter.covariance(i,j);
        for(int k=0;k<j;k++) value-=L[i][k]*L[j][k];
        if(i==j) {
            if(!std::isfinite(value)||value<=1e-12f) {
                failed_pivot=i;pivot_value=value;return true;
            }
            L[i][j]=std::sqrt(value);
        } else L[i][j]=value/L[j][j];
    }
    failed_pivot=-1;pivot_value=NAN;return false;
}
void write_covariance_header(std::ostream& out) {
    out<<"estimator,sample_index,stage,failed_pivot,pivot_value";
    for(int i=0;i<kDim;i++)for(int j=0;j<kDim;j++)out<<",P_"<<i<<'_'<<j;
    out<<'\n';
}
void copy_covariance(const Eskf15& filter,float* covariance) {
    for(int i=0;i<kDim;i++)for(int j=0;j<kDim;j++)covariance[i*kDim+j]=filter.covariance(i,j);
}
void write_covariance_values(std::ostream& out,const Run& run,const InputRecord& sample,
                             const char* stage,const float* covariance,int failed_pivot,float pivot_value) {
    out<<policy_name(run.policy)<<','<<sample.index<<','<<stage<<','<<failed_pivot<<',';
    csv_float(out,pivot_value);
    for(int i=0;i<kDim;i++)for(int j=0;j<kDim;j++) {out<<',';csv_float(out,covariance[i*kDim+j]);}
    out<<'\n';
}
void write_covariance_snapshot(std::ostream& out,const Run& run,const InputRecord& sample,
                               const char* stage,const Eskf15& filter) {
    float covariance[kDim*kDim];
    copy_covariance(filter,covariance);
    int failed_pivot=-1;float pivot_value=NAN;
    cholesky_failure(filter,failed_pivot,pivot_value);
    write_covariance_values(out,run,sample,stage,covariance,failed_pivot,pivot_value);
}
void write_sample_trace(std::ostream& out,const InputRecord& sample,int rate,const Run& run,
                        bool evaluation_sample,bool propagated,bool heading_available,
                        bool heading_attempted,bool heading_accepted,std::uint32_t gravity_delta,
                        std::uint32_t rejected_delta,float nis_after_process,float nis_after_heading,
                        Health health_before,Health health_after_process,bool covariance_before,
                        bool covariance_after_process,bool covariance_after_heading,
                        int process_failed_pivot,float process_failed_pivot_value,
                        int heading_failed_pivot,float heading_failed_pivot_value) {
    const State& state=run.filter.state();
    out<<sample.index<<','<<static_cast<double>(sample.index)/rate<<','<<sample.reported_us<<','<<sample.physical_us<<','
       <<policy_name(run.policy)<<','<<(evaluation_sample?"true":"false")<<','<<(propagated?"true":"false")<<','
       <<(heading_available?"true":"false")<<','<<(heading_attempted?"true":"false")<<','<<(heading_accepted?"true":"false")<<','
       <<gravity_delta<<','<<rejected_delta<<',';
    csv_float(out,nis_after_process);out<<',';csv_float(out,nis_after_heading);out<<','
       <<health_name(health_before)<<','<<health_name(health_after_process)<<','<<health_name(run.filter.health())<<','
       <<(covariance_before?"true":"false")<<','<<(covariance_after_process?"true":"false")<<','
       <<(covariance_after_heading?"true":"false")<<','<<process_failed_pivot<<',';
    csv_float(out,process_failed_pivot_value);out<<','<<heading_failed_pivot<<',';
    csv_float(out,heading_failed_pivot_value);out<<','<<(run.filter.control_state_valid()?"true":"false")<<',';
    const float state_values[]={state.position.x,state.position.y,state.position.z,state.velocity.x,state.velocity.y,state.velocity.z,
        state.orientation.w,state.orientation.x,state.orientation.y,state.orientation.z,
        state.accel_bias.x,state.accel_bias.y,state.accel_bias.z,state.gyro_bias.x,state.gyro_bias.y,state.gyro_bias.z};
    for(float value:state_values){csv_float(out,value);out<<',';}
    for(int i=0;i<3;i++)for(int j=0;j<3;j++){csv_float(out,run.filter.covariance(6+i,6+j));out<<',';}
    for(int i=0;i<3;i++)for(int j=0;j<3;j++){csv_float(out,run.filter.covariance(6+i,9+j));if(i!=2||j!=2)out<<',';}
    out<<'\n';
}

int evaluate(const char* input,const char* output,const char* split,const char* sensor_input,
             const char* startup,bool startup_calibration,const char* aid,const char* commit_sha,
             const char* config_sha,const char* input_sha,const char* sample_trace_path) {
    using namespace pr3_protocol;
    if(std::strcmp(sensor_input,"IMU_ONLY")!=0 && std::strcmp(sensor_input,"IMU_WITH_SYNTHETIC_HEADING")!=0) return 2;
    if(std::strcmp(startup,"UNKNOWN")!=0 && std::strcmp(startup,"EXTERNALLY_VERIFIED_STATIC")!=0 && std::strcmp(startup,"TRUTH_ORACLE_STATIC")!=0) return 2;
    if(std::strcmp(aid,"NONE")!=0 && std::strcmp(aid,"INDEPENDENT_MEASUREMENT")!=0 && std::strcmp(aid,"SIMULATOR_ORACLE")!=0) return 2;
    if(std::strcmp(sensor_input,"IMU_ONLY")==0 && std::strcmp(aid,"NONE")!=0) {std::fputs("IMU_ONLY cannot provide runtime heading aid\n",stderr);return 2;}
    if(std::strcmp(startup,"UNKNOWN")==0 && startup_calibration) {std::fputs("startup calibration requires declared static knowledge\n",stderr);return 2;}
    if(std::strcmp(sensor_input,"IMU_WITH_SYNTHETIC_HEADING")!=0 && std::strcmp(aid,"NONE")!=0) return 2;
    if(!hex_digest(commit_sha,40)||!hex_digest(config_sha,64)||!hex_digest(input_sha,64)) {std::fputs("commit/config/input provenance digests must be valid hexadecimal SHA values\n",stderr);return 2;}

    std::ifstream in(input,std::ios::binary);
    if(!in) {std::fprintf(stderr,"cannot open input %s\n",input);return 2;}
    char magic[8]{};in.read(magic,8);
    if(in.gcount()!=8 || std::memcmp(magic,"PR3INP03",8)!=0) {std::fputs("bad PR3 input magic\n",stderr);return 3;}
    std::array<std::uint32_t,9> h{};
    try {for(auto& x:h)read_u32(in,x);}catch(...){std::fputs("truncated PR3 header\n",stderr);return 3;}
    char protocol_sha[64]{};in.read(protocol_sha,64);
    if(in.gcount()!=64 || std::string(protocol_sha,64)!=kProtocolSha256 || h[0]!=3 || h[1]>=kScenarioCount || h[2]>=3 || h[3]>1 || h[6]!=kRecordBytes || h[5]!=h[7]) {
        std::fputs("invalid PR3 input header or protocol SHA\n",stderr);return 3;
    }
    in.ignore(static_cast<std::streamsize>(kHeaderBytes-108));
    const int scenario=static_cast<int>(h[1]),rate_mode=static_cast<int>(h[2]);
    const int rate=kRateHz[rate_mode];
    const std::uint32_t seed=h[4],count=h[5];
    const bool stress=h[3]!=0;
    const std::string split_name=split;
    const bool seed_ok=(split_name=="development"&&seed>=kDevelopmentFirstSeed&&seed<=kDevelopmentLastSeed)
        ||(split_name=="held_out"&&seed>=kHeldOutFirstSeed&&seed<=kHeldOutLastSeed)
        ||(split_name=="final_confirmation"&&seed>=kConfirmationFirstSeed&&seed<=kConfirmationLastSeed);
    if(!seed_ok) {std::fputs("input seed is outside the declared split\n",stderr);return 3;}
    if(count!=static_cast<std::uint32_t>(rate*static_cast<int>(kDurationS))) {std::fputs("sample count mismatches duration/rate\n",stderr);return 3;}
    std::array<Run,3> runs{{Run(GravityPolicy::Conservative),Run(GravityPolicy::LegacyHeuristic),Run(GravityPolicy::ConfirmedOnly)}};
    for(Run& run:runs) {
        Settings cfg{};cfg.accel_noise=static_cast<float>(kAccelDensity);cfg.gyro_noise=static_cast<float>(kGyroDensity);
        cfg.accel_bias_walk=static_cast<float>(kAccelWalk);cfg.gyro_bias_walk=static_cast<float>(kGyroWalk);
        cfg.gravity_policy=run.policy;cfg.startup_gyro_bias_calibration=startup_calibration;
        cfg.expected_period_us=static_cast<std::uint32_t>(1000000/rate);
        run.filter=Eskf15(cfg);
    }
    std::ofstream out(output,std::ios::trunc);
    if(!out) {std::fprintf(stderr,"cannot create summary %s\n",output);return 2;}
    std::ofstream sample_trace,covariance_trace;
    if(sample_trace_path && *sample_trace_path) {
        sample_trace.open(sample_trace_path,std::ios::trunc);
        if(!sample_trace) {std::fprintf(stderr,"cannot create sample trace %s\n",sample_trace_path);return 2;}
        sample_trace.setf(std::ios::fixed);sample_trace.precision(8);
        sample_trace<<"sample_index,nominal_time_s,reported_timestamp_us,physical_timestamp_us,estimator,evaluation_sample,process_propagated,heading_available,heading_attempted,heading_accepted,gravity_updates_delta,rejected_updates_delta,nis_after_process,nis_after_heading,health_before,health_after_process,health_after_heading,covariance_before,covariance_after_process,covariance_after_heading,process_failed_pivot,process_failed_pivot_value,heading_failed_pivot,heading_failed_pivot_value,control_valid,position_x,position_y,position_z,velocity_x,velocity_y,velocity_z,orientation_w,orientation_x,orientation_y,orientation_z,accel_bias_x,accel_bias_y,accel_bias_z,gyro_bias_x,gyro_bias_y,gyro_bias_z,cov_theta_00,cov_theta_01,cov_theta_02,cov_theta_10,cov_theta_11,cov_theta_12,cov_theta_20,cov_theta_21,cov_theta_22,cov_theta_ba_00,cov_theta_ba_01,cov_theta_ba_02,cov_theta_ba_10,cov_theta_ba_11,cov_theta_ba_12,cov_theta_ba_20,cov_theta_ba_21,cov_theta_ba_22\n";
        const std::string covariance_path=std::string(sample_trace_path)+".first_failure_covariance.csv";
        covariance_trace.open(covariance_path,std::ios::trunc);
        if(!covariance_trace) {std::fprintf(stderr,"cannot create first-failure covariance trace %s\n",covariance_path.c_str());return 2;}
        covariance_trace.setf(std::ios::fixed);covariance_trace.precision(8);
        write_covariance_header(covariance_trace);
    }
    std::uint64_t previous_reported=0,previous_physical=0;
    for(std::uint32_t n=0;n<count;n++) {
        InputRecord s{};
        try{s=read_record(in);}catch(...){std::fputs("truncated PR3 input record\n",stderr);return 3;}
        const double qnorm=static_cast<double>(s.truth_q.w)*s.truth_q.w+static_cast<double>(s.truth_q.x)*s.truth_q.x+static_cast<double>(s.truth_q.y)*s.truth_q.y+static_cast<double>(s.truth_q.z)*s.truth_q.z;
        const std::uint64_t expected_nominal=static_cast<std::uint64_t>(nominal_timestamp_us(s.index,rate));
        if(s.index!=n+1 || s.nominal_us!=expected_nominal || !finite(s.truth_q)||!finite(s.truth_p)||!finite(s.truth_v)||!finite(s.truth_ba)||!finite(s.truth_bg)||!finite(s.accel)||!finite(s.gyro) || !std::isfinite(s.independent_heading)||!std::isfinite(s.oracle_heading) || std::fabs(qnorm-1.0)>1e-3 || (s.flags&~1u) || (previous_reported && (s.reported_us<=previous_reported || s.reported_us-previous_reported<static_cast<std::uint64_t>(kMinimumInterSampleDtUs))) || (previous_physical && s.physical_us<=previous_physical)) {
            std::fputs("invalid, nonfinite, reordered or nonmonotonic PR3 input record\n",stderr);return 3;
        }
        const double nominal_t=static_cast<double>(s.index)/rate;
        const bool in_eval=nominal_t>=2.0 && nominal_t<=kDurationS;
        const double physical_t=static_cast<double>(s.physical_us-kEpochUs)*1e-6;
        for(unsigned r=0;r<runs.size();r++) {
            Run& run=runs[r];
            const bool trace_enabled=sample_trace.is_open();
            const bool static_knowledge=std::strcmp(startup,"UNKNOWN")!=0;
            run.filter.set_external_stationary_confirmed(static_knowledge && physical_t<2.0);
            std::array<float,kDim*kDim> covariance_before_values{};
            if(trace_enabled) copy_covariance(run.filter,covariance_before_values.data());
            const bool covariance_before=!trace_enabled || run.filter.covariance_positive_definite();
            const Health health_before=run.filter.health();
            const auto gravity_before=run.filter.gravity_applied_updates();
            const auto aid_before=run.filter.accepted_updates();
            const auto rejected_before=run.filter.rejected_updates();
            const auto fault_before=run.filter.health()==Health::Fault;
            const auto reset_before=run.filter.reset_required();
            const Imu imu{s.reported_us,s.accel,s.gyro};
            const bool propagated=run.filter.process(imu);
            int process_failed_pivot=-1;float process_failed_pivot_value=NAN;
            const bool covariance_after_process=!trace_enabled ||
                !cholesky_failure(run.filter,process_failed_pivot,process_failed_pivot_value);
            std::array<float,kDim*kDim> covariance_after_process_values{};
            if(trace_enabled) copy_covariance(run.filter,covariance_after_process_values.data());
            const Health health_after_process=run.filter.health();
            const float nis_after_process=run.filter.last_nis();
            if(trace_enabled && !run.first_covariance_failure_written && !covariance_after_process) {
                write_covariance_values(covariance_trace,run,s,"pre_process",covariance_before_values.data(),-1,NAN);
                write_covariance_snapshot(covariance_trace,run,s,covariance_before?"process":"preexisting",run.filter);
                run.first_covariance_failure_written=true;
            }
            const bool heading_available=(s.flags&1u)!=0;
            const bool heading_attempted=heading_available && std::strcmp(aid,"NONE")!=0;
            bool aid_accepted=false;
            if(heading_attempted) {
                const float heading=std::strcmp(aid,"INDEPENDENT_MEASUREMENT")==0?s.independent_heading:s.oracle_heading;
                aid_accepted=run.filter.update_heading_at({s.reported_us,kHeadingSource,0},heading,
                    static_cast<float>(kIndependentHeadingSigma));
            }
            int heading_failed_pivot=-1;float heading_failed_pivot_value=NAN;
            const bool covariance_after_heading=!trace_enabled ||
                !cholesky_failure(run.filter,heading_failed_pivot,heading_failed_pivot_value);
            if(trace_enabled && !run.first_covariance_failure_written && !covariance_after_heading) {
                write_covariance_values(covariance_trace,run,s,"pre_heading_aid",covariance_after_process_values.data(),-1,NAN);
                write_covariance_snapshot(covariance_trace,run,s,covariance_after_process?"heading_aid":"preexisting",run.filter);
                run.first_covariance_failure_written=true;
            }
            const float nis_after_heading=run.filter.last_nis();
            if(trace_enabled) write_sample_trace(sample_trace,s,rate,run,in_eval,propagated,heading_available,
                heading_attempted,aid_accepted,run.filter.gravity_applied_updates()-gravity_before,
                run.filter.rejected_updates()-rejected_before,nis_after_process,nis_after_heading,
                health_before,health_after_process,covariance_before,covariance_after_process,
                covariance_after_heading,process_failed_pivot,process_failed_pivot_value,
                heading_failed_pivot,heading_failed_pivot_value);
            if(in_eval) {
                TrialMetrics& m=run.metrics;++m.expected;
                if(propagated)++m.produced;
                const auto age=run.filter.state_timestamp_us()<=s.reported_us?s.reported_us-run.filter.state_timestamp_us():0;
                m.max_state_age_us=std::max(m.max_state_age_us,age);
                if(run.filter.state_timestamp_us()<s.reported_us)++m.stale;
                if(run.filter.rejected_updates()>rejected_before)m.rejected+=run.filter.rejected_updates()-rejected_before;
                if(run.filter.health()==Health::Fault && !fault_before)++m.faults;
                if(run.filter.reset_required() && !reset_before)++m.resets;
                const bool state_ok=run.filter.control_state_valid();
                if(state_ok)++m.control_valid;
                const bool covariance_ok=trace_enabled?covariance_after_heading:run.filter.covariance_positive_definite();
                if(covariance_ok)++m.covariance_valid;
                const bool output_valid=state_ok && covariance_ok;
                if(!output_valid) {
                    if(!std::isfinite(m.outage_start_s))m.outage_start_s=nominal_t;
                    m.outage_open=true;
                } else if(m.outage_open) {
                    if(!std::isfinite(m.recovery_time_s))m.recovery_time_s=static_cast<float>(nominal_t-m.outage_start_s);
                    m.outage_open=false;m.outage_start_s=NAN;
                }
                if(output_valid) {
                    ++m.valid;
                    const auto& estimate=run.filter.state();
                    const float tilt=tilt_error_deg(estimate.orientation,s.truth_q);
                    const float attitude=attitude_error_deg(estimate.orientation,s.truth_q);
                    const float yaw=wrap_pi(estimate.orientation.yaw()-s.truth_q.yaw())*180.0f/kPi;
                    const float position=(estimate.position-s.truth_p).norm();
                    const float velocity=(estimate.velocity-s.truth_v).norm();
                    if(std::isfinite(tilt)&&std::isfinite(attitude)&&std::isfinite(yaw)&&std::isfinite(position)&&std::isfinite(velocity)) {
                        m.tilt.push_back(tilt);m.attitude.push_back(attitude);m.yaw_abs.push_back(std::fabs(yaw));m.position.push_back(position);m.velocity.push_back(velocity);
                        m.tilt_sq+=tilt*tilt;m.attitude_sq+=attitude*attitude;m.yaw_sq+=yaw*yaw;m.position_sq+=position*position;m.velocity_sq+=velocity*velocity;
                        m.accel_bias_error=(estimate.accel_bias-s.truth_ba).norm();m.gyro_bias_error=(estimate.gyro_bias-s.truth_bg).norm();
                        const double nees=tilt_nees(run.filter,s.truth_q);
                        if(std::isfinite(nees)){m.nees_sum+=nees;++m.nees_count;if(nees<5.99146)++m.nees_95;}
                    } else {--m.valid;}
                }
                const auto gravity_after=run.filter.gravity_applied_updates();
                if(gravity_after>gravity_before && std::isfinite(run.filter.last_nis())) {m.nis_sum+=run.filter.last_nis();++m.nis_count;}
                if(std::strcmp(aid,"NONE")!=0 && heading_available) {
                    if(aid_accepted && run.filter.accepted_updates()>aid_before) {m.nis_sum+=run.filter.last_nis();++m.nis_count;++m.aid_accepted;}
                    else ++m.aid_rejected;
                }
            }
        }
        previous_reported=s.reported_us;
        previous_physical=s.physical_us;
    }
    if(in.peek()!=std::char_traits<char>::eof()) {std::fputs("trailing bytes after declared PR3 input records\n",stderr);return 3;}
    out<<"protocol_version,protocol_sha256,input_sha256,config_sha256,commit_sha,scenario,rate_mode,stress_mode,seed_split,seed,sensor_input,startup_knowledge,startup_gyro_bias_calibration,runtime_aid,estimator,expected,produced,valid,missing,unavailable,unavailable_duration_s,recovery_time_s,recovery_time_reason,stale,control_valid,covariance_valid,faults,resets,rejected,aid_accepted,aid_rejected,availability,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,attitude_rms_deg,yaw_rms_deg,position_rms_m,velocity_rms_m_s,accel_bias_error_m_s2,gyro_bias_error_rad_s,tilt_nees_mean,tilt_nees_count,tilt_nees_coverage95,nis_mean,nis_count,max_state_age_us,health_end,complete_run,pr2_gate_status\n";
    out.setf(std::ios::fixed);out.precision(8);
    for(Run& run:runs) {
        TrialMetrics& m=run.metrics;
        const std::uint32_t missing=m.expected-m.produced;
        const std::uint32_t unavailable=m.expected-m.valid;
        const char* health=health_name(run.filter.health());
        const char* recovery_reason=std::isfinite(m.recovery_time_s)?"recovered_after_unavailability":(m.outage_open?"not_recovered_by_end":"no_unavailability");
        out<<kProtocolVersion<<','<<kProtocolSha256<<','<<input_sha<<','<<config_sha<<','<<commit_sha<<','<<kScenarioIds[scenario]<<','<<kRateIds[rate_mode]<<','<<(stress?"stress":"nominal")<<','<<split<<','<<seed<<','<<sensor_input<<','<<startup<<','<<(startup_calibration?"ON":"OFF")<<','<<aid<<','<<policy_name(run.policy)<<','<<m.expected<<','<<m.produced<<','<<m.valid<<','<<missing<<','<<unavailable<<','<<static_cast<double>(unavailable)/rate<<',';
        csv_float(out,m.recovery_time_s);out<<','<<recovery_reason<<','<<m.stale<<','<<m.control_valid<<','<<m.covariance_valid<<','<<m.faults<<','<<m.resets<<','<<m.rejected<<','<<m.aid_accepted<<','<<m.aid_rejected<<',';
        csv_float(out,m.expected?static_cast<float>(m.valid)/m.expected:NAN);out<<',';
        csv_float(out,rms(m.tilt_sq,m.valid));out<<',';csv_float(out,percentile(m.tilt,0.95f));out<<',';csv_float(out,m.tilt.empty()?NAN:*std::max_element(m.tilt.begin(),m.tilt.end()));out<<',';
        csv_float(out,rms(m.attitude_sq,m.valid));out<<',';csv_float(out,rms(m.yaw_sq,m.valid));out<<',';csv_float(out,rms(m.position_sq,m.valid));out<<',';csv_float(out,rms(m.velocity_sq,m.valid));out<<',';
        csv_float(out,m.accel_bias_error);out<<',';csv_float(out,m.gyro_bias_error);out<<',';
        if(m.nees_count) out<<m.nees_sum/m.nees_count;
        out<<','<<m.nees_count<<',';
        if(m.nees_count) out<<static_cast<double>(m.nees_95)/m.nees_count;
        out<<',';
        if(m.nis_count) out<<m.nis_sum/m.nis_count;
        out<<','<<m.nis_count<<','<<m.max_state_age_us<<','<<health<<','
           <<(m.expected==m.produced&&m.valid==m.expected&&m.covariance_valid==m.expected?"true":"false")<<",OPEN\n";
    }
    if(!out || (sample_trace.is_open() && (!sample_trace || !covariance_trace))) return 4;
    return 0;
}
} // namespace

int main(int argc,char**argv) {
    if(argc!=11 && argc!=13) {
        std::fprintf(stderr,"usage: pr3_evaluate_stream INPUT OUTPUT SPLIT SENSOR_INPUT STARTUP KNOWLEDGE_CALIBRATION(0|1) RUNTIME_AID COMMIT_SHA CONFIG_SHA INPUT_SHA [--sample-trace TRACE.csv]\n");
        return 2;
    }
    if(argc==13 && std::strcmp(argv[11],"--sample-trace")!=0) return 2;
    const std::string calibration=argv[6];
    if(calibration!="0"&&calibration!="1")return 2;
    return evaluate(argv[1],argv[2],argv[3],argv[4],argv[5],calibration=="1",argv[7],argv[8],argv[9],argv[10],
        argc==13?argv[12]:nullptr);
}
