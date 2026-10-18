"""运行最小内核验收场景：两表三规则、两条成功、一条失败后局部重试。"""

from __future__ import annotations

import argparse
import json

from legacy.numcounts import PerformanceKernel


def registered(name: str) -> dict[str, str]:
    return {"kind": "registered", "name": name, "version": "1.0.0"}


def result_summary(record: dict[str, object]) -> dict[str, object]:
    output = record["output"]
    return {
        "id": record["id"],
        "table": record["table_name"],
        "status": record["status"],
        "amount": output["amount"] if isinstance(output, dict) else None,
        "error": record["error"],
        "attempt_count": record["attempt_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 NumCounts 最小内核验收场景")
    parser.add_argument("--database", default="numcounts.db", help="SQLite 数据库文件路径")
    args = parser.parse_args()

    kernel = PerformanceKernel(args.database)
    teaching_record_id = kernel.create_record(
        table_name="teaching_rules",
        inputs={"hours": 36, "course_coefficient": 1.2, "unit_price": 80},
        function=registered("teaching_performance"),
    )
    invalid_bonus_record_id = kernel.create_record(
        table_name="teaching_rules",
        inputs={"course_level": "municipal"},
        function=registered("course_bonus"),
    )
    research_record_id = kernel.create_record(
        table_name="research_rules",
        inputs={"research_points": 12, "point_price": 300},
        function=registered("research_performance"),
    )
    initial_results = kernel.run_pending()
    retry_result = kernel.retry_record(invalid_bonus_record_id)

    report = {
        "scenario": "两个表中的三条绩效规则：两条成功，一条错误后局部重试",
        "initial_results": [result_summary(result) for result in initial_results],
        "retry": {
            "record_id": invalid_bonus_record_id,
            "status": retry_result["status"],
            "message": retry_result["error"],
            "attempt_count": retry_result["attempt_count"],
        },
        "successful_records": [teaching_record_id, research_record_id],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
