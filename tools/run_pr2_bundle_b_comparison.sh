#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 4 ]]; then
  echo "usage: run_pr2_bundle_b_comparison.sh PR1_PARENT_WORKTREE PR2_CANDIDATE_WORKTREE SEED OUTPUT_DIRECTORY" >&2
  exit 2
fi

PARENT=$(cd "$1" && pwd)
CANDIDATE=$(cd "$2" && pwd)
SEED=$3
OUT=$(cd "$(dirname "$4")" && pwd)/$(basename "$4")
CXX=${CXX:-g++}

if [[ -e "$OUT" ]]; then
  echo "output directory already exists: $OUT" >&2
  exit 2
fi
if [[ ! "$SEED" =~ ^[0-9]+$ ]]; then
  echo "seed must be a nonnegative integer" >&2
  exit 2
fi
if ! cmp -s "$PARENT/tools/benchmark_bundle_b.cpp" "$CANDIDATE/tools/benchmark_bundle_b.cpp"; then
  echo "Bundle B generator differs between worktrees" >&2
  exit 2
fi

mkdir -p "$OUT/parent-source/tools" "$OUT/candidate-source/tools"
cp "$PARENT/tools/benchmark_bundle_b.cpp" "$OUT/parent-source/tools/"
cp "$PARENT/eskf15.hpp" "$OUT/parent-source/eskf15.hpp"
cp "$CANDIDATE/tools/benchmark_bundle_b.cpp" "$OUT/candidate-source/tools/"
cp "$CANDIDATE/eskf15.hpp" "$OUT/candidate-source/eskf15.hpp"
cp "$CANDIDATE/tools/compare_pr2_bundle_b.py" "$OUT/"

FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror)
"$CXX" "${FLAGS[@]}" "$OUT/parent-source/tools/benchmark_bundle_b.cpp" -o "$OUT/benchmark_parent"
"$CXX" "${FLAGS[@]}" "$OUT/candidate-source/tools/benchmark_bundle_b.cpp" -o "$OUT/benchmark_candidate"
"$OUT/benchmark_parent" --trials 5 --seed "$SEED" --output "$OUT/parent_no_startup_bias.csv"
"$OUT/benchmark_candidate" --trials 5 --seed "$SEED" --output "$OUT/candidate_no_startup_bias.csv"
"$OUT/benchmark_parent" --trials 5 --seed "$SEED" --startup-bias --output "$OUT/parent_verified_startup_bias.csv"
"$OUT/benchmark_candidate" --trials 5 --seed "$SEED" --startup-bias --output "$OUT/candidate_verified_startup_bias.csv"
python3 "$OUT/compare_pr2_bundle_b.py" \
  "$OUT/parent_no_startup_bias.csv" "$OUT/candidate_no_startup_bias.csv" \
  "$OUT/paired_no_startup_bias.csv"
python3 "$OUT/compare_pr2_bundle_b.py" \
  "$OUT/parent_verified_startup_bias.csv" "$OUT/candidate_verified_startup_bias.csv" \
  "$OUT/paired_verified_startup_bias.csv"
sha256sum "$CANDIDATE/tools/benchmark_bundle_b.cpp" "$CANDIDATE/eskf15.hpp" \
  "$OUT"/*startup_bias.csv "$OUT"/paired_*.csv > "$OUT/SHA256SUMS"
echo "PR2 Bundle B seed $SEED comparison written to $OUT"
