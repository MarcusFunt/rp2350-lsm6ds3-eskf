#define INERTIAL_GRAVITY_DIAGNOSTICS 1
#include "../eskf15.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>

using namespace inertial;

static Imu sample(unsigned index, Vec3 accel={0,0,kGravity}, Vec3 gyro={}) {
    return {1000000u+static_cast<uint64_t>(index)*4808u, accel, gyro};
}

static void test_candidate_dwell_and_aid_cadence_are_distinct() {
    Settings settings;
    settings.static_min_samples=3;
    settings.aid_every_samples=2;
    Eskf15 filter(settings);

    for(unsigned i=1;i<=80;i++) filter.process(sample(i));
    assert(filter.ready());

    const Vec3 step_rejected_accel{0.25f,0.0f,std::sqrt(kGravity*kGravity-0.25f*0.25f)};
    filter.process(sample(81,step_rejected_accel));
    auto diagnostic=filter.gravity_diagnostic();
    assert(diagnostic.initialized);
    assert(diagnostic.accel_norm_gate_pass);
    assert(diagnostic.gyro_norm_gate_pass);
    assert(!diagnostic.accel_step_gate_pass);
    assert(!diagnostic.raw_candidate);
    assert(diagnostic.consecutive_candidate_samples==0);
    assert(!diagnostic.gravity_attempted);
    assert(diagnostic.reason==GravityDiagnosticReason::CandidateRejected);

    filter.process(sample(82)); // The return step also exceeds the limit.
    filter.process(sample(83));
    diagnostic=filter.gravity_diagnostic();
    assert(diagnostic.raw_candidate);
    assert(diagnostic.consecutive_candidate_samples==1);
    assert(!diagnostic.stationary);
    assert(!diagnostic.gravity_attempted);
    assert(diagnostic.reason==GravityDiagnosticReason::DwellIncomplete);

    filter.process(sample(84));
    diagnostic=filter.gravity_diagnostic();
    assert(!diagnostic.stationary);
    assert(diagnostic.consecutive_candidate_samples==2);
    assert(diagnostic.reason==GravityDiagnosticReason::DwellIncomplete);

    filter.process(sample(85));
    diagnostic=filter.gravity_diagnostic();
    assert(diagnostic.stationary);
    assert(diagnostic.gravity_allowed);
    assert(!diagnostic.gravity_attempted);
    assert(diagnostic.reason==GravityDiagnosticReason::AidCadencePending);

    filter.process(sample(86));
    diagnostic=filter.gravity_diagnostic();
    assert(diagnostic.gravity_attempted);
    assert(diagnostic.gravity_accepted);
    assert(diagnostic.reason==GravityDiagnosticReason::Accepted);
    assert(std::isfinite(diagnostic.gravity_nis));
    assert(std::fabs(diagnostic.gravity_nis_gate-16.0f)<1e-6f);
}

int main() {
    test_candidate_dwell_and_aid_cadence_are_distinct();
    std::puts("PASS gravity diagnostic candidate, dwell, cadence and update reasons");
}
