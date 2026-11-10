#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CXX="${CXX:-g++}"
BUILD_DIR="${PR1_BUILD_DIR:-${TMPDIR:-/tmp}/rp2350_pr1_baseline}"
REPORT_DIR="$ROOT/benchmarks/reports"
LEGACY_COMMIT=e90c80eb47e5002738f4a16450714b3149798e28
LEGACY_HEADER="$BUILD_DIR/legacy_eskf15.hpp"

mkdir -p "$BUILD_DIR" "$REPORT_DIR"
if [[ "$(uname -s)" == Linux && -n "$(command -v git.exe || true)" ]]; then
  WINDOWS_ROOT="$(wslpath -m "$ROOT")"
  git.exe -C "$WINDOWS_ROOT" show "$LEGACY_COMMIT:eskf15.hpp" > "$LEGACY_HEADER"
else
  git -C "$ROOT" show "$LEGACY_COMMIT:eskf15.hpp" > "$LEGACY_HEADER"
fi

"$CXX" -std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror \
  -I"$BUILD_DIR" "$ROOT/tools/pr1_legacy_compare.cpp" -o "$BUILD_DIR/pr1_legacy_compare"
"$BUILD_DIR/pr1_legacy_compare" \
  "$REPORT_DIR/pr1_imu_samples_protocol_v2.bin" \
  "$REPORT_DIR/pr1_sample_index_protocol_v2.csv" \
  "$REPORT_DIR/pr1_historical_default_protocol_v2.csv"
