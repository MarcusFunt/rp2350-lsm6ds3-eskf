#pragma once
// Explicit physical aiding contract. No delayed-state replay yet: only
// measurements actually aligned with the current ESKF state are accepted.
#include <cmath>
#include <cstdint>
#include "eskf15.hpp"

namespace inertial {
enum class AidingType : uint8_t { PositionWorld, VelocityWorld, HeadingWorld, VerifiedZeroRate, VerifiedZeroVelocity };
enum class AidingFrame : uint8_t { WorldENU, BodyFLU }; // right-handed; world Z up
// A source with shared IMU/VIO evidence must not claim statistical independence.
enum class AidingProvenance : uint8_t { IndependentPhysical, CorrelatedOrFused };
struct AidingMeasurement {
    AidingType type=AidingType::PositionWorld;
    AidingFrame frame=AidingFrame::WorldENU;
    AidingProvenance provenance=AidingProvenance::CorrelatedOrFused;
    uint64_t capture_us=0, publication_us=0, interval_start_us=0, interval_end_us=0;
    uint32_t timebase_id=0, source_id=0, calibration_id=0;
    Vec3 value{}; // position m, velocity m/s, gyro rad/s (per type)
    float scalar_value=0; // yaw rad only
    float sigma=0; // isotropic 1-sigma units of value, positive
    bool valid=false;
};
enum class AidingResult : uint8_t {
    Accepted, Invalid, WrongTimebase, WrongFrame, BadCalibration,
    StaleOrFuture, CorrelatedEvidence, DuplicateOrReordered, FilterRejected, SourceTableFull
};
class AidingRouter {
public:
    explicit AidingRouter(uint32_t expected_timebase=1,uint32_t expected_calibration=0)
        : timebase_(expected_timebase),calibration_(expected_calibration) {}
    AidingResult apply(Eskf15 &filter,const AidingMeasurement &m) {
        if (!m.valid || !m.source_id || !m.capture_us || !std::isfinite(m.sigma) ||
            !(m.sigma>0) || !std::isfinite(m.scalar_value) ||
            !SensorValuesFinite(m.value) || m.publication_us<m.capture_us ||
            m.interval_start_us>m.capture_us || m.interval_end_us<m.capture_us ||
            m.interval_end_us>m.publication_us ||
            m.interval_end_us<m.interval_start_us) return AidingResult::Invalid;
        if (m.timebase_id!=timebase_) return AidingResult::WrongTimebase;
        if (m.calibration_id!=calibration_) return AidingResult::BadCalibration;
        if (m.provenance!=AidingProvenance::IndependentPhysical) return AidingResult::CorrelatedEvidence;
        if (m.type==AidingType::VerifiedZeroRate ? m.frame!=AidingFrame::BodyFLU : m.frame!=AidingFrame::WorldENU)
            return AidingResult::WrongFrame;
        if (!filter.ready() || m.capture_us>filter.state_timestamp_us() ||
            filter.state_timestamp_us()-m.capture_us>1000) return AidingResult::StaleOrFuture;
        int slot=-1,free_slot=-1;
        for(int i=0;i<kSources;i++) {
            if (sources_[i]==m.source_id) slot=i;
            if (!sources_[i] && free_slot==-1) free_slot=i;
        }
        if (slot<0 && free_slot<0) return AidingResult::SourceTableFull;
        if (slot>=0 && m.capture_us<=last_capture_[slot]) return AidingResult::DuplicateOrReordered;
        const AidingStamp stamp{m.capture_us,m.source_id,m.calibration_id};
        bool ok=false;
        switch(m.type) {
            case AidingType::PositionWorld: ok=filter.update_position_world_at(stamp,m.value,m.sigma);break;
            case AidingType::VelocityWorld: ok=filter.update_velocity_world_at(stamp,m.value,m.sigma);break;
            case AidingType::HeadingWorld: ok=filter.update_heading_at(stamp,m.scalar_value,m.sigma);break;
            case AidingType::VerifiedZeroRate: ok=filter.update_zero_angular_rate_at(stamp,m.value,m.sigma);break;
            case AidingType::VerifiedZeroVelocity: ok=filter.update_zero_velocity_at(stamp,m.sigma);break;
            default: return AidingResult::Invalid;
        }
        if (!ok) return AidingResult::FilterRejected;
        if (slot<0) slot=free_slot;
        sources_[slot]=m.source_id;
        last_capture_[slot]=m.capture_us;
        return AidingResult::Accepted;
    }
private:
    static bool SensorValuesFinite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
    static constexpr int kSources=8;
    uint32_t timebase_,calibration_;
    uint32_t sources_[kSources]{};
    uint64_t last_capture_[kSources]{};
};
} // namespace inertial
