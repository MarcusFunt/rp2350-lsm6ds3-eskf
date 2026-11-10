// PR 2 paired comparison runner. Reuses the frozen PR 1 scenario generator,
// truth metrics, and estimator-provenance matrix without changing them.
#define main pr1_baseline_hidden_main
#include "pr1_baseline.cpp"
#undef main

int main(int argc, char** argv) {
    if (argc != 5) {
        std::fprintf(stderr,
            "Usage: pr2_confirmation OUTPUT_DIRECTORY SPLIT FIRST_SEED LAST_SEED\n");
        return 2;
    }
    const std::string dir=argv[1],split=argv[2];
    const unsigned first=static_cast<unsigned>(std::strtoul(argv[3],nullptr,10));
    const unsigned last=static_cast<unsigned>(std::strtoul(argv[4],nullptr,10));
    unsigned expected_first=0,expected_last=0;
    if(split=="development") { expected_first=101u; expected_last=116u; }
    else if(split=="confirmation") { expected_first=2001u; expected_last=2016u; }
    else if(split=="confirmation_v3") { expected_first=3001u; expected_last=3016u; }
    if (expected_first==0
        || first!=expected_first || last!=expected_last) {
        std::fprintf(stderr,"Refusing seed range for split %s\n",split.c_str());
        return 2;
    }

    const std::string summary_path=dir+"/summary.csv";
    const std::string trace_path=dir+"/representative_traces.csv";
    const std::string index_path=dir+"/sample_index.csv";
    const std::string sample_path=dir+"/imu_samples.bin";
    std::ofstream summary(summary_path),trace(trace_path),index(index_path),
        sample_file(sample_path,std::ios::binary);
    ensure_stream(summary,summary_path.c_str());
    ensure_stream(trace,trace_path.c_str());
    ensure_stream(index,index_path.c_str());
    ensure_stream(sample_file,sample_path.c_str());
    summary << "evaluation_protocol_version,scenario,noise_mode,seed_split,seed,input_mode,startup_knowledge,startup_calibration,runtime_aid,estimator,expected,valid,unavailable,stale,valid_fraction,tilt_rms_deg,tilt_p95_deg,tilt_max_deg,attitude_rms_deg,yaw_rms_deg,yaw_abs_p95_deg,yaw_abs_max_deg,position_rms_m,position_p95_m,velocity_rms_m_s,gravity_nis_mean,gravity_nis_count,gravity_applied,gravity_suppressed,aid_accepted,aid_rejected,health_end,max_state_age_us,accel_bias_error_end_m_s2,gyro_bias_error_end_rad_s\n";
    trace << "evaluation_protocol_version,scenario,noise_mode,seed_split,seed,input_mode,startup_knowledge,startup_calibration,runtime_aid,estimator,timestamp_us,time_s,truth_qw,truth_qx,truth_qy,truth_qz,truth_px,truth_py,truth_pz,truth_vx,truth_vy,truth_vz,imu_ax,imu_ay,imu_az,imu_gx,imu_gy,imu_gz,estimate_qw,estimate_qx,estimate_qy,estimate_qz,estimate_px,estimate_py,estimate_pz,estimate_vx,estimate_vy,estimate_vz,truth_bax,truth_bay,truth_baz,estimate_bax,estimate_bay,estimate_baz,truth_bgx,truth_bgy,truth_bgz,estimate_bgx,estimate_bgy,estimate_bgz,cov_p_x,cov_v_x,cov_theta_x,cov_ba_x,cov_bg_x,cov_theta_bg_x,cov_v_bg_x,gravity_event,nis,nis_source,heading_sample_present,output_valid,health,state_age_us,tilt_error_deg,attitude_error_deg,euler_yaw_error_deg,position_error_m,velocity_error_m_s\n";
    index << "trial_id,scenario,noise_mode,seed_split,seed,offset_bytes,record_count,record_bytes\n";
    summary << std::fixed << std::setprecision(8);
    trace << std::fixed << std::setprecision(8);

    const std::array<Scenario,4> scenarios{{{"static"},{"pure_roll"},
        {"lateral_accel_0p2g"},{"slow_yaw"}}};
    const std::array<NoiseMode,3> noise_modes{{NoiseMode::AccelOnly,
        NoiseMode::GyroOnly,NoiseMode::Combined}};
    for(const Scenario& scenario:scenarios)
        for(NoiseMode noise:noise_modes)
            for(unsigned seed=first;seed<=last;seed++)
                write_trial(summary,trace,index,sample_file,scenario,noise,split.c_str(),seed);

    std::printf("Wrote %s comparison inputs and metrics: 4 scenarios x 3 noise modes x %u seeds; 18 variants per stream\n",
        split.c_str(),last-first+1);
    return 0;
}
