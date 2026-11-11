#include "../binary_log.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

// Example: binary_log_tool generate /tmp/imu.bin
//          binary_log_tool replay /tmp/imu.bin [required-calibration-id]
int main(int argc,char **argv){
    if (argc<3) {std::cerr<<"usage: binary_log_tool generate|replay PATH [calibration_id]\n";return 2;}
    const std::string mode=argv[1];
    if(mode=="generate"){
        std::ofstream out(argv[2],std::ios::binary);
        if(!out)return 2;
        uint8_t b[imu_log::kRecordSize]{};
        imu_log::Header header{0x4c364433u,1u,1234u,208};
        imu_log::encode_header(header,b);out.write(reinterpret_cast<char*>(b),imu_log::kHeaderSize);
        for(uint32_t i=0;i<1200;i++){
            imu_log::Record r{};
            r.capture_us=1'000'000ull+uint64_t(i)*4808ull;
            r.publication_us=r.capture_us+40;
            r.sequence=i+1+(i>=600?1u:0u); // one deliberately missing source record
            r.dropped_records_before=(i==600)?1u:0u;
            r.accel_mps2={0,0,9.80665f};
            r.gyro_rps={0,0,i<200?0.0f:0.1f};
            imu_log::encode_record(r,b);out.write(reinterpret_cast<char*>(b),imu_log::kRecordSize);
        }
        return out ? 0:3;
    }
    if(mode!="replay")return 2;
    std::ifstream in(argv[2],std::ios::binary);
    uint8_t b[imu_log::kRecordSize]{};
    if(!in.read(reinterpret_cast<char*>(b),imu_log::kHeaderSize))return 3;
    imu_log::Header header{};
    if(!imu_log::decode_header(b,imu_log::kHeaderSize,header))return 4;
    if(argc>3 && header.calibration_id!=uint32_t(std::strtoul(argv[3],nullptr,0))) {
        std::cerr<<"calibration mismatch\n"; return 5;
    }
    inertial::Settings cfg{};cfg.calibration_id=header.calibration_id;
    inertial::Eskf15 filter(cfg);
    uint64_t previous=0;uint32_t previous_sequence=0;
    std::size_t count=0,valid=0;uint64_t sequence_gaps=0,dropped_records=0;
    std::cout<<"timestamp_us,sequence,sequence_gap_before,dropped_records_before,yaw_rad,health,valid\n";
    for(;;){
        in.read(reinterpret_cast<char*>(b),imu_log::kRecordSize);
        if(in.gcount()==0&&in.eof())break;
        if(in.gcount()!=static_cast<std::streamsize>(imu_log::kRecordSize)){
            std::cerr<<"truncated record\n";return 6;
        }
        imu_log::Record r{};
        if(!imu_log::decode_record(b,imu_log::kRecordSize,r) || r.version!=header.version ||
           (previous && r.capture_us<=previous)){
            std::cerr<<"invalid record or nonmonotonic timestamp\n";return 7;
        }
        uint32_t sequence_gap=0;
        if(count){
            const uint32_t sequence_delta=r.sequence-previous_sequence;
            if(sequence_delta==0 || sequence_delta>=0x80000000u){
                std::cerr<<"duplicate or nonmonotonic sequence\n";return 7;
            }
            sequence_gap=sequence_delta-1u;
        }
        previous=r.capture_us;count++;
        previous_sequence=r.sequence;
        sequence_gaps+=sequence_gap;dropped_records+=r.dropped_records_before;
        const bool ok=filter.process({r.capture_us,r.accel_mps2,r.gyro_rps});
        valid+=ok?1:0;
        std::cout<<r.capture_us<<','<<r.sequence<<','<<sequence_gap<<','<<r.dropped_records_before<<','
                 <<std::setprecision(9)<<filter.state().orientation.yaw()<<','
                 <<unsigned(filter.health())<<','<<unsigned(ok)<<'\n';
    }
    std::cerr<<"replayed="<<count<<" propagated="<<valid<<" sequence_gaps="<<sequence_gaps
             <<" explicit_drops="<<dropped_records<<" calibration="<<header.calibration_id<<"\n";
    return count ? 0 : 8;
}
