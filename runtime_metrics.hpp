#pragma once

#include <array>
#include <cstdint>

namespace inertial::metrics {

// Fixed-memory log2 histogram for embedded timing diagnostics. Percentiles
// return the inclusive upper edge of the selected bucket, not an exact sample.
class LatencyHistogram {
public:
    void observe(uint32_t microseconds) {
        uint8_t bucket=0;
        uint32_t value=microseconds;
        while(value>1u && bucket<31u){value>>=1u;++bucket;}
        if(bins_[bucket]!=UINT32_MAX) ++bins_[bucket];
        if(sample_count_!=UINT32_MAX) ++sample_count_;
        if(microseconds>max_us_) max_us_=microseconds;
    }

    uint32_t sample_count() const { return sample_count_; }
    uint32_t max_us() const { return max_us_; }

    // percentile_basis_points is 0..10000 (for example, 9500 is p95).
    uint32_t percentile_upper_bound(uint32_t percentile_basis_points) const {
        if(sample_count_==0) return 0;
        if(percentile_basis_points>10000u) percentile_basis_points=10000u;
        uint64_t rank=(uint64_t(sample_count_)*percentile_basis_points+9999u)/10000u;
        if(rank==0) rank=1;
        uint64_t cumulative=0;
        for(uint8_t bucket=0;bucket<32u;bucket++){
            cumulative+=bins_[bucket];
            if(cumulative>=rank){
                if(bucket==0) return 1;
                if(bucket==31u) return UINT32_MAX;
                return (uint32_t(1u)<<(bucket+1u))-1u;
            }
        }
        return max_us_;
    }

private:
    std::array<uint32_t,32> bins_{};
    uint32_t sample_count_=0;
    uint32_t max_us_=0;
};

} // namespace inertial::metrics
