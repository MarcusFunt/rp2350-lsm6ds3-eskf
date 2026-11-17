// Sample-by-sample host replay of the production ESKF for B9.
#define INERTIAL_GRAVITY_DIAGNOSTICS 1
#include "../eskf15.hpp"

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {
using namespace inertial;

struct InputRow {
    uint64_t sample_index=0;
    uint64_t timestamp_us=0;
    bool valid=false;
    Vec3 accel{};
    Vec3 gyro{};
};

bool parse_u64(const std::string& text,uint64_t& value) {
    if(text.empty() || text[0]=='-') return false;
    char* end=nullptr;
    errno=0;
    const unsigned long long parsed=std::strtoull(text.c_str(),&end,10);
    if(errno==ERANGE || end==text.c_str() || *end!='\0') return false;
    value=static_cast<uint64_t>(parsed);
    return true;
}

bool parse_f32(const std::string& text,float& value) {
    if(text.empty()) return false;
    char* end=nullptr;
    errno=0;
    const float parsed=std::strtof(text.c_str(),&end);
    if(errno==ERANGE || end==text.c_str() || *end!='\0' || !std::isfinite(parsed)) return false;
    value=parsed;
    return true;
}

bool split_csv(const std::string& line,std::vector<std::string>& fields) {
    fields.clear();
    std::istringstream stream(line);
    std::string field;
    while(std::getline(stream,field,',')) fields.push_back(field);
    if(!line.empty() && line.back()==',') fields.emplace_back();
    return true;
}

bool parse_row(const std::string& line,InputRow& row) {
    std::vector<std::string> f;
    split_csv(line,f);
    if(f.size()!=9 || !parse_u64(f[0],row.sample_index) || row.sample_index==0 ||
       !parse_u64(f[1],row.timestamp_us) || f[2].size()!=1 || (f[2][0]!='0' && f[2][0]!='1')) return false;
    row.valid=f[2][0]=='1';
    float v[6];
    for(int i=0;i<6;i++) if(!parse_f32(f[3+i],v[i])) return false;
    row.accel={v[0],v[1],v[2]};
    row.gyro={v[3],v[4],v[5]};
    return true;
}

const char* health_name(Health health) {
    switch(health) {
        case Health::Aligning:return "Aligning";
        case Health::Nominal:return "Nominal";
        case Health::Degraded:return "Degraded";
        case Health::Fault:return "Fault";
    }
    return "Unknown";
}

const char* gravity_reason_name(GravityDiagnosticReason reason) {
    switch(reason) {
        case GravityDiagnosticReason::NotInitialized:return "not_initialized";
        case GravityDiagnosticReason::InitializationComplete:return "initialization_complete";
        case GravityDiagnosticReason::InputInvalid:return "input_invalid";
        case GravityDiagnosticReason::TimestampInvalid:return "timestamp_invalid";
        case GravityDiagnosticReason::GapRejected:return "gap_rejected";
        case GravityDiagnosticReason::CandidateRejected:return "candidate_gate_failed";
        case GravityDiagnosticReason::DwellIncomplete:return "candidate_dwell_incomplete";
        case GravityDiagnosticReason::AidCadencePending:return "aid_cadence_pending";
        case GravityDiagnosticReason::ExternalConfirmationRequired:return "external_confirmation_required";
        case GravityDiagnosticReason::MeasurementModelRejected:return "measurement_model_rejected";
        case GravityDiagnosticReason::DebiasedAccelerationRejected:return "debiased_acceleration_invalid";
        case GravityDiagnosticReason::ConservativeAngleRejected:return "conservative_angle_gate_failed";
        case GravityDiagnosticReason::InvalidNoiseSigma:return "invalid_noise_sigma";
        case GravityDiagnosticReason::InnovationCovarianceRejected:return "innovation_covariance_invalid";
        case GravityDiagnosticReason::NisRejected:return "nis_gate_rejected";
        case GravityDiagnosticReason::NonFiniteCorrection:return "nonfinite_correction";
        case GravityDiagnosticReason::Accepted:return "accepted";
    }
    return "unknown";
}

void csv_float(std::ostream& output,float value) {
    if(std::isfinite(value)) output<<value;
}

int run(const char* input_path,const char* output_path,const char* profile) {
    if(std::string(profile)!="lsm6ds3" && std::string(profile)!="broad") {
        std::cerr<<"range profile must be 'lsm6ds3' or 'broad'\n";
        return 2;
    }
    std::ifstream input(input_path);
    if(!input) {std::cerr<<"cannot open input CSV: "<<input_path<<"\n";return 2;}
    std::string header;
    if(!std::getline(input,header) || header!="sample_index,timestamp_us,valid,ax,ay,az,gx,gy,gz") {
        std::cerr<<"input CSV header does not match the B9 schema\n";
        return 2;
    }
    std::ofstream output(output_path,std::ios::trunc);
    if(!output) {std::cerr<<"cannot create output CSV: "<<output_path<<"\n";return 2;}

    Settings settings{};
    // All BROAD inputs use 2000/7 Hz. Give both range controls the same timebase.
    settings.expected_period_us=3500;
    if(std::string(profile)=="broad") {
        settings.max_gyro_axis_rps=0.98f*2000.0f*(kPi/180.0f);
        settings.max_accel_axis_mps2=0.98f*16.0f*kGravity;
    }
    Eskf15 filter(settings);
    const float gyro_limit=settings.max_gyro_axis_rps;
    const float accel_limit=settings.max_accel_axis_mps2;

    output<<"sample_index,timestamp_us,input_valid,process_propagated,output_valid,status,health,reset_required,state_timestamp_us,"
          <<"gyro_axis_absmax_rad_s,accel_axis_absmax_mps2,max_gyro_axis_rps,max_accel_axis_mps2,"
          <<"state_orientation_w,state_orientation_x,state_orientation_y,state_orientation_z,"
          <<"accel_bias_x,accel_bias_y,accel_bias_z,gyro_bias_x,gyro_bias_y,gyro_bias_z,"
          <<"cov_theta_xx,cov_theta_yy,cov_theta_zz,gravity_reason,gravity_attempted,gravity_accepted,"
          <<"gravity_accel_norm_mps2,gravity_gyro_norm_rad_s,gravity_accel_step_mps2,"
          <<"gravity_accel_norm_gate_pass,gravity_gyro_norm_gate_pass,gravity_accel_step_gate_pass,"
          <<"gravity_innovation_angle_rad,gravity_nis,gravity_nis_gate\n";
    output<<std::setprecision(9);

    std::string line;
    uint64_t previous_index=0,previous_timestamp=0;
    while(std::getline(input,line)) {
        if(line.empty()) continue;
        InputRow row{};
        if(!parse_row(line,row) || row.sample_index!=previous_index+1 ||
           (previous_index!=0 && row.timestamp_us<=previous_timestamp)) {
            std::cerr<<"invalid or unordered input record after sample "<<previous_index<<"\n";
            return 3;
        }
        const bool propagated=row.valid && filter.process({row.timestamp_us,row.accel,row.gyro});
        const bool current=filter.control_state_valid();
        const char* status=!row.valid ? "invalid_input" :
            (filter.health()==Health::Fault ? "failed" : (current ? "valid" : "warming_up"));
        const GravityDiagnostic& d=filter.gravity_diagnostic();
        const State& state=filter.state();
        output<<row.sample_index<<','<<row.timestamp_us<<','<<(row.valid?"true":"false")<<','
              <<(propagated?"true":"false")<<','<<((row.valid&&current)?"true":"false")<<','<<status<<','
              <<health_name(filter.health())<<','<<(filter.reset_required()?"true":"false")<<','
              <<filter.state_timestamp_us()<<','<<std::max(std::fabs(row.gyro.x),std::max(std::fabs(row.gyro.y),std::fabs(row.gyro.z)))<<','
              <<std::max(std::fabs(row.accel.x),std::max(std::fabs(row.accel.y),std::fabs(row.accel.z)))<<','
              <<gyro_limit<<','<<accel_limit<<','
              <<state.orientation.w<<','<<state.orientation.x<<','<<state.orientation.y<<','<<state.orientation.z<<','
              <<state.accel_bias.x<<','<<state.accel_bias.y<<','<<state.accel_bias.z<<','
              <<state.gyro_bias.x<<','<<state.gyro_bias.y<<','<<state.gyro_bias.z<<','
              <<filter.variance(6)<<','<<filter.variance(7)<<','<<filter.variance(8)<<','
              <<gravity_reason_name(d.reason)<<','<<(d.gravity_attempted?"true":"false")<<','<<(d.gravity_accepted?"true":"false")<<',';
        csv_float(output,d.accel_norm);output<<',';csv_float(output,d.gyro_norm);output<<',';csv_float(output,d.accel_step);output<<','
              <<(d.accel_norm_gate_pass?"true":"false")<<','<<(d.gyro_norm_gate_pass?"true":"false")<<','
              <<(d.accel_step_gate_pass?"true":"false")<<',';
        csv_float(output,d.innovation_angle_rad);output<<',';csv_float(output,d.gravity_nis);output<<',';csv_float(output,d.gravity_nis_gate);output<<'\n';
        if(!output) {std::cerr<<"failed while writing replay output\n";return 4;}
        previous_index=row.sample_index;
        previous_timestamp=row.timestamp_us;
    }
    if(input.bad()) {std::cerr<<"failed while reading input CSV\n";return 4;}
    return 0;
}
} // namespace

int main(int argc,char** argv) {
    if(argc!=4) {
        std::cerr<<"usage: b9_eskf_replay INPUT.csv OUTPUT.csv lsm6ds3|broad\n";
        return 2;
    }
    return run(argv[1],argv[2],argv[3]);
}
