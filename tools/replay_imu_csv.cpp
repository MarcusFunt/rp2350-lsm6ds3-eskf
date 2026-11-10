// Standalone host replay: g++ -std=c++17 -O2 tools/replay_imu_csv.cpp -o replay_imu
// Input: timestamp_us,ax_mps2,ay_mps2,az_mps2,gx_rps,gy_rps,gz_rps
// Lines beginning with '#' are metadata/comments; no gyro/accel integration by importer.
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <cstring>
#include "../eskf15.hpp"

int main(int argc,char **argv) {
    if(argc!=2) {std::fprintf(stderr,"Usage: %s imu_samples.csv\n",argv[0]);return 2;}
    FILE *fd=std::fopen(argv[1],"r");
    if(!fd) {std::perror(argv[1]);return 2;}
    inertial::Eskf15 f;
    char line[512]; unsigned records=0,propagated=0,malformed=0;
    std::puts("timestamp_us,health,qw,qx,qy,qz,px_m,py_m,pz_m,vx_mps,vy_mps,vz_mps,nis,gaps,saturations");
    while(std::fgets(line,sizeof(line),fd)) {
        if(line[0]=='#'||line[0]=='\n'||line[0]=='\r' || std::strncmp(line,"timestamp_",10)==0) continue;
        // Raw USB debugging may interleave human-readable summary/warning lines.
        if(line[0]<'0'||line[0]>'9') continue;
        unsigned long long t=0;
        float ax=0,ay=0,az=0,gx=0,gy=0,gz=0;
        const int fields=std::sscanf(line,"%llu,%f,%f,%f,%f,%f,%f",&t,&ax,&ay,&az,&gx,&gy,&gz);
        if(fields!=7) {++malformed;continue;}
        ++records;
        inertial::Imu imu{static_cast<uint64_t>(t),{ax,ay,az},{gx,gy,gz}};
        if(!f.process(imu)) continue;
        ++propagated;
        // Output 1 record every ~0.1 sec without altering prediction rate.
        if(propagated%20) continue;
        const auto &s=f.state();
        std::printf("%llu,%u,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%.8g,%u,%u\n",
            static_cast<unsigned long long>(f.state_timestamp_us()),
            static_cast<unsigned>(f.health()),
            s.orientation.w,s.orientation.x,s.orientation.y,s.orientation.z,
            s.position.x,s.position.y,s.position.z,
            s.velocity.x,s.velocity.y,s.velocity.z,
            f.last_nis(),f.gap_count(),f.saturation_count());
    }
    std::fclose(fd);
    std::fprintf(stderr,"Replay: %u valid CSV records, %u propagated; malformed %u; gaps %u; saturation %u; health %u\n",
        records,propagated,malformed,f.gap_count(),f.saturation_count(),static_cast<unsigned>(f.health()));
    if(malformed || !f.ready())return 1;
    return f.covariance_positive_definite()?0:3;
}
