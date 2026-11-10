import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.summarize_bundle_b import read


def test_protocol_v1_csv_is_rejected():
    scenarios = ["static", "slow_yaw", "lateral_accel", "maneuver", "vibration", "timing_jitter"]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "protocol_v1.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["scenario", "model"])
            writer.writeheader()
            writer.writerows({"scenario": scenario, "model": "eskf"} for scenario in scenarios)
        try:
            read(path)
        except ValueError as error:
            assert "protocol v2" in str(error)
        else:
            raise AssertionError("protocol-v1 results must not be silently summarized as v2")


if __name__ == "__main__":
    test_protocol_v1_csv_is_rejected()
    print("PASS summarizer rejects superseded protocol-v1 CSV")
