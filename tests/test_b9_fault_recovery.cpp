// B9 fault lifecycle checks against the production ESKF and runtime-health contract.
#include "../eskf15.hpp"
#include "../runtime_health.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>

using namespace inertial;

static constexpr float kSampleRatePeriodUs=5000.0f;
static uint64_t timestamp(unsigned index) {
    return 1000000ull+static_cast<uint64_t>(index)*static_cast<uint64_t>(kSampleRatePeriodUs);
}
static Imu stationary(unsigned index) { return {timestamp(index),{0,0,kGravity},{}}; }
static void initialize(Eskf15& filter,unsigned& index) {
    for(unsigned i=0;i<120;i++) filter.process(stationary(++index));
    assert(filter.ready());
    assert(filter.health()==Health::Nominal);
    assert(filter.control_state_valid());
}
static RuntimeHealth runtime_status(const Eskf15& filter,uint64_t now_us) {
    RuntimeHealthInput input{};
    input.now_us=now_us;
    input.last_sensor_edge_us=now_us;
    input.estimate_timestamp_us=filter.state_timestamp_us();
    input.estimate_publication_us=now_us;
    input.max_age_us=100000;
    input.calibration_id=1;
    input.estimator_health=filter.health();
    input.estimator_valid=filter.control_state_valid();
    input.reset_required=filter.reset_required();
    return assess_runtime_health(input);
}

static void short_gap_propagates_but_never_restores_nominal_health() {
    Settings settings{};
    settings.expected_period_us=5000;
    Eskf15 filter(settings);
    unsigned index=0;
    initialize(filter,index);
    ++index; // one missing 5 ms sample; the next observed interval is 10 ms
    assert(filter.process(stationary(++index)));
    assert(filter.health()==Health::Degraded);
    assert(!filter.reset_required());
    assert(filter.control_state_valid());
    assert(!runtime_status(filter,timestamp(index)+1000).output_available());
    assert(filter.process(stationary(++index)));
    assert(filter.health()==Health::Degraded);
    assert(!runtime_status(filter,timestamp(index)+1000).output_available());
    std::puts("PASS short gap propagates but remains non-nominal until reset");
}

static void duplicate_timestamp_degrades_without_latching_reset() {
    Settings settings{};
    settings.expected_period_us=5000;
    Eskf15 filter(settings);
    unsigned index=0;
    initialize(filter,index);
    const uint64_t last_good_time=filter.state_timestamp_us();
    assert(!filter.process({last_good_time,{0,0,kGravity},{}}));
    assert(filter.health()==Health::Degraded);
    assert(!filter.reset_required());
    assert(filter.state_timestamp_us()==last_good_time);
    assert(!runtime_status(filter,last_good_time+1000).output_available());
    assert(filter.process(stationary(++index)));
    assert(filter.health()==Health::Degraded);
    assert(!filter.reset_required());
    assert(filter.control_state_valid());
    assert(filter.state_timestamp_us()==timestamp(index));
    assert(!runtime_status(filter,timestamp(index)+1000).output_available());
    std::puts("PASS duplicate timestamp can resume propagation but requires reset to restore nominal output availability");
}

static void saturated_input_latches_and_withholds_stale_output_until_reinitialization() {
    Settings settings{};
    settings.expected_period_us=5000;
    Eskf15 filter(settings);
    unsigned index=0;
    initialize(filter,index);
    const uint64_t last_good_state_time=filter.state_timestamp_us();
    const Imu over_range{timestamp(++index),{0,0,kGravity},{0,0,500.0f*kPi/180.0f}};
    assert(!filter.process(over_range));
    assert(filter.health()==Health::Fault);
    assert(filter.reset_required());
    assert(!filter.control_state_valid());
    assert(filter.state_timestamp_us()==last_good_state_time);
    const RuntimeHealth fault_status=runtime_status(filter,timestamp(index)+200000);
    assert(!fault_status.output_available());
    assert(fault_status.flags&kResetRequired);
    assert(fault_status.flags&kEstimateStale);

    const uint64_t stale_timestamp=filter.state_timestamp_us();
    assert(!filter.process(stationary(++index)));
    assert(filter.reset_required());
    assert(filter.state_timestamp_us()==stale_timestamp);

    filter.reset();
    assert(!filter.ready() && !filter.reset_required());
    initialize(filter,index);
    assert(filter.control_state_valid());
    assert(filter.health()==Health::Nominal);
    assert(runtime_status(filter,timestamp(index)+1000).output_available());
    assert(!filter.process({timestamp(++index),{0,0,kGravity},{0,0,500.0f*kPi/180.0f}}));
    assert(filter.reset_required()); // reset preserves the configured range
    std::puts("PASS range fault latches, suppresses stale output, and needs reset plus reinitialization");
}

static void broad_sensor_range_accepts_legitimate_high_rate_motion() {
    Settings settings{};
    settings.expected_period_us=3500;
    settings.max_gyro_axis_rps=0.98f*2000.0f*kPi/180.0f;
    settings.max_accel_axis_mps2=0.98f*16.0f*kGravity;
    Eskf15 filter(settings);
    unsigned index=0;
    for(unsigned i=0;i<120;i++) filter.process({1000000ull+3500ull*++index,{0,0,kGravity},{}});
    assert(filter.ready() && filter.control_state_valid());
    const Imu high_rate{1000000ull+3500ull*++index,{0,0,kGravity},{0,0,500.0f*kPi/180.0f}};
    assert(filter.process(high_rate));
    assert(filter.health()==Health::Nominal);
    assert(filter.control_state_valid());
    assert(!filter.reset_required());
    std::puts("PASS BROAD full-scale configuration accepts 500 deg/s without latching");
}

static void long_gap_and_nonfinite_input_remain_unrecoverable_without_reset() {
    Settings settings{};
    settings.expected_period_us=5000;
    Eskf15 long_gap(settings);
    unsigned index=0;
    initialize(long_gap,index);
    index+=6; // 30 ms exceeds max_continuous_predict_dt_s
    assert(!long_gap.process(stationary(index)));
    assert(long_gap.health()==Health::Fault && long_gap.reset_required());
    assert(!long_gap.control_state_valid());

    Eskf15 nonfinite(settings);
    unsigned other=0;
    initialize(nonfinite,other);
    const float nan=std::nanf("");
    assert(!nonfinite.process({timestamp(++other),{nan,0,kGravity},{}}));
    assert(nonfinite.health()==Health::Fault && nonfinite.reset_required());
    assert(!nonfinite.control_state_valid());
    std::puts("PASS long gaps and non-finite samples stay latched until reset");
}

int main() {
    short_gap_propagates_but_never_restores_nominal_health();
    duplicate_timestamp_degrades_without_latching_reset();
    saturated_input_latches_and_withholds_stale_output_until_reinitialization();
    broad_sensor_range_accepts_legitimate_high_rate_motion();
    long_gap_and_nonfinite_input_remain_unrecoverable_without_reset();
}
