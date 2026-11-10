#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${BUNDLE_B_BUILD_DIR:-${TMPDIR:-/tmp}/rp2350_bundle_b_checks}"
mkdir -p "$OUT"
CXX="${CXX:-g++}"
FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror)

"$CXX" "${FLAGS[@]}" tests/test_bundle_b.cpp -o "$OUT/test_bundle_b"
"$OUT/test_bundle_b"
"$CXX" "${FLAGS[@]}" tests/test_bundle_b_sim.cpp -o "$OUT/test_bundle_b_sim"
"$OUT/test_bundle_b_sim"
python3 tests/test_summarize_bundle_b.py
"$CXX" "${FLAGS[@]}" tools/benchmark_bundle_b.cpp -o "$OUT/benchmark_bundle_b"

"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --sensor-profile both --output "$OUT/no_bias.csv"
"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --startup-bias --sensor-profile both --output "$OUT/with_bias.csv"
"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --startup-bias --sensor-profile both --output "$OUT/repeated.csv"
cmp "$OUT/with_bias.csv" "$OUT/repeated.csv"
cmp "$OUT/with_bias.csv.metadata.json" "$OUT/repeated.csv.metadata.json"

"$OUT/benchmark_bundle_b" --trials 1 --seed 20261110 --sensor-profile both --output "$OUT/single_both.csv"
"$OUT/benchmark_bundle_b" --trials 1 --seed 20261110 --sensor-profile nominal --output "$OUT/single_nominal.csv"
"$OUT/benchmark_bundle_b" --trials 1 --seed 20261110 --sensor-profile stress --output "$OUT/single_stress.csv"
for args in \
  "--sensor-profile invalid" \
  "--trials nope" \
  "--trials -1" \
  "--trials 0" \
  "--trials 201" \
  "--seed 12x" \
  "--seed 4294967295 --trials 1"; do
  if invalid_output=$("$OUT/benchmark_bundle_b" $args --output "$OUT/invalid.csv" 2>&1); then
    echo "FAIL invalid arguments were accepted: $args" >&2
    exit 1
  fi
  if [[ "$invalid_output" != *"Usage:"* ]]; then
    echo "FAIL invalid arguments did not print usage: $args" >&2
    exit 1
  fi
done

python3 tools/summarize_bundle_b.py "$OUT/no_bias.csv" \
  --markdown "$OUT/no_bias.md" --json "$OUT/no_bias.json" \
  --metadata "$OUT/no_bias.csv.metadata.json" --plots-dir "$OUT/plots/no_startup_bias"
python3 tools/summarize_bundle_b.py "$OUT/with_bias.csv" \
  --markdown "$OUT/with_bias.md" --json "$OUT/with_bias.json" \
  --metadata "$OUT/with_bias.csv.metadata.json" --plots-dir "$OUT/plots/verified_startup_bias"
mkdir -p "$OUT/plots_snapshot"
cp "$OUT/plots/verified_startup_bias/"*.svg "$OUT/plots_snapshot/"
python3 tools/summarize_bundle_b.py "$OUT/single_both.csv" \
  --json "$OUT/single.json" --metadata "$OUT/single_both.csv.metadata.json"
python3 tools/summarize_bundle_b.py "$OUT/single_both.csv" \
  --markdown "$OUT/markdown_only.md" --metadata "$OUT/single_both.csv.metadata.json"
python3 - "$OUT/markdown_only.md" <<'PY'
import pathlib,sys
assert 'Plot generation was not requested' in pathlib.Path(sys.argv[1]).read_text()
print('PASS optional plot generation with Markdown-only output')
PY
python3 tools/summarize_bundle_b.py "$OUT/with_bias.csv" \
  --markdown "$OUT/with_bias_repeat.md" --json "$OUT/with_bias_repeat.json" \
  --metadata "$OUT/with_bias.csv.metadata.json" --plots-dir "$OUT/plots/verified_startup_bias"
cmp "$OUT/with_bias.json" "$OUT/with_bias_repeat.json"
cmp "$OUT/with_bias.md" "$OUT/with_bias_repeat.md"
for name in tilt_rms_nominal.svg tilt_rms_stress.svg yaw_rms_nominal.svg yaw_rms_stress.svg; do
  cmp "$OUT/plots_snapshot/$name" "$OUT/plots/verified_startup_bias/$name"
done

python3 - "$OUT/no_bias.csv" "$OUT/with_bias.csv" "$OUT/single_both.csv" \
  "$OUT/single_nominal.csv" "$OUT/single_stress.csv" "$OUT/no_bias.json" \
  "$OUT/with_bias.json" "$OUT/single.json" "$OUT/no_bias.md" "$OUT/with_bias.md" \
  "$OUT/plots/no_startup_bias" "$OUT/plots/verified_startup_bias" <<'PY'
import csv, json, math, pathlib, statistics, sys
from collections import Counter
from xml.etree import ElementTree as ET

scenarios = {'static','slow_yaw','lateral_accel','maneuver','vibration','timing_jitter','stop_start','compound_motion'}
profiles = {'nominal','stress'}
models = {'eskf_conservative','mahony','eskf_legacy'}

def strict_json(path):
    def reject(value):
        raise AssertionError(f'non-standard JSON constant {value}')
    return json.loads(pathlib.Path(path).read_text(), parse_constant=reject)

def read(path):
    with open(path, newline='', encoding='utf-8') as source:
        return list(csv.DictReader(source))

def collect(path, trials, selected_profiles=profiles):
    rows = read(path)
    assert len(rows) == trials * len(scenarios) * len(selected_profiles) * len(models), (path, len(rows))
    assert {row['scenario'] for row in rows} == scenarios
    assert {row['sensor_profile'] for row in rows} == selected_profiles
    assert {row['model'] for row in rows} == models
    assert {row['schema_version'] for row in rows} == {'2'}
    assert {row['metric_definition_version'] for row in rows} == {'2'}
    keys = [(row['scenario'], row['sensor_profile'], row['startup_bias'], row['trial_id'], row['model']) for row in rows]
    assert len(set(keys)) == len(keys)
    counts = Counter((row['scenario'], row['sensor_profile'], row['startup_bias'], row['model']) for row in rows)
    assert set(counts.values()) == {trials}
    assert {int(row['trial_id']) for row in rows} == set(range(trials))
    streams = {}
    clips = {}
    for row in rows:
        expected, valid, invalid = int(row['expected']), int(row['valid']), int(row['invalid'])
        assert expected > 0 and 0 <= valid <= expected and invalid == expected-valid
        assert abs(float(row['valid_fraction']) - valid/expected) < 1e-7
        assert len(row['valid_mask']) == expected and set(row['valid_mask']) <= {'0','1'}
        assert row['valid_mask'].count('1') == valid
        assert math.isfinite(float(row['tilt_rms_deg'])) and math.isfinite(float(row['yaw_rms_deg']))
        assert int(row['accel_clip_samples']) >= 0 and int(row['gyro_clip_samples']) >= 0
        assert len(row['noise_draw_hash_fnv1a64']) == 16
        identity = (row['scenario'], row['sensor_profile'], row['startup_bias'], row['trial_id'])
        streams.setdefault(identity, set()).add(row['imu_stream_hash_fnv1a64'])
        clips.setdefault(identity, set()).add((row['accel_clip_samples'],row['gyro_clip_samples']))
    assert all(len(value) == 1 for value in streams.values())
    assert all(len(value) == 1 for value in clips.values())
    draw_hashes = {}
    for row in rows:
        key = (row['scenario'],row['startup_bias'],row['trial_id'])
        draw_hashes.setdefault(key,set()).add(row['noise_draw_hash_fnv1a64'])
    assert all(len(value) == 1 for value in draw_hashes.values()), 'profiles must reuse identical Gaussian draws'
    return rows

no_bias = collect(sys.argv[1], 5)
with_bias = collect(sys.argv[2], 5)
single = collect(sys.argv[3], 1)
nominal = collect(sys.argv[4], 1, {'nominal'})
stress = collect(sys.argv[5], 1, {'stress'})

def keyed(rows):
    return {(r['scenario'],r['sensor_profile'],r['trial_id'],r['model']):r for r in rows}

both_map = keyed(single)
for subset, profile in ((nominal,'nominal'),(stress,'stress')):
    isolated = keyed(subset)
    expected = {key:value for key,value in both_map.items() if key[1] == profile}
    assert isolated == expected, f'{profile} alone differs from both profile output'
assert all(int(row['accel_clip_samples']) == 0 and int(row['gyro_clip_samples']) == 0 for row in nominal + stress), 'ordinary scenarios must not be forced to clip'
assert all(int(row['accel_clip_samples']) == 0 and int(row['gyro_clip_samples']) == 0 for row in no_bias + with_bias), 'nominal/stress coverage includes no ordinary clipping'

for metadata_path, csv_rows, expected_profiles in (
    (sys.argv[1]+'.metadata.json',no_bias,profiles),
    (sys.argv[2]+'.metadata.json',with_bias,profiles),
    (sys.argv[3]+'.metadata.json',single,profiles),
):
    metadata = strict_json(metadata_path)
    assert metadata['schema_version'] == 2 and metadata['metric_definition_version'] == 2
    assert metadata['truth_integration_version'] == 2
    assert metadata['sample_rate_hz'] == 200 and metadata['duration_seconds'] == 16
    assert metadata['sensor_profiles'] == sorted(expected_profiles)
    assert metadata['trials'] == len({row['trial_id'] for row in csv_rows})
    assert metadata['git_sha'] and metadata['configuration_hash_fnv1a64'] and metadata['standard_library_version']

golden = strict_json('benchmarks/historical_v1/nominal_noise_draw_hashes.json')
run_metadata = strict_json(sys.argv[1]+'.metadata.json')
if (run_metadata['compiler'] == golden['compiler_version']
        and run_metadata['standard_library_version'] == golden['standard_library_version']):
    for scene, expected_hash in golden['scenario_hashes'].items():
        row = next(r for r in no_bias if r['scenario']==scene and r['sensor_profile']=='nominal' and r['trial_id']=='0' and r['model']=='eskf_conservative')
        assert row['noise_draw_hash_fnv1a64'] == expected_hash, (scene,row['noise_draw_hash_fnv1a64'],expected_hash)
else:
    print('SKIP compiler/standard-library-specific historical Gaussian draw golden on this toolchain')

def mean(rows, scenario, profile, model, column):
    return statistics.mean(float(row[column]) for row in rows if row['scenario']==scenario and row['sensor_profile']==profile and row['model']==model)

assert mean(with_bias,'lateral_accel','nominal','eskf_conservative','tilt_rms_deg') < mean(with_bias,'lateral_accel','nominal','eskf_legacy','tilt_rms_deg')
assert mean(with_bias,'lateral_accel','nominal','eskf_conservative','tilt_rms_deg') < mean(with_bias,'lateral_accel','nominal','mahony','tilt_rms_deg')
assert mean(with_bias,'static','nominal','eskf_conservative','yaw_rms_deg') < mean(no_bias,'static','nominal','eskf_conservative','yaw_rms_deg')

for path, expected_groups, mode in ((sys.argv[6],8*2*3,False),(sys.argv[7],8*2*3,True)):
    document = strict_json(path)
    assert len(document['groups']) == expected_groups
    assert document['startup_bias'] is mode
    assert len(document['paired_comparisons']) == 8*2*3*2 + 8*3*2
    assert all(group['metrics'][metric]['n_finite'] == 5 for group in document['groups'] for metric in ('tilt_rms_deg','yaw_rms_deg'))
    assert all(group['metrics'][metric]['n_missing'] == 0 for group in document['groups'] for metric in ('tilt_rms_deg','yaw_rms_deg'))
    sample = next(group for group in document['groups'] if group['scenario']=='static' and group['sensor_profile']=='nominal' and group['model']=='eskf_conservative')
    source_rows = with_bias if mode else no_bias
    values = [float(row['tilt_rms_deg']) for row in source_rows if row['scenario']=='static' and row['sensor_profile']=='nominal' and row['model']=='eskf_conservative']
    assert abs(sample['metrics']['tilt_rms_deg']['mean'] - statistics.mean(values)) < 1e-10
    assert sample['metrics']['tilt_rms_deg']['ci95_low'] < sample['metrics']['tilt_rms_deg']['mean'] < sample['metrics']['tilt_rms_deg']['ci95_high']

one = strict_json(sys.argv[8])
assert len(one['groups']) == 8*2*3
assert all(group['metrics'][metric]['n_finite']==1 and group['metrics'][metric]['n_missing']==0 and group['metrics'][metric]['sd'] is None and group['metrics'][metric]['ci95_low'] is None for group in one['groups'] for metric in ('tilt_rms_deg','yaw_rms_deg'))
assert all(pair['delta']['n_finite']==1 and pair['delta']['ci95_low'] is None for pair in one['paired_comparisons'])

for markdown_path, plot_dir in ((sys.argv[9],pathlib.Path(sys.argv[11])),(sys.argv[10],pathlib.Path(sys.argv[12]))):
    markdown = pathlib.Path(markdown_path).read_text()
    assert 'Student-t' in markdown and 'v1' in markdown and 'yaw' in markdown.lower()
    assert 'Mask mismatches' in markdown
    for profile in profiles:
        for metric in ('tilt','yaw'):
            link = f'{metric}_rms_{profile}.svg'
            assert link in markdown
            path = plot_dir / link
            root = ET.parse(path).getroot()
            assert root.attrib['viewBox'] == '0 0 1480 690'
            text = ''.join(root.itertext())
            assert 'Motion scenario' in text and 'RMS error (degrees)' in text and 'eskf_conservative' in text
            assert root.findall(".//*[@class='ci']"), path

print('PASS Bundle B profiles, paired coverage, metadata, intervals and eight SVGs')
PY

# A deliberately missing estimate remains explicit in summary JSON and invalidates
# paired claims for a mismatched evaluation window.
python3 - "$OUT/single_both.csv" "$OUT/missing.csv" <<'PY'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as source:
    reader=csv.DictReader(source); rows=list(reader); fields=reader.fieldnames
row=next(item for item in rows if item['scenario']=='static' and item['sensor_profile']=='nominal' and item['model']=='eskf_conservative')
row['valid']='0'; row['invalid']=row['expected']; row['valid_fraction']='0'; row['valid_mask']='0'*int(row['expected'])
row['tilt_rms_deg']=''; row['yaw_rms_deg']=''
row['tilt_nees_mean']=''; row['tilt_nees_coverage95']=''; row['tilt_nees_count']='0'
row['gravity_nis_mean']=''; row['gravity_nis_count']='0'
with open(sys.argv[2],'w',newline='',encoding='utf-8') as target:
    writer=csv.DictWriter(target,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
PY
python3 tools/summarize_bundle_b.py "$OUT/missing.csv" --json "$OUT/missing.json"
python3 - "$OUT/missing.json" <<'PY'
import json,sys
document=json.load(open(sys.argv[1]))
group=next(row for row in document['groups'] if row['scenario']=='static' and row['sensor_profile']=='nominal' and row['model']=='eskf_conservative')
assert group['metrics']['tilt_rms_deg']['n_finite']==0 and group['metrics']['tilt_rms_deg']['n_missing']==1
pair=next(row for row in document['paired_comparisons'] if row['scenario']=='static' and row['sensor_profile']=='nominal' and row['model_a']=='eskf_conservative' and row['model_b']=='eskf_legacy' and row['metric']=='tilt_rms_deg')
assert pair['n_pairs']==0 and pair['n_missing']==1 and pair['mask_mismatch_count']==1
print('PASS missing estimates stay visible and invalidate unmatched pairs')
PY

if [[ "${BUNDLE_B_SANITIZERS:-0}" == "1" ]]; then
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=address,undefined tests/test_bundle_b_sim.cpp -o "$OUT/test_bundle_b_sim_san"
  ASAN_OPTIONS=detect_leaks=1 "$OUT/test_bundle_b_sim_san"
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=undefined tools/benchmark_bundle_b.cpp -o "$OUT/benchmark_bundle_b_ubsan"
  "$OUT/benchmark_bundle_b_ubsan" --trials 2 --startup-bias --sensor-profile both --output "$OUT/ubsan.csv"
  echo 'PASS Bundle B sanitizers'
fi
