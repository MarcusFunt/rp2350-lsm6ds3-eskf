#!/usr/bin/env python3
"""Summarize deterministic, synthetic Bundle B trials and render SVG reports."""
import argparse
import csv
import html
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path


SCENARIOS = (
    'static', 'slow_yaw', 'lateral_accel', 'maneuver', 'vibration',
    'timing_jitter', 'stop_start', 'compound_motion',
)
MODELS = ('eskf_conservative', 'mahony', 'eskf_legacy')
MODEL_COLORS = {
    'eskf_conservative': '#1769aa',
    'mahony': '#d97706',
    'eskf_legacy': '#41845b',
}
METRICS = ('tilt_rms_deg', 'yaw_rms_deg')
PAIR_ORDER = (
    ('eskf_conservative', 'eskf_legacy'),
    ('eskf_conservative', 'mahony'),
    ('eskf_legacy', 'mahony'),
)
REQUIRED_COLUMNS = {
    'schema_version', 'metric_definition_version', 'scenario', 'trial_id',
    'sensor_profile', 'model', 'seed', 'startup_bias', 'expected', 'valid',
    'invalid', 'valid_fraction', 'valid_mask', 'tilt_rms_deg', 'yaw_rms_deg',
    'tilt_nees_count', 'gravity_nis_count',
    'uninitialized_samples', 'invalid_samples', 'degraded_samples',
    'faulted_samples', 'accel_clip_samples', 'gyro_clip_samples',
    'imu_stream_hash_fnv1a64', 'noise_draw_hash_fnv1a64',
}


def regularized_beta(x, a, b):
    """Regularized incomplete beta via a stable continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    def fraction(aa, bb, xx):
        qab = aa + bb
        qap = aa + 1.0
        qam = aa - 1.0
        tiny = 1e-300
        c = 1.0
        d = 1.0 - qab * xx / qap
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        result = d
        for m in range(1, 10001):
            m2 = 2 * m
            term = m * (bb - m) * xx / ((qam + m2) * (aa + m2))
            d = 1.0 + term * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + term / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            result *= d * c
            term = -(aa + m) * (qab + m) * xx / ((aa + m2) * (qap + m2))
            d = 1.0 + term * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + term / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            delta = d * c
            result *= delta
            if abs(delta - 1.0) < 3e-14:
                return result
        raise ArithmeticError('incomplete beta continued fraction did not converge')

    log_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * fraction(a, b, x) / a
    return 1.0 - front * fraction(b, a, 1.0 - x) / b


def student_t_cdf(value, degrees_freedom):
    x = degrees_freedom / (degrees_freedom + value * value)
    tail = 0.5 * regularized_beta(x, degrees_freedom / 2.0, 0.5)
    return 1.0 - tail if value >= 0.0 else tail


def student_t_critical_975(degrees_freedom):
    """Two-sided 95% Student-t critical value for df 1..199."""
    if not 1 <= degrees_freedom <= 199:
        raise ValueError('Student-t degrees of freedom must be between 1 and 199')
    low, high = 0.0, 1.0
    while student_t_cdf(high, degrees_freedom) < 0.975:
        high *= 2.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if student_t_cdf(middle, degrees_freedom) < 0.975:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def parse_finite(row, column):
    value = row.get(column)
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f'column {column!r} must be numeric or empty') from error
    if not math.isfinite(parsed):
        return None
    return parsed


def parse_integer(row, column, minimum=0):
    value = row.get(column)
    if value is None or not value.isdigit():
        raise ValueError(f'column {column!r} must contain a nonnegative integer')
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f'column {column!r} must be at least {minimum}')
    return parsed


def parse_bool(row, column):
    value = row.get(column, '').strip().lower()
    if value in ('1', 'true'):
        return True
    if value in ('0', 'false'):
        return False
    raise ValueError(f'column {column!r} must be 0 or 1')


def read(path):
    with open(path, newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f'CSV is missing required columns: {", ".join(sorted(missing))}')
        rows = list(reader)
    if not rows:
        raise ValueError('CSV contains no result rows')

    unique = set()
    for row in rows:
        if row['scenario'] not in SCENARIOS:
            raise ValueError(f"unknown scenario {row['scenario']!r}")
        if row['sensor_profile'] not in ('nominal', 'stress'):
            raise ValueError(f"unknown sensor profile {row['sensor_profile']!r}")
        if row['model'] not in MODELS:
            raise ValueError(f"unknown estimator {row['model']!r}")
        if parse_integer(row, 'schema_version') != 2:
            raise ValueError('only schema_version 2 is supported')
        if parse_integer(row, 'metric_definition_version') != 2:
            raise ValueError('only metric_definition_version 2 is supported')
        row['_trial_id'] = parse_integer(row, 'trial_id')
        row['_seed'] = parse_integer(row, 'seed')
        row['_startup_bias'] = parse_bool(row, 'startup_bias')
        row['_expected'] = parse_integer(row, 'expected', minimum=1)
        row['_valid'] = parse_integer(row, 'valid')
        row['_invalid'] = parse_integer(row, 'invalid')
        if row['_valid'] > row['_expected'] or row['_invalid'] != row['_expected'] - row['_valid']:
            raise ValueError('valid/invalid counts do not match expected samples')
        row['_valid_fraction'] = parse_finite(row, 'valid_fraction')
        fraction = row['_valid'] / row['_expected']
        if row['_valid_fraction'] is None or abs(row['_valid_fraction'] - fraction) > 1e-7:
            raise ValueError('valid_fraction does not match valid/expected')
        mask = row['valid_mask']
        if len(mask) != row['_expected'] or any(bit not in '01' for bit in mask):
            raise ValueError('valid_mask must contain one 0/1 character per expected sample')
        if mask.count('1') != row['_valid']:
            raise ValueError('valid_mask population does not match valid count')
        row['_valid_mask'] = mask
        row['_metrics'] = {metric: parse_finite(row, metric) for metric in METRICS}
        for column in ('uninitialized_samples', 'invalid_samples', 'degraded_samples',
                       'faulted_samples', 'accel_clip_samples', 'gyro_clip_samples',
                       'tilt_nees_count', 'gravity_nis_count'):
            row['_' + column] = parse_integer(row, column)
        if row['_tilt_nees_count'] > row['_valid'] or row['_gravity_nis_count'] > row['_valid']:
            raise ValueError('diagnostic sample counts exceed valid estimator samples')
        if row['_uninitialized_samples'] + row['_invalid_samples'] > row['_invalid']:
            raise ValueError('instrumented unavailable counts exceed invalid samples')
        stream_hash = row['imu_stream_hash_fnv1a64'].lower()
        if len(stream_hash) != 16 or any(ch not in '0123456789abcdef' for ch in stream_hash):
            raise ValueError('imu_stream_hash_fnv1a64 must be 16 hexadecimal digits')
        row['_stream_hash'] = stream_hash
        key = (row['scenario'], row['sensor_profile'], row['_startup_bias'],
               row['_trial_id'], row['model'])
        if key in unique:
            raise ValueError(f'duplicate trial row: {key}')
        unique.add(key)

    profiles = sorted({row['sensor_profile'] for row in rows})
    modes = sorted({row['_startup_bias'] for row in rows})
    if len(modes) != 1:
        raise ValueError('summarize one startup-bias mode per input CSV')
    mode = modes[0]
    group_keys = defaultdict(set)
    seeds = defaultdict(set)
    hashes = defaultdict(set)
    draw_hashes = defaultdict(set)
    for row in rows:
        group = (row['scenario'], row['sensor_profile'], mode, row['model'])
        group_keys[group].add(row['_trial_id'])
        seeds[(row['scenario'], row['sensor_profile'], mode, row['_trial_id'])].add(row['_seed'])
        hashes[(row['scenario'], row['sensor_profile'], mode, row['_trial_id'])].add(row['_stream_hash'])
        draw_hash = row['noise_draw_hash_fnv1a64'].lower()
        if len(draw_hash) != 16 or any(ch not in '0123456789abcdef' for ch in draw_hash):
            raise ValueError('noise_draw_hash_fnv1a64 must be 16 hexadecimal digits')
        draw_hashes[(row['scenario'], mode, row['_trial_id'])].add(draw_hash)
    trial_sets = list(group_keys.values())
    expected_trials = trial_sets[0]
    if not expected_trials or any(trial_ids != expected_trials for trial_ids in trial_sets):
        raise ValueError('scenario/profile/estimator groups have inconsistent trial IDs')
    if len(expected_trials) > 200 or expected_trials != set(range(len(expected_trials))):
        raise ValueError('trial IDs must be contiguous from 0 and there may be at most 200 trials')
    for scenario in SCENARIOS:
        for profile in profiles:
            for model in MODELS:
                group = (scenario, profile, mode, model)
                if group not in group_keys:
                    raise ValueError(f'missing required result group: {group}')
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError('estimators do not share the same IMU stream hash for a trial')
    if any(len(values) != 1 for values in seeds.values()):
        raise ValueError('estimators or profiles do not share the same seed for a trial')
    if any(len(values) != 1 for values in draw_hashes.values()):
        raise ValueError('nominal/stress profiles do not reuse the same Gaussian draw sequence')
    return rows


def validate_metadata(rows, metadata):
    if metadata.get('schema_version') != 2 or metadata.get('metric_definition_version') != 2:
        raise ValueError('metadata schema/metric versions must both be 2')
    if metadata.get('truth_integration_version') != 2:
        raise ValueError('only truth_integration_version 2 is supported')
    if metadata.get('seed_schedule_version') != 1:
        raise ValueError('unsupported seed schedule version in metadata')
    if metadata.get('scenario_set') != list(SCENARIOS):
        raise ValueError('metadata scenario_set does not match the v2 scenario list')
    if metadata.get('sample_rate_hz') != 200 or metadata.get('duration_seconds') != 16:
        raise ValueError('metadata timing must describe the 16-second, 200 Hz host simulation')
    trials = metadata.get('trials')
    if not isinstance(trials, int) or not 1 <= trials <= 200:
        raise ValueError('metadata trials must be an integer from 1 through 200')
    profiles = metadata.get('sensor_profiles')
    if not isinstance(profiles, list) or sorted(profiles) != sorted({row['sensor_profile'] for row in rows}):
        raise ValueError('metadata sensor_profiles do not match the CSV')
    startup = metadata.get('startup_bias')
    if not isinstance(startup, bool) or any(row['_startup_bias'] != startup for row in rows):
        raise ValueError('metadata startup_bias does not match the CSV')
    if any(row['_trial_id'] >= trials for row in rows):
        raise ValueError('CSV trial_id exceeds metadata trial count')
    if {row['_trial_id'] for row in rows} != set(range(trials)):
        raise ValueError('CSV is missing a trial listed in metadata')
    base_seed = metadata.get('base_seed')
    if not isinstance(base_seed, int) or not 0 <= base_seed <= 0xffffffff:
        raise ValueError('metadata base_seed is invalid')
    for row in rows:
        expected_seed = base_seed + 1009 * row['_trial_id'] + 103 * len(row['scenario'])
        if expected_seed > 0xffffffff or row['_seed'] != expected_seed:
            raise ValueError('CSV seed does not match metadata seed schedule')
    if not isinstance(metadata.get('configuration_hash_fnv1a64'), str):
        raise ValueError('metadata is missing the profile configuration hash')
    config_hash = metadata['configuration_hash_fnv1a64'].lower()
    if len(config_hash) != 16 or any(ch not in '0123456789abcdef' for ch in config_hash):
        raise ValueError('metadata configuration hash must be 16 hexadecimal digits')
    if (not isinstance(metadata.get('compiler'), str)
            or not isinstance(metadata.get('standard_library_version'), str)
            or not isinstance(metadata.get('git_sha'), str)
            or not isinstance(metadata.get('git_worktree_state'), str)):
        raise ValueError('metadata must record compiler, standard library, git_sha and working-tree state')
    return metadata


def load_metadata(csv_path, explicit_path=None):
    candidate = Path(explicit_path) if explicit_path else Path(str(csv_path) + '.metadata.json')
    if not candidate.exists():
        if explicit_path:
            raise ValueError(f'metadata sidecar does not exist: {candidate}')
        return None
    with candidate.open(encoding='utf-8') as source:
        return json.load(source)


def mean_ci(values):
    finite = [value for value in values if value is not None and math.isfinite(value)]
    n = len(finite)
    if n == 0:
        return {'mean': None, 'sd': None, 'ci95_low': None, 'ci95_high': None,
                'n_finite': 0, 'n_missing': len(values)}
    mean = statistics.mean(finite)
    if n < 2:
        return {'mean': mean, 'sd': None, 'ci95_low': None, 'ci95_high': None,
                'n_finite': n, 'n_missing': len(values) - n}
    sd = statistics.stdev(finite)
    half_width = student_t_critical_975(n - 1) * sd / math.sqrt(n)
    return {'mean': mean, 'sd': sd, 'ci95_low': mean - half_width,
            'ci95_high': mean + half_width, 'n_finite': n,
            'n_missing': len(values) - n}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['scenario'], row['sensor_profile'], row['_startup_bias'], row['model'])].append(row)
    group_summaries = []
    for (scenario, profile, startup_bias, model), group in sorted(groups.items()):
        metrics = {metric: mean_ci([row['_metrics'][metric] for row in group]) for metric in METRICS}
        expected = sum(row['_expected'] for row in group)
        valid = sum(row['_valid'] for row in group)
        group_summaries.append({
            'scenario': scenario, 'sensor_profile': profile, 'startup_bias': startup_bias,
            'model': model, 'trials': len(group), 'metrics': metrics,
            'availability': {
                'expected_samples': expected, 'valid_samples': valid,
                'invalid_samples': expected - valid,
                'valid_fraction': valid / expected if expected else None,
                'uninitialized_samples': sum(row['_uninitialized_samples'] for row in group),
                'invalid_output_samples': sum(row['_invalid_samples'] for row in group),
                'degraded_samples': sum(row['_degraded_samples'] for row in group),
                'faulted_samples': sum(row['_faulted_samples'] for row in group),
            },
            'diagnostics': {
                'tilt_nees_mean': mean_ci([parse_finite(row, 'tilt_nees_mean') for row in group]),
                'tilt_nees_coverage95_mean': mean_ci([parse_finite(row, 'tilt_nees_coverage95') for row in group]),
                'tilt_nees_sample_count': sum(row['_tilt_nees_count'] for row in group),
                'tilt_nees_sample_coverage': (sum(row['_tilt_nees_count'] for row in group) / valid) if valid else None,
                'gravity_nis_mean': mean_ci([parse_finite(row, 'gravity_nis_mean') for row in group]),
                'gravity_nis_sample_count': sum(row['_gravity_nis_count'] for row in group),
                'gravity_nis_sample_coverage': (sum(row['_gravity_nis_count'] for row in group) / valid) if valid else None,
                'gyro_bias_error_rps': mean_ci([parse_finite(row, 'gyro_bias_error_rps') for row in group]),
                'accel_clip_samples_mean': statistics.mean(row['_accel_clip_samples'] for row in group),
                'gyro_clip_samples_mean': statistics.mean(row['_gyro_clip_samples'] for row in group),
            },
        })

    by_identity = defaultdict(dict)
    for row in rows:
        identity = (row['scenario'], row['sensor_profile'], row['_startup_bias'], row['_trial_id'])
        by_identity[identity][row['model']] = row
    paired = []
    comparison_groups = sorted({(row['scenario'], row['sensor_profile'], row['_startup_bias']) for row in rows})
    for scenario, profile, startup_bias in comparison_groups:
        candidates = [identity for identity in by_identity
                      if identity[:3] == (scenario, profile, startup_bias)]
        for model_a, model_b in PAIR_ORDER:
            for metric in METRICS:
                deltas = []
                mask_mismatch = 0
                metric_missing = 0
                for identity in candidates:
                    a, b = by_identity[identity][model_a], by_identity[identity][model_b]
                    if a['_valid_mask'] != b['_valid_mask']:
                        mask_mismatch += 1
                        continue
                    av, bv = a['_metrics'][metric], b['_metrics'][metric]
                    if av is None or bv is None:
                        metric_missing += 1
                        continue
                    deltas.append(av - bv)
                stats = mean_ci(deltas)
                paired.append({
                    'kind': 'estimator', 'scenario': scenario, 'sensor_profile': profile,
                    'startup_bias': startup_bias, 'metric': metric,
                    'model_a': model_a, 'model_b': model_b,
                    'sign_convention': 'A minus B; negative means A lower error',
                    'n_expected': len(candidates), 'n_pairs': len(deltas),
                    'n_missing': len(candidates) - len(deltas),
                    'mask_mismatch_count': mask_mismatch,
                    'metric_missing_count': metric_missing, 'delta': stats,
                })

    profiles = {row['sensor_profile'] for row in rows}
    if profiles == {'nominal', 'stress'}:
        mode = rows[0]['_startup_bias']
        for scenario in SCENARIOS:
            for model in MODELS:
                for metric in METRICS:
                    nominal = {(row['_trial_id']): row for row in rows
                               if row['scenario'] == scenario and row['sensor_profile'] == 'nominal'
                               and row['_startup_bias'] == mode and row['model'] == model}
                    stress = {(row['_trial_id']): row for row in rows
                              if row['scenario'] == scenario and row['sensor_profile'] == 'stress'
                              and row['_startup_bias'] == mode and row['model'] == model}
                    ids = sorted(set(nominal) | set(stress))
                    deltas, mask_mismatch, missing = [], 0, 0
                    for trial_id in ids:
                        if trial_id not in nominal or trial_id not in stress:
                            missing += 1
                            continue
                        nrow, srow = nominal[trial_id], stress[trial_id]
                        if nrow['_valid_mask'] != srow['_valid_mask']:
                            mask_mismatch += 1
                            continue
                        nv, sv = nrow['_metrics'][metric], srow['_metrics'][metric]
                        if nv is None or sv is None:
                            missing += 1
                            continue
                        deltas.append(sv - nv)
                    paired.append({
                        'kind': 'stress_minus_nominal', 'scenario': scenario,
                        'sensor_profile': 'stress - nominal', 'startup_bias': mode,
                        'metric': metric, 'model_a': 'stress', 'model_b': 'nominal',
                        'sign_convention': 'stress minus nominal; positive means higher error under stress',
                        'n_expected': len(ids), 'n_pairs': len(deltas),
                        'n_missing': len(ids) - len(deltas), 'mask_mismatch_count': mask_mismatch,
                        'metric_missing_count': missing, 'delta': mean_ci(deltas),
                    })

    return group_summaries, paired


def fmt(value, digits=3):
    return 'N/A' if value is None or not math.isfinite(value) else f'{value:.{digits}f}'


def ci_text(stats):
    if stats['mean'] is None:
        return 'N/A'
    if stats['ci95_low'] is None:
        return f"{fmt(stats['mean'])} (CI unavailable, n={stats['n_finite']})"
    return f"{fmt(stats['mean'])} [{fmt(stats['ci95_low'])}, {fmt(stats['ci95_high'])}] (n={stats['n_finite']})"


def plot_files(summary, plot_dir, markdown_path=None):
    modes = sorted({row['startup_bias'] for row in summary})
    profiles = sorted({row['sensor_profile'] for row in summary})
    files = {}
    base = Path(plot_dir)
    for mode in modes:
        mode_name = 'verified_startup_bias' if mode else 'no_startup_bias'
        target_dir = base / mode_name if len(modes) > 1 else base
        target_dir.mkdir(parents=True, exist_ok=True)
        for profile in profiles:
            for metric in METRICS:
                short = 'tilt' if metric == 'tilt_rms_deg' else 'yaw'
                path = target_dir / f'{short}_rms_{profile}.svg'
                title = f'{short.title()} RMS by scenario — {profile}, {mode_name.replace("_", " ")}'
                write_svg(summary, mode, profile, metric, title, path)
                files[(mode, profile, short)] = path
    links = {}
    for key, path in files.items():
        if markdown_path:
            parent = Path(markdown_path).parent
            relative = os.path.relpath(path, parent if str(parent) else Path('.'))
        else:
            relative = str(path)
        links[key] = Path(relative).as_posix()
    return links


def write_svg(summary, startup_bias, profile, metric, title, path):
    width, height = 1480, 690
    left, right, top, bottom = 100, 32, 82, 220
    plot_width, plot_height = width - left - right, height - top - bottom
    rows = [row for row in summary if row['startup_bias'] == startup_bias
            and row['sensor_profile'] == profile]
    scenario_order = list(SCENARIOS)
    y_values = []
    for row in rows:
        stats = row['metrics'][metric]
        for key in ('mean', 'ci95_high'):
            if stats[key] is not None:
                y_values.append(stats[key])
    y_max = max(1.0, max(y_values, default=1.0) * 1.12)
    x_group = plot_width / len(scenario_order)
    offsets = {model: (-21 + 21 * index) for index, model in enumerate(MODELS)}

    def y_coord(value):
        clipped = min(y_max, max(0.0, value))
        return top + plot_height - clipped * plot_height / y_max

    title_xml = html.escape(title)
    label = 'RMS error (degrees)'
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f'<title>{title_xml}</title>',
        '<style>text{font-family:Arial,sans-serif;fill:#253044}.grid{stroke:#d9dee7;stroke-width:1}.axis{stroke:#596579;stroke-width:1.4}.ci{stroke-width:2.2}</style>',
        f'<text x="{width/2}" y="32" text-anchor="middle" font-size="22" font-weight="700">{title_xml}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        yy = y_coord(value)
        parts.append(f'<line class="grid" x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}"/>')
        parts.append(f'<text x="{left-12}" y="{yy+5:.1f}" text-anchor="end" font-size="13">{value:.2f}</text>')
    parts.extend([
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_height}"/>',
        f'<line class="axis" x1="{left}" y1="{top+plot_height}" x2="{width-right}" y2="{top+plot_height}"/>',
        f'<text transform="translate(26 {top+plot_height/2}) rotate(-90)" text-anchor="middle" font-size="15">{label}</text>',
        f'<text x="{left+plot_width/2}" y="{height-18}" text-anchor="middle" font-size="15">Motion scenario</text>',
    ])
    for index, scenario in enumerate(scenario_order):
        center = left + x_group * (index + 0.5)
        label_y = top + plot_height + 18
        parts.append(f'<text x="{center:.1f}" y="{label_y}" transform="rotate(48 {center:.1f} {label_y})" text-anchor="start" font-size="13">{html.escape(scenario)}</text>')
        for model in MODELS:
            row = next((item for item in rows if item['scenario'] == scenario and item['model'] == model), None)
            stats = row['metrics'][metric] if row else {'mean': None, 'ci95_low': None, 'ci95_high': None}
            xx = center + offsets[model]
            color = MODEL_COLORS[model]
            if stats['mean'] is None:
                parts.append(f'<text x="{xx}" y="{top+plot_height-8}" text-anchor="middle" font-size="10" fill="{color}">N/A</text>')
                continue
            mean_y = y_coord(stats['mean'])
            if stats['ci95_low'] is not None and stats['ci95_high'] is not None:
                low_y, high_y = y_coord(stats['ci95_low']), y_coord(stats['ci95_high'])
                parts.extend([
                    f'<line class="ci" stroke="{color}" x1="{xx}" y1="{low_y:.1f}" x2="{xx}" y2="{high_y:.1f}"/>',
                    f'<line class="ci" stroke="{color}" x1="{xx-5}" y1="{low_y:.1f}" x2="{xx+5}" y2="{low_y:.1f}"/>',
                    f'<line class="ci" stroke="{color}" x1="{xx-5}" y1="{high_y:.1f}" x2="{xx+5}" y2="{high_y:.1f}"/>',
                ])
            parts.append(f'<circle cx="{xx}" cy="{mean_y:.1f}" r="4.2" fill="{color}"/>')
    legend_y, legend_x = 59, width / 2 - 235
    for index, model in enumerate(MODELS):
        xx = legend_x + index * 220
        parts.append(f'<circle cx="{xx}" cy="{legend_y}" r="5" fill="{MODEL_COLORS[model]}"/>')
        parts.append(f'<text x="{xx+11}" y="{legend_y+5}" font-size="13">{html.escape(model)}</text>')
    valid_rows = [row['availability']['valid_fraction'] for row in rows]
    coverage = statistics.mean(valid_rows) if valid_rows else None
    ci_unavailable = any(row['metrics'][metric]['mean'] is not None
                         and row['metrics'][metric]['ci95_low'] is None for row in rows)
    ci_note = ' CI N/A when fewer than two finite trials.' if ci_unavailable else ''
    note = (f'Synthetic only; mean of per-trial RMS; whiskers are two-sided 95% Student-t CIs. '
            f'Mean valid-sample fraction: {fmt(coverage, 4)}. N/A marks unavailable data.{ci_note}')
    parts.append(f'<text x="{width/2}" y="{height-7}" text-anchor="middle" font-size="11">{html.escape(note)}</text>')
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(parts) + '\n', encoding='utf-8')


def markdown_report(document, source, links):
    modes = sorted({row['startup_bias'] for row in document['groups']})
    profiles = sorted({row['sensor_profile'] for row in document['groups']})
    lines = [
        '# Bundle B: synthetic estimator comparison', '',
        f"Source CSV: `{source}`. Schema v{document['schema_version']}; metric definition v{document['metric_definition_version']}; truth integration v{document['truth_integration_version']}.",
        'These are host-side synthetic results, not measured RP2350 or LSM6DS3 performance.', '',
        'The checked-in eight-trial intervals are preliminary descriptive uncertainty under the stated simulator assumptions; they are not real-world accuracy bounds.', '',
        'Each cell summarizes the arithmetic mean of per-trial RMS values with a two-sided 95% Student-t confidence interval and sample SD across trials. Missing values remain explicit.', '',
        '## Per-trial RMS summary', '',
        '| Scenario | Profile | Startup bias | Estimator | Trials | Tilt RMS mean [95% CI], deg | Tilt SD, deg | Yaw RMS mean [95% CI], deg | Yaw SD, deg | Valid fraction | Invalid samples |',
        '|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in document['groups']:
        tilt, yaw = row['metrics']['tilt_rms_deg'], row['metrics']['yaw_rms_deg']
        availability = row['availability']
        lines.append(
            f"| {row['scenario']} | {row['sensor_profile']} | {str(row['startup_bias']).lower()} | {row['model']} | {row['trials']} | "
            f"{ci_text(tilt)} | {fmt(tilt['sd'])} | {ci_text(yaw)} | {fmt(yaw['sd'])} | "
            f"{fmt(availability['valid_fraction'], 4)} | {availability['invalid_samples']} |"
        )
    metadata = document.get('metadata')
    lines.extend(['', '## Run provenance', ''])
    if metadata:
        lines.extend([
            f"- Seed: `{metadata['base_seed']}`; {metadata['trials']} trials per scenario/profile; schedule v{metadata['seed_schedule_version']} (`{metadata['seed_schedule']}`).",
            f"- Simulator rate and duration: {metadata['sample_rate_hz']} Hz, {metadata['duration_seconds']} s; truth integration v{metadata['truth_integration_version']}; startup bias: {str(metadata['startup_bias']).lower()}; profiles: {', '.join(metadata['sensor_profiles'])}.",
            f"- Compiler: `{metadata['compiler']}`; Git SHA: `{metadata['git_sha']}`; working tree: `{metadata['git_worktree_state']}`.",
            f"- C++ standard library: `{metadata['standard_library_version']}`.",
            f"- Sensor configuration hash (FNV-1a 64): `{metadata['configuration_hash_fnv1a64']}`.",
        ])
    else:
        lines.append('No metadata sidecar was supplied; use the simulator-generated sidecar to verify the intended trial count and configuration hash.')
    lines.extend(['', '## Paired differences', '',
                   'Estimator delta is `model A minus model B`; negative values mean A had lower error. Stress delta is `stress minus nominal`; positive values mean higher error under stress. A pair is included only when its `valid_mask` matches exactly. Mask mismatches are reported and excluded.', '',
                   '| Comparison | Scenario | Profile | Estimator/metric | Mean delta [95% CI] | SD | Pairs | Missing | Mask mismatches |',
                   '|---|---|---|---|---:|---:|---:|---:|---:|'])
    for row in document['paired_comparisons']:
        label = f"{row['model_a']} − {row['model_b']}" if row['kind'] == 'estimator' else 'stress − nominal'
        delta = row['delta']
        lines.append(
            f"| {row['kind']} | {row['scenario']} | {row['sensor_profile']} | {label} / {row['metric']} | {ci_text(delta)} | {fmt(delta['sd'])} | {row['n_pairs']} | {row['n_missing']} | {row['mask_mismatch_count']} |"
        )
    lines.extend(['', '## Availability and diagnostics', '',
                  'Unavailable estimates remain in the report through `expected`, `valid`, and `invalid` counts; they are never converted to zero. Uninitialized, invalid-output, degraded, and faulted sample totals are recorded where the estimator exposes those states. NEES/NIS also report diagnostic sample counts and coverage relative to valid estimates. They are diagnostics: gravity aiding reuses IMU data, so independent-noise chi-square coverage assumptions are not rigorous.', '',
                  '| Scenario | Profile | Estimator | NEES mean | NEES samples / valid | NEES sample coverage | NEES below 95% bound | NIS mean | NIS samples / valid | NIS sample coverage |',
                  '|---|---|---|---:|---:|---:|---:|---:|---:|---:|'])
    for row in document['groups']:
        diagnostic, availability = row['diagnostics'], row['availability']
        denominator = availability['valid_samples']
        lines.append(
            f"| {row['scenario']} | {row['sensor_profile']} | {row['model']} | "
            f"{fmt(diagnostic['tilt_nees_mean']['mean'])} | "
            f"{diagnostic['tilt_nees_sample_count']} / {denominator} | "
            f"{fmt(diagnostic['tilt_nees_sample_coverage'], 4)} | "
            f"{fmt(diagnostic['tilt_nees_coverage95_mean']['mean'], 4)} | "
            f"{fmt(diagnostic['gravity_nis_mean']['mean'])} | "
            f"{diagnostic['gravity_nis_sample_count']} / {denominator} | "
            f"{fmt(diagnostic['gravity_nis_sample_coverage'], 4)} |"
        )
    lines.extend(['',
                  '## Sensor profile assumptions', '',
                  'The nominal model retains the benchmark white-noise and random-walk equations. Stress terms are synthetic engineering assumptions, not measured or calibrated LSM6DS3 characteristics. Per sample: ideal motion → axis scale/misalignment → initial and random-walk bias plus thermal bias and white noise → clipping → quantization → one shared `Imu` record for all estimators. The reported gyro-bias error compares against additive injected bias; scale and cross-axis errors can also affect the estimate.', '',
                  '| Sensor parameter | Value | Unit |', '|---|---|---|'])
    if metadata:
        parameters = metadata['sensor_model_parameters']
        lines.extend([
            f"| Accelerometer scale/misalignment matrix | `{json.dumps(parameters['accel_matrix'], separators=(',', ':'))}` | dimensionless |",
            f"| Gyroscope scale/misalignment matrix | `{json.dumps(parameters['gyro_matrix'], separators=(',', ':'))}` | dimensionless |",
            f"| Temperature ramp | 0 to +{fmt(parameters['temperature_ramp']['rise_c'], 3)} over {fmt(parameters['temperature_ramp']['duration_s'], 3)} s, beginning at {fmt(parameters['temperature_ramp']['start_s'], 3)} s | °C |",
            f"| Temperature bias coefficients, accel | `{json.dumps(parameters['accel_temperature_bias_mps2_per_c'], separators=(',', ':'))}` | m/s²/°C |",
            f"| Temperature bias coefficients, gyro | `{json.dumps(parameters['gyro_temperature_bias_rps_per_c'], separators=(',', ':'))}` | rad/s/°C |",
            f"| Per-axis clipping limit, accel | ±{fmt(parameters['accel_clip_limit_mps2'], 3)} | m/s² |",
            f"| Per-axis clipping limit, gyro | ±{fmt(parameters['gyro_clip_limit_rps'], 3)} | rad/s |",
            f"| Quantization step, accel | {fmt(parameters['accel_quantum_mps2'], 6)} | m/s²/count |",
            f"| Quantization step, gyro | {fmt(parameters['gyro_quantum_rps'], 6)} | rad/s/count |",
            f"| White-noise density, accel | {fmt(parameters['accel_white_noise_density_mps2_per_sqrt_hz'], 6)} | m/s²/√Hz |",
            f"| White-noise density, gyro | {fmt(parameters['gyro_white_noise_density_rps_per_sqrt_hz'], 6)} | rad/s/√Hz |",
            f"| Bias random walk, accel | {fmt(parameters['accel_bias_walk_mps2_per_sqrt_s'], 6)} | m/s²/√s |",
            f"| Bias random walk, gyro | {fmt(parameters['gyro_bias_walk_rps_per_sqrt_s'], 6)} | rad/s/√s |",
        ])
    else:
        lines.append('| Parameter values | Not available without the metadata sidecar | — |')
    lines.extend(['',
                  'The limits are deliberately illustrative and are not sensor full-scale specifications. Ordinary scenarios should remain below them; saturation behavior is tested with isolated extreme input.', '',
                  '## Metric and interpretation limits', '',
                  '- Metric definition v2 computes inclination from gravity/up vectors in the body frame. The historical v1 `tilt_rms_deg` used world-frame body-Z-axis deviation and can include common world-yaw error, so v1 and v2 RMS values are not directly comparable.',
                  '- Yaw RMS is relative to the synthetic initial yaw gauge. Gravity alone cannot observe absolute yaw or heading.',
                  '- The initial 2 s are stationary by the known scenario definition. This is not an IMU-only detector. Startup bias calibration is opt-in.',
                  '- The host simulator runs at 200 Hz for 16 s. Target firmware configures the IMU at 208 Hz; this benchmark does not claim hardware timing or accuracy.',
                  '- Truth integration v2 uses midpoint angular rates. This changes some time-varying-rotation accelerometer samples relative to the historical endpoint-rate v1 simulator even though the six original Gaussian draw sequences are preserved. Historical v1/v2 performance values are therefore not directly comparable.',
                  '- Translation is represented by acceleration commands for specific-force generation; position and velocity are not part of this attitude benchmark.',
                  '- A simulator can expose code defects and model assumptions. It cannot establish physical attitude accuracy, controller safety, or actual RP2350/LSM6DS3 timing.', '',
                  ])
    if links:
        lines.extend(['', '## Plots', ''])
        for mode in modes:
            mode_name = 'verified_startup_bias' if mode else 'no_startup_bias'
            lines.extend([f'### {mode_name.replace("_", " ")}', ''])
            for profile in profiles:
                lines.extend([
                    f'#### {profile} profile', '',
                    f"![Tilt RMS across scenarios — {profile}, {mode_name.replace('_', ' ')}]({links[(mode, profile, 'tilt')]})",
                    '',
                    f"![Yaw RMS across scenarios — {profile}, {mode_name.replace('_', ' ')}]({links[(mode, profile, 'yaw')]})",
                    '',
                ])
    else:
        lines.extend(['', '## Plots', '', 'Plot generation was not requested for this summary.', ''])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', help='per-trial results CSV (metric definition v2)')
    parser.add_argument('--markdown', help='write a Markdown report')
    parser.add_argument('--json', dest='json_path', help='write strict JSON summary')
    parser.add_argument('--plots-dir', help='write profile and startup-mode SVG plots')
    parser.add_argument('--metadata', help='metadata sidecar written by the simulator')
    args = parser.parse_args(argv)
    try:
        rows = read(args.csv)
        metadata = load_metadata(args.csv, args.metadata)
        if metadata is not None:
            validate_metadata(rows, metadata)
        groups, paired = summarize(rows)
        modes = {row['_startup_bias'] for row in rows}
        document = {
            'schema_version': 2,
            'metric_definition_version': 2,
            'truth_integration_version': metadata.get('truth_integration_version', 2) if metadata else 2,
            'source_csv': Path(args.csv).name,
            'startup_bias': next(iter(modes)),
            'sample_rate_hz': 200,
            'duration_seconds': 16,
            'metadata': metadata,
            'ci_method': 'two-sided 95% Student-t interval over per-trial metric values',
            'grouping': ['scenario', 'sensor_profile', 'startup_bias', 'model'],
            'groups': groups,
            'paired_comparisons': paired,
        }
        links = {}
        if args.plots_dir:
            links = plot_files(groups, args.plots_dir, args.markdown)
        if args.json_path:
            with open(args.json_path, 'w', encoding='utf-8', newline='\n') as target:
                json.dump(document, target, indent=2, sort_keys=True, allow_nan=False)
                target.write('\n')
        if args.markdown:
            Path(args.markdown).write_text(markdown_report(document, Path(args.csv).name, links), encoding='utf-8')
        if not args.json_path and not args.markdown:
            json.dump(document, sys.stdout, indent=2, sort_keys=True, allow_nan=False)
            sys.stdout.write('\n')
    except (OSError, ValueError, ArithmeticError, KeyError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
