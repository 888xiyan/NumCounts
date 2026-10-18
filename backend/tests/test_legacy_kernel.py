import sqlite3
import tempfile
import unittest
from pathlib import Path

from legacy.numcounts import PerformanceKernel


class PerformanceKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "test.db"
        self.kernel = PerformanceKernel(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_calculates_teaching_performance_and_persists_output(self) -> None:
        record_id = self.kernel.create_record(
            table_name="teaching_performance",
            inputs={"hours": 36, "course_coefficient": 1.2, "unit_price": 80},
            function={
                "kind": "registered",
                "name": "teaching_performance",
                "version": "1.0.0",
            },
        )

        result = self.kernel.run_record(record_id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["function"]["kind"], "registered")
        self.assertEqual(result["function"]["name"], "teaching_performance")
        self.assertEqual(result["output"]["amount"], 3456.0)
        self.assertEqual(self.kernel.get_record(record_id)["output"]["amount"], 3456.0)

    def test_invalid_input_marks_record_as_failed(self) -> None:
        record_id = self.kernel.create_record(
            table_name="teaching_performance",
            inputs={"hours": 36, "unit_price": 80},
            function={
                "kind": "registered",
                "name": "teaching_performance",
                "version": "1.0.0",
            },
        )

        result = self.kernel.run_record(record_id)

        self.assertEqual(result["status"], "failed")
        self.assertIn("course_coefficient", result["error"])

    def test_three_rules_in_two_tables_retry_only_the_failed_rule(self) -> None:
        teaching_record_id = self.kernel.create_record(
            table_name="teaching_rules",
            inputs={"hours": 36, "course_coefficient": 1.2, "unit_price": 80},
            function={
                "kind": "registered",
                "name": "teaching_performance",
                "version": "1.0.0",
            },
        )
        invalid_bonus_record_id = self.kernel.create_record(
            table_name="teaching_rules",
            inputs={"course_level": "municipal"},
            function={
                "kind": "registered",
                "name": "course_bonus",
                "version": "1.0.0",
            },
        )
        research_record_id = self.kernel.create_record(
            table_name="research_rules",
            inputs={"research_points": 12, "point_price": 300},
            function={
                "kind": "registered",
                "name": "research_performance",
                "version": "1.0.0",
            },
        )

        results = {result["id"]: result for result in self.kernel.run_pending()}

        self.assertEqual(results[teaching_record_id]["status"], "success")
        self.assertEqual(results[teaching_record_id]["output"]["amount"], 3456.0)
        self.assertEqual(results[research_record_id]["status"], "success")
        self.assertEqual(results[research_record_id]["output"]["amount"], 3600.0)
        self.assertEqual(results[invalid_bonus_record_id]["status"], "failed")
        self.assertIn("course_level", results[invalid_bonus_record_id]["error"])
        self.assertEqual(len(self.kernel.list_records(table_name="teaching_rules")), 2)
        self.assertEqual(len(self.kernel.list_records(table_name="research_rules")), 1)

        retry_result = self.kernel.retry_record(invalid_bonus_record_id)

        self.assertEqual(retry_result["status"], "failed")
        self.assertIn("course_level", retry_result["error"])
        self.assertEqual(retry_result["attempt_count"], 2)
        self.assertEqual(self.kernel.get_record(teaching_record_id)["attempt_count"], 1)
        self.assertEqual(self.kernel.get_record(research_record_id)["attempt_count"], 1)

    def test_migrates_legacy_function_name_database(self) -> None:
        legacy_database = Path(self.temporary_directory.name) / "legacy.db"
        with sqlite3.connect(legacy_database) as connection:
            connection.execute(
                """
                CREATE TABLE records (
                    id TEXT PRIMARY KEY,
                    table_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    output_json TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

        migrated_kernel = PerformanceKernel(legacy_database)
        record_id = migrated_kernel.create_record(
            table_name="teaching_performance",
            inputs={"hours": 1, "course_coefficient": 1, "unit_price": 100},
            function={
                "kind": "registered",
                "name": "teaching_performance",
                "version": "1.0.0",
            },
        )

        self.assertEqual(
            migrated_kernel.run_record(record_id)["output"]["amount"], 100.0
        )


if __name__ == "__main__":
    unittest.main()
