"""Independent, host-side adapter contract for external estimator benchmarks."""

from .api import (
    ContractError,
    FilterAdapter,
    canonical_input_sha256,
    canonical_json_sha256,
    check_reset_isolation,
    gravity_direction_body,
    rotate_body_to_world,
    run_trial,
    validate_adapter_manifest,
    validate_output_bundle,
    validate_trial,
)

__all__ = [
    "ContractError",
    "FilterAdapter",
    "canonical_input_sha256",
    "canonical_json_sha256",
    "check_reset_isolation",
    "gravity_direction_body",
    "rotate_body_to_world",
    "run_trial",
    "validate_adapter_manifest",
    "validate_output_bundle",
    "validate_trial",
]
