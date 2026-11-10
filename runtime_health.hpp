#pragma once
// Freshness and observability metadata for control consumers. Availability is
// not an accuracy certificate; callers must honor per-component observability.
#include <cstdint>
#include "eskf15.hpp"

namespace inertial {
enum RuntimeHealthFlag : uint32_t {
    kSensorStale=1u<<0,
    kEstimateStale=1u<<1,
    kCalibrationUnverified=1u<<2,
    kEstimatorInvalid=1u<<3,
    kResetRequired=1u<<4,
    kYawUnobservable=1u<<5,
    kPositionUnobservable=1u<<6,
    kEstimatorNotNominal=1u<<7
};

struct RuntimeHealthInput {
    uint64_t now_us=0;
    uint64_t last_sensor_edge_us=0;
    uint64_t estimate_timestamp_us=0;
    uint64_t estimate_publication_us=0;
    uint64_t max_age_us=100000;
    uint32_t calibration_id=0;
    uint8_t accepted_aid_mask=0;
    Health estimator_health=Health::Aligning;
    bool estimator_valid=false;
    bool reset_required=false;
};

struct RuntimeHealth {
    uint32_t flags=0;
    bool sensor_fresh=false;
    bool estimate_fresh=false;
    bool calibration_verified=false;
    bool estimator_valid=false;
    Health estimator_health=Health::Aligning;
    bool reset_required=false;
    bool yaw_observable=false;
    bool position_observable=false;

    // This only states whether an output is current, calibrated, and free of
    // an estimator reset/fault latch. It says nothing about physical accuracy.
    bool output_available() const {
        return sensor_fresh && estimate_fresh && calibration_verified &&
            estimator_valid && estimator_health==Health::Nominal && !reset_required;
    }
};

inline RuntimeHealth assess_runtime_health(const RuntimeHealthInput &in) {
    RuntimeHealth out{};
    out.sensor_fresh=in.last_sensor_edge_us!=0 && in.now_us>=in.last_sensor_edge_us &&
        in.now_us-in.last_sensor_edge_us<=in.max_age_us;
    out.estimate_fresh=in.estimate_timestamp_us!=0 && in.estimate_publication_us!=0 &&
        in.estimate_timestamp_us<=in.estimate_publication_us &&
        in.estimate_publication_us<=in.now_us && in.estimate_timestamp_us<=in.now_us &&
        in.now_us-in.estimate_timestamp_us<=in.max_age_us &&
        in.now_us-in.estimate_publication_us<=in.max_age_us;
    out.calibration_verified=in.calibration_id!=0;
    out.estimator_valid=in.estimator_valid;
    out.estimator_health=in.estimator_health;
    out.reset_required=in.reset_required;
    out.yaw_observable=(in.accepted_aid_mask&kAidHeading)!=0;
    out.position_observable=(in.accepted_aid_mask&kAidPosition)!=0;
    if(!out.sensor_fresh) out.flags|=kSensorStale;
    if(!out.estimate_fresh) out.flags|=kEstimateStale;
    if(!out.calibration_verified) out.flags|=kCalibrationUnverified;
    if(!out.estimator_valid) out.flags|=kEstimatorInvalid;
    if(out.reset_required) out.flags|=kResetRequired;
    if(in.estimator_health!=Health::Nominal) out.flags|=kEstimatorNotNominal;
    if(!out.yaw_observable) out.flags|=kYawUnobservable;
    if(!out.position_observable) out.flags|=kPositionUnobservable;
    return out;
}
} // namespace inertial
