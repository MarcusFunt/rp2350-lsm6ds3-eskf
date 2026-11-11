#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include "pr3_scenario_protocol.hpp"

int main() {
    using namespace pr3_protocol;
    assert(kProtocolVersion == 3);
    assert(kScenarioCount == 8);
    assert(scenario_index("compound_motion") == 7);
    assert(scenario_index("unknown") == -1);
    assert(nominal_timestamp_us(208, 208) == 2000000);
    assert(nominal_timestamp_us(200, 200) == 2000000);
    const Motion maneuver = motion(scenario_index("maneuver"), 5.25);
    const Motion jitter_scenario = motion(scenario_index("timing_jitter"), 5.25);
    assert(std::fabs(maneuver.body_rate_rad_s.x-jitter_scenario.body_rate_rad_s.x)<1e-12);
    assert(std::fabs(maneuver.world_acceleration_m_s2.y-jitter_scenario.world_acceleration_m_s2.y)<1e-12);
    assert(disturbance(scenario_index("vibration"),0,false,1.99)==0.0);
    const double vibration_t=2.0+1.0/(4.0*43.0);
    assert(std::fabs(disturbance(scenario_index("vibration"),0,false,vibration_t)-0.4)<1e-12);
    assert(rate_jitter_us(2, 100) != 0);
    assert(scenario_jitter_us(scenario_index("timing_jitter"),100,208) != 0);
    for (int rate_mode=0; rate_mode<3; ++rate_mode) {
        const int rate=kRateHz[rate_mode];
        for (int scenario=0; scenario<kScenarioCount; ++scenario) {
            std::int64_t previous=nominal_timestamp_us(0,rate)
                +rate_jitter_us(rate_mode,0,2.0)+scenario_jitter_us(scenario,0,rate,2.0);
            for (std::uint64_t i=1;i<=static_cast<std::uint64_t>(rate*16);++i) {
                const std::int64_t timestamp=nominal_timestamp_us(i,rate)
                    +rate_jitter_us(rate_mode,i,2.0)+scenario_jitter_us(scenario,i,rate,2.0);
                assert(timestamp-previous>=4700);
                previous=timestamp;
            }
        }
    }
    std::puts("PASS PR3 generated scenario runtime: profiles, disturbances, timestamps and stress jitter");
}
