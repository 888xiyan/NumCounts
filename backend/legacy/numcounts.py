"""NumCounts 的最小 SQLite 执行内核。

每条记录均包含 Input、Function、Output 三个业务字段，并都以 JSON 存储。
Function 是受控的函数描述对象，内核据此调用已注册的函数；它不是可直接
执行的 Python 或 JavaScript 源码。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


RecordFunction = Callable[[Mapping[str, Any]], dict[str, Any]]
FunctionSpec = Mapping[str, Any]


class NumCountsError(Exception):
    """内核可预期的业务错误。"""


def calculate_teaching_performance(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """计算课时绩效：课时数 × 课程系数 × 课时单价。"""
    required = ("hours", "course_coefficient", "unit_price")
    missing = [field for field in required if field not in inputs]
    if missing:
        raise NumCountsError(f"缺少输入字段：{', '.join(missing)}")

    try:
        hours = float(inputs["hours"])
        coefficient = float(inputs["course_coefficient"])
        unit_price = float(inputs["unit_price"])
    except (TypeError, ValueError) as error:
        raise NumCountsError("hours、course_coefficient 和 unit_price 必须是数值") from error

    if hours < 0 or coefficient < 0 or unit_price < 0:
        raise NumCountsError("课时数、课程系数和课时单价不能为负数")

    amount = round(hours * coefficient * unit_price, 2)
    return {
        "metric": "teaching_performance",
        "formula": "hours * course_coefficient * unit_price",
        "hours": hours,
        "course_coefficient": coefficient,
        "unit_price": unit_price,
        "amount": amount,
    }


def calculate_course_bonus(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """按精品课程等级计算一次性教学奖励。"""
    course_level = inputs.get("course_level")
    bonus_by_level = {"national": 10000.0, "provincial": 5000.0, "school": 2000.0}
    if course_level not in bonus_by_level:
        raise NumCountsError("course_level 必须是 national、provincial 或 school")
    return {
        "metric": "course_bonus",
        "course_level": course_level,
        "amount": bonus_by_level[course_level],
    }


def calculate_research_performance(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """计算科研绩效：成果积分 × 每积分金额。"""
    required = ("research_points", "point_price")
    missing = [field for field in required if field not in inputs]
    if missing:
        raise NumCountsError(f"缺少输入字段：{', '.join(missing)}")
    try:
        points = float(inputs["research_points"])
        point_price = float(inputs["point_price"])
    except (TypeError, ValueError) as error:
        raise NumCountsError("research_points 和 point_price 必须是数值") from error
    if points < 0 or point_price < 0:
        raise NumCountsError("成果积分和每积分金额不能为负数")
    return {
        "metric": "research_performance",
        "research_points": points,
        "point_price": point_price,
        "amount": round(points * point_price, 2),
    }


class PerformanceKernel:
    """用于持久化记录并执行注册函数的最小内核。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self.functions: dict[tuple[str, str], RecordFunction] = {}
        self._has_legacy_function_name = False
        self.register_function(
            "teaching_performance", calculate_teaching_performance, version="1.0.0"
        )
        self.register_function("course_bonus", calculate_course_bonus, version="1.0.0")
        self.register_function(
            "research_performance", calculate_research_performance, version="1.0.0"
        )
        self.initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        """创建最小记录表及索引。"""
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    table_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    function_json TEXT NOT NULL,
                    output_json TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'success', 'failed')),
                    error_message TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_status ON records(status)"
            )

            # 兼容本项目的首个实现：将旧的 function_name 字段迁移为 Function JSON。
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(records)")
            }
            if "function_json" not in columns:
                connection.execute("ALTER TABLE records ADD COLUMN function_json TEXT")
                legacy_records = connection.execute(
                    "SELECT id, function_name FROM records"
                ).fetchall()
                for record in legacy_records:
                    function_spec = {
                        "kind": "registered",
                        "name": record["function_name"],
                        "version": "1.0.0",
                    }
                    connection.execute(
                        "UPDATE records SET function_json = ? WHERE id = ?",
                        (json.dumps(function_spec, ensure_ascii=False), record["id"]),
                    )
            if "attempt_count" not in columns:
                connection.execute(
                    "ALTER TABLE records ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            self._has_legacy_function_name = "function_name" in columns

    def register_function(
        self, name: str, function: RecordFunction, *, version: str = "1.0.0"
    ) -> None:
        """注册一个可由记录引用的受控函数。"""
        if not isinstance(name, str) or not name:
            raise ValueError("函数名称不能为空")
        if not isinstance(version, str) or not version:
            raise ValueError("函数版本不能为空")
        self.functions[(name, version)] = function

    def create_record(
        self,
        *,
        table_name: str,
        inputs: Mapping[str, Any],
        function: FunctionSpec,
        record_id: str | None = None,
    ) -> str:
        """创建一条待执行的表记录。"""
        if not table_name:
            raise ValueError("表名不能为空")
        function_spec = _validate_function_spec(function)
        function_identity = (function_spec["name"], function_spec["version"])
        if function_identity not in self.functions:
            raise NumCountsError(
                f"未注册的函数：{function_spec['name']}@{function_spec['version']}"
            )

        identifier = record_id or str(uuid4())
        now = _now()
        with self._connection() as connection:
            if self._has_legacy_function_name:
                connection.execute(
                    """
                    INSERT INTO records (
                        id, table_name, input_json, function_name, function_json,
                        output_json, status, error_message, attempt_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, 'pending', NULL, 0, ?, ?)
                    """,
                    (
                        identifier,
                        table_name,
                        json.dumps(dict(inputs), ensure_ascii=False),
                        function_spec["name"],
                        json.dumps(function_spec, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO records (
                        id, table_name, input_json, function_json, output_json,
                        status, error_message, attempt_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, 'pending', NULL, 0, ?, ?)
                    """,
                    (
                        identifier,
                        table_name,
                        json.dumps(dict(inputs), ensure_ascii=False),
                        json.dumps(function_spec, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        return identifier

    def run_record(self, record_id: str) -> dict[str, Any]:
        """执行指定记录；成功结果或失败信息都会写回 SQLite。"""
        with self._connection() as connection:
            record = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if record is None:
                raise NumCountsError(f"记录不存在：{record_id}")
            if record["status"] == "running":
                raise NumCountsError(f"记录正在执行：{record_id}")

            connection.execute(
                """
                UPDATE records
                SET status = 'running', error_message = NULL,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (_now(), record_id),
            )

            try:
                function_spec = _validate_function_spec(json.loads(record["function_json"]))
                function = self.functions.get(
                    (function_spec["name"], function_spec["version"])
                )
                if function is None:
                    raise NumCountsError(
                        f"未注册的函数：{function_spec['name']}@{function_spec['version']}"
                    )
            except (NumCountsError, json.JSONDecodeError, TypeError) as error:
                self._mark_failed(connection, record_id, str(error))
            else:
                try:
                    output = function(json.loads(record["input_json"]))
                    connection.execute(
                        """
                        UPDATE records
                        SET output_json = ?, status = 'success', error_message = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (json.dumps(output, ensure_ascii=False), _now(), record_id),
                    )
                except Exception as error:
                    self._mark_failed(connection, record_id, _describe_error(error))

        return self.get_record(record_id)

    def run_pending(self) -> list[dict[str, Any]]:
        """以创建时间顺序执行全部待执行记录，作为单线程执行循环的最小实现。"""
        with self._connection() as connection:
            ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM records WHERE status = 'pending' ORDER BY created_at, id"
                )
            ]
        return [self.run_record(record_id) for record_id in ids]

    def reload_record(self, record_id: str) -> dict[str, Any]:
        """仅重载指定记录，不影响其他表或其他记录。"""
        with self._connection() as connection:
            record = connection.execute(
                "SELECT status FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if record is None:
                raise NumCountsError(f"记录不存在：{record_id}")
            if record["status"] == "running":
                raise NumCountsError(f"记录正在执行，不能重载：{record_id}")
            connection.execute(
                """
                UPDATE records
                SET output_json = NULL, status = 'pending', error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (_now(), record_id),
            )
        return self.get_record(record_id)

    def retry_record(self, record_id: str) -> dict[str, Any]:
        """重载并立即重试指定记录，返回最新成功结果或失败原因。"""
        self.reload_record(record_id)
        return self.run_record(record_id)

    def get_record(self, record_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            record = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        if record is None:
            raise NumCountsError(f"记录不存在：{record_id}")
        return _serialize_record(record)

    def list_records(self, *, table_name: str | None = None) -> list[dict[str, Any]]:
        """列出全部记录，或只列出指定表中的记录。"""
        query = "SELECT * FROM records"
        parameters: tuple[str, ...] = ()
        if table_name is not None:
            query += " WHERE table_name = ?"
            parameters = (table_name,)
        query += " ORDER BY created_at, id"
        with self._connection() as connection:
            records = connection.execute(query, parameters).fetchall()
        return [_serialize_record(record) for record in records]

    @staticmethod
    def _mark_failed(connection: sqlite3.Connection, record_id: str, message: str) -> None:
        connection.execute(
            """
            UPDATE records
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (message, _now(), record_id),
        )


def _serialize_record(record: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": record["id"],
        "table_name": record["table_name"],
        "input": json.loads(record["input_json"]),
        "function": json.loads(record["function_json"]),
        "output": json.loads(record["output_json"]) if record["output_json"] else None,
        "status": record["status"],
        "error": record["error_message"],
        "attempt_count": record["attempt_count"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_function_spec(function: FunctionSpec) -> dict[str, str]:
    """验证并规范化 Function JSON。

    最小内核当前只支持已注册函数，后续可在此扩展 expression、plugin 等类型。
    """
    if not isinstance(function, Mapping):
        raise NumCountsError("Function 必须是 JSON 对象")

    kind = function.get("kind")
    name = function.get("name")
    version = function.get("version")
    if kind != "registered":
        raise NumCountsError("当前仅支持 kind 为 registered 的 Function")
    if not isinstance(name, str) or not name:
        raise NumCountsError("Function.name 必须是非空字符串")
    if not isinstance(version, str) or not version:
        raise NumCountsError("Function.version 必须是非空字符串")
    return {"kind": kind, "name": name, "version": version}


def _describe_error(error: Exception) -> str:
    message = str(error)
    return message or error.__class__.__name__
