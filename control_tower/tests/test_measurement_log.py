"""Control Tower JSONL 측정 기록기 테스트."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from control_tower.monitoring.measurement_log import MeasurementLogWriter


class MeasurementLogWriterTest(unittest.TestCase):
    def test_creates_metadata_and_appends_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = MeasurementLogWriter(
                root=root, run_id="run-01", component="control_tower"
            )

            self.assertTrue(writer.write("rmf_energy_estimates", {"task_id": "job-1"}))
            self.assertTrue(writer.write("rmf_energy_estimates", {"task_id": "job-2"}))

            run_directory = root / "run-01"
            metadata = json.loads((run_directory / "run_metadata.json").read_text())
            records = [
                json.loads(line)
                for line in (run_directory / "rmf_energy_estimates.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual("control_tower", metadata["component"])
            self.assertEqual(["job-1", "job-2"], [row["task_id"] for row in records])
            self.assertTrue(all(row["schema_version"] == 1 for row in records))
            self.assertTrue(all(row["run_id"] == "run-01" for row in records))
            self.assertTrue(all(row["record_type"] == "rmf_energy_estimates" for row in records))
            self.assertTrue(all(row["recorded_at"].endswith("Z") for row in records))

    def test_disabled_writer_creates_no_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "measurements"
            writer = MeasurementLogWriter(
                root=root, run_id="disabled", component="test", enabled=False
            )
            self.assertTrue(writer.write("stream", {"value": 1}))
            self.assertFalse(root.exists())

    def test_environment_selects_root_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "TRIHOUSE_MEASUREMENT_LOG_ROOT": directory,
                "TRIHOUSE_MEASUREMENT_RUN_ID": "shared-run",
            },
        ):
            writer = MeasurementLogWriter.from_environment(component="control_tower")
            self.assertEqual(Path(directory), writer.root)
            self.assertEqual("shared-run", writer.run_id)

    def test_invalid_run_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MeasurementLogWriter(root="/tmp", run_id="../escape", component="test")

    def test_disk_error_returns_false_instead_of_changing_control_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_file = Path(directory) / "not-a-directory"
            root_file.write_text("occupied")
            writer = MeasurementLogWriter(
                root=root_file, run_id="run-01", component="test"
            )
            self.assertFalse(writer.write("stream", {"value": 1}))


if __name__ == "__main__":
    unittest.main()
