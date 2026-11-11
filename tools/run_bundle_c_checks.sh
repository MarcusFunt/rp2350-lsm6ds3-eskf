#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tests/test_firmware_resource_report.py
CXX="${CXX:-g++}"
OUT="${TMPDIR:-/tmp}/rp2350_bundle_c_checks"
mkdir -p "$OUT"
FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic)
if [[ "${BUNDLE_C_SANITIZERS:-0}" == 1 ]]; then FLAGS+=(-fsanitize=address,undefined -fno-omit-frame-pointer -O1 -g); fi
"$CXX" "${FLAGS[@]}" tests/test_bundle_c.cpp -o "$OUT/test_bundle_c"
"$OUT/test_bundle_c"
"$CXX" "${FLAGS[@]}" tools/binary_log_tool.cpp -o "$OUT/binary_log_tool"
"$OUT/binary_log_tool" generate "$OUT/fixture.bin"
"$OUT/binary_log_tool" replay "$OUT/fixture.bin" 1234 > "$OUT/replayed.csv"
python3 - "$OUT/replayed.csv" "$OUT/fixture.bin" "$OUT/binary_log_tool" <<'PY'
import csv, struct, subprocess, sys, zlib
from pathlib import Path
rows=list(csv.DictReader(open(sys.argv[1],newline='')))
assert len(rows)==1200,len(rows)
assert sum(int(r['valid']) for r in rows)>1000
assert rows[600]['sequence_gap_before']=='1',rows[600]
assert rows[600]['dropped_records_before']=='1',rows[600]
assert sum(int(r['sequence_gap_before']) for r in rows)==1
assert sum(int(r['dropped_records_before']) for r in rows)==1
f=Path(sys.argv[2]); exe=sys.argv[3]
assert subprocess.run([exe,'replay',str(f),'999'],capture_output=True).returncode==5
summary=subprocess.run([exe,'replay',str(f),'1234'],capture_output=True,text=True,check=True).stderr
assert 'replayed=1200' in summary and 'sequence_gaps=1' in summary and 'explicit_drops=1' in summary,summary
legacy=bytearray(f.read_bytes())
struct.pack_into('<H',legacy,8,1)
struct.pack_into('<I',legacy,28,zlib.crc32(legacy[:28]) & 0xffffffff)
for offset in range(32,len(legacy),64):
    record=legacy[offset:offset+64]
    record[:4]=b'IUM1';struct.pack_into('<H',record,4,1)
    flags=struct.unpack_from('<H',record,6)[0]
    struct.pack_into('<H',record,6,0);struct.pack_into('<I',record,28,flags)
    struct.pack_into('<I',record,60,zlib.crc32(record[:60]) & 0xffffffff)
    legacy[offset:offset+64]=record
legacy_path=f.with_suffix('.v1.bin');legacy_path.write_bytes(legacy)
legacy_summary=subprocess.run([exe,'replay',str(legacy_path),'1234'],capture_output=True,text=True,check=True).stderr
assert 'replayed=1200' in legacy_summary and 'sequence_gaps=1' in legacy_summary and 'explicit_drops=0' in legacy_summary,legacy_summary
wrong_version=bytearray(legacy)
struct.pack_into('<H',wrong_version,8,2)
struct.pack_into('<I',wrong_version,28,zlib.crc32(wrong_version[:28]) & 0xffffffff)
wrong_version_path=f.with_suffix('.version-mismatch.bin');wrong_version_path.write_bytes(wrong_version)
assert subprocess.run([exe,'replay',str(wrong_version_path),'1234'],capture_output=True).returncode==7
duplicate=bytearray(f.read_bytes())
duplicate_offset=32+64*11
struct.pack_into('<I',duplicate,duplicate_offset+24,11)
struct.pack_into('<I',duplicate,duplicate_offset+60,zlib.crc32(duplicate[duplicate_offset:duplicate_offset+60]) & 0xffffffff)
duplicate_path=f.with_suffix('.duplicate-sequence.bin');duplicate_path.write_bytes(duplicate)
assert subprocess.run([exe,'replay',str(duplicate_path),'1234'],capture_output=True).returncode==7
b=bytearray(f.read_bytes());b[32+64*10+33]^=0x10
p=f.with_suffix('.corrupted.bin');p.write_bytes(b)
assert subprocess.run([exe,'replay',str(p),'1234'],capture_output=True).returncode==7
p=f.with_suffix('.truncated.bin');p.write_bytes(f.read_bytes()[:-3])
assert subprocess.run([exe,'replay',str(p),'1234'],capture_output=True).returncode==6
print('PASS v1/v2 replay compatibility, loss provenance, mismatch / CRC / truncation rejection')
PY
