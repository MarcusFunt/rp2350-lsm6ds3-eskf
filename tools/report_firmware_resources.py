#!/usr/bin/env python3
"""Summarize target section sizes and GCC per-function stack estimates."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def parse_stack_usage_record(line):
    """Parse one GCC .su line without splitting C++ scopes or drive letters."""
    fields = line.split("\t")
    if len(fields) < 3 or not fields[1].isdigit():
        return None
    match = re.match(r"^(.*):[0-9]+:[0-9]+:(.*)$", fields[0])
    if match is None:
        return None
    return {
        "function": match.group(2),
        "bytes": int(fields[1]),
        "classification": fields[2],
        "source_record": fields[0],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    build = args.build_dir
    elf = build / "rp2350_lsm6ds3_fusion.elf"
    map_file = build / "rp2350_lsm6ds3_fusion.map"
    binary = build / "rp2350_lsm6ds3_fusion.bin"
    if not elf.is_file() or not map_file.is_file() or not binary.is_file():
        raise SystemExit(f"missing ELF, BIN, or linker map in {build}")

    size_output = subprocess.run(
        ["arm-none-eabi-size", "-A", str(elf)], check=True,
        text=True, capture_output=True
    ).stdout
    sections = {name: 0 for name in (".text", ".rodata", ".data", ".bss")}
    for line in size_output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in sections:
            sections[fields[0]] = int(fields[1], 0)

    map_text = map_file.read_text(errors="replace")
    memory = {}
    for name, origin, length in re.findall(
        r"^\s*(FLASH|RAM)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)",
        map_text, re.MULTILINE
    ):
        memory[name] = {"origin": int(origin, 16), "capacity_bytes": int(length, 16)}
    if "FLASH" not in memory or "RAM" not in memory:
        raise SystemExit("linker map is missing FLASH/RAM memory-region capacities")
    static_ram = sections[".data"] + sections[".bss"]
    flash_image_bytes = binary.stat().st_size

    records = []
    for su_file in sorted(build.rglob("*.su")):
        for line in su_file.read_text(errors="replace").splitlines():
            record = parse_stack_usage_record(line)
            if record is not None:
                records.append(record)
    if not records:
        raise SystemExit(f"no GCC stack-usage records found under {build}")
    maximum = max(records, key=lambda record: record["bytes"])
    report = {
        "label": args.label,
        "elf": elf.name,
        "link_map": map_file.name,
        "link_map_present": True,
        "flash_image_bytes": flash_image_bytes,
        "flash_capacity_bytes": memory["FLASH"]["capacity_bytes"],
        "flash_headroom_bytes": memory["FLASH"]["capacity_bytes"] - flash_image_bytes,
        "section_bytes": sections,
        "main_ram_capacity_bytes": memory["RAM"]["capacity_bytes"],
        "static_ram_bytes_data_plus_bss": static_ram,
        "main_ram_remaining_after_data_bss_bytes": memory["RAM"]["capacity_bytes"] - static_ram,
        "heap_usage": "NOT_MEASURED; application and library allocation paths require a separate audit",
        "stack_usage": {
            "record_count": len(records),
            "max_single_function_frame_bytes": maximum["bytes"],
            "max_frame_function": maximum["function"],
            "max_frame_classification": maximum["classification"],
            "files": [str(path.relative_to(build)) for path in sorted(build.rglob("*.su"))],
            "note": "Compiler per-function frame estimates; not call-chain stack or measured high-water.",
        },
        "size_output": size_output,
    }
    output = build / "resource_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    compact = {key: value for key, value in report.items() if key != "size_output"}
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
