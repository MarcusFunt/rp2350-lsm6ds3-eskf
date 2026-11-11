#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 4 ]]; then
  echo "usage: run_pr2_comparison.sh PR1_PARENT_WORKTREE PR2_CANDIDATE_WORKTREE development|confirmation OUTPUT_DIRECTORY" >&2
  exit 2
fi

PARENT=$(cd "$1" && pwd)
CANDIDATE=$(cd "$2" && pwd)
SPLIT=$3
OUT=$(cd "$(dirname "$4")" && pwd)/$(basename "$4")
case "$SPLIT" in
  development|confirmation)
    CONFIG="$CANDIDATE/benchmarks/scenarios/pr2_confirmation_protocol_v2.json"
    ;;
  confirmation_v3)
    CONFIG="$CANDIDATE/benchmarks/scenarios/pr2_confirmation_protocol_v3.json"
    ;;
  *)
    echo "split must be development, confirmation or confirmation_v3" >&2
    exit 2
    ;;
esac
CXX=${CXX:-g++}

if [[ -e "$OUT" ]]; then
  echo "output directory already exists: $OUT" >&2
  exit 2
fi
if ! cmp -s "$PARENT/tools/pr1_baseline.cpp" "$CANDIDATE/tools/pr1_baseline.cpp"; then
  echo "PR1 frozen scenario generator differs between worktrees" >&2
  exit 2
fi

read -r FIRST LAST < <(python3 - "$CONFIG" "$SPLIT" <<'PY'
import json, sys
config=json.load(open(sys.argv[1], encoding="utf-8"))
seeds=config["seeds"][sys.argv[2]]
if seeds != list(range(seeds[0], seeds[-1]+1)):
    raise SystemExit("runner requires a contiguous frozen seed list")
print(seeds[0], seeds[-1])
PY
)

mkdir -p "$OUT/baseline-source/tools" "$OUT/candidate-source/tools"
mkdir -p "$OUT/baseline" "$OUT/candidate"
cp "$CANDIDATE/tools/pr1_baseline.cpp" "$OUT/baseline-source/tools/"
cp "$CANDIDATE/tools/pr2_confirmation.cpp" "$OUT/baseline-source/tools/"
cp "$PARENT/eskf15.hpp" "$OUT/baseline-source/eskf15.hpp"
cp "$CANDIDATE/tools/pr1_baseline.cpp" "$OUT/candidate-source/tools/"
cp "$CANDIDATE/tools/pr2_confirmation.cpp" "$OUT/candidate-source/tools/"
cp "$CANDIDATE/eskf15.hpp" "$OUT/candidate-source/eskf15.hpp"

FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror)
"$CXX" "${FLAGS[@]}" "$OUT/baseline-source/tools/pr2_confirmation.cpp" -o "$OUT/pr2_baseline"
"$CXX" "${FLAGS[@]}" "$OUT/candidate-source/tools/pr2_confirmation.cpp" -o "$OUT/pr2_candidate"
"$OUT/pr2_baseline" "$OUT/baseline" "$SPLIT" "$FIRST" "$LAST"
"$OUT/pr2_candidate" "$OUT/candidate" "$SPLIT" "$FIRST" "$LAST"
python3 "$CANDIDATE/tools/compare_pr2_results.py" \
  "$OUT/baseline" "$OUT/candidate" "$OUT/paired_comparison.csv"
cp "$CONFIG" "$OUT/protocol.json"
sha256sum "$OUT/protocol.json" "$CANDIDATE/tools/pr1_baseline.cpp" \
  "$CANDIDATE/tools/pr2_confirmation.cpp" "$CANDIDATE/eskf15.hpp" \
  "$OUT/baseline/imu_samples.bin" "$OUT/paired_comparison.csv" > "$OUT/SHA256SUMS"
echo "PR2 $SPLIT comparison written to $OUT"
