#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CXX="${CXX:-g++}"
export CXX
BUILD_DIR="${PR1_BUILD_DIR:-${TMPDIR:-/tmp}/rp2350_pr1_baseline}"
REPORT_DIR="$ROOT/benchmarks/reports"
mkdir -p "$BUILD_DIR" "$REPORT_DIR"
"$CXX" -std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror \
  "$ROOT/tools/pr1_baseline.cpp" -o "$BUILD_DIR/pr1_baseline"
"$BUILD_DIR/pr1_baseline" "$REPORT_DIR"
"$ROOT/tools/run_pr1_legacy_compare.sh"
python3 "$ROOT/tools/finalize_pr1_manifest.py"
