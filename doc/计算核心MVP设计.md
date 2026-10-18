# 计算核心 MVP 设计

## 1. 当前交付

正式计算内核已以 FastAPI、SQLAlchemy 和本地 MySQL 实现。它以一条 `calculation_records` 记录为计算单元，固定保存 `Input`、`Function`、`Output` 三个业务字段，并保存状态、错误和每次执行尝试。

当前范围包括：受控函数注册、受控外部执行器、幂等创建、记录查询、同步执行、FIFO 待执行循环、局部重载、局部重试、尝试历史、跨表数据／执行链接、依赖等待、下游失效与恢复、运行审计和指标查询。身份认证、角色权限与组织范围控制的后续扩展当前挂起；插队仍不在本版本范围内。

## 2. 安全边界

`Function` 是 JSON 引用，而不是 Python、JavaScript、SQL 或 URL。记录可选择服务端注册函数，或引用部署配置中已登记的外部执行器：

```json
{
  "kind": "registered",
  "name": "teaching_performance",
  "version": "1.0.0"
}
```

核心根据 `(name, version)` 从 `backend/app/functions/registry.py` 取得受控实现，并用 Pydantic 校验 `Input`。因此规则配置可以保存于表中，但调用方不能借由记录执行任意代码。

外部函数引用不含地址或凭证：

```json
{
  "kind": "external",
  "executor_id": "research-policy-runner",
  "name": "calculate_paper_performance",
  "version": "2.1.0"
}
```

`executor_id` 仅由 `EXTERNAL_EXECUTORS` 环境配置映射到固定基础地址、认证令牌与超时。核心向固定的 `/v1/executions` 发送 `execution_id`、记录信息、函数引用和输入；外部执行器只可返回成功输出或标准业务错误，不能直接写数据库。

## 3. 记录与执行尝试

```json
{
  "id": "4a353e8e-3578-4dda-954d-5d5063d4509e",
  "table_name": "teaching_rules",
  "period_id": "2026",
  "input": {"hours": 36, "rate": 80, "quality_factor": 1.1},
  "function": {
    "kind": "registered",
    "name": "teaching_performance",
    "version": "1.0.0"
  },
  "output": null,
  "status": "pending",
  "error": null,
  "attempt_count": 0,
  "version": 1
}
```

`calculation_attempts` 为每一次实际执行保存输入和函数快照、唯一 `execution_id`、开始和结束时间、耗时、成功输出或失败错误。局部重载不删除历史尝试；重试会创建新的尝试。

输入和输出均限制为不超过 64 KiB 的 JSON 对象。创建记录需要 UUID 格式的 `Idempotency-Key`：相同键和相同请求返回既有记录；同一键配合不同内容返回 `409 IDEMPOTENCY_KEY_REUSED`。

## 4. 状态机与单线程循环

```text
create:                  → pending
execute: pending/success/failed → running → success | failed
reload:  pending/success/failed → pending
retry:   pending/success/failed → pending → running → success | failed
```

`running` 记录不能再次执行、重载或重试。正式执行分两段事务完成：

1. 以 `SELECT ... FOR UPDATE` 锁定记录，切换到 `running`，递增尝试次数并创建尝试快照后提交。
2. 在事务外运行受控函数；随后再次加锁，把输出或结构化错误、执行状态和尝试结束信息一起提交。

`backend/app/workers/runner.py` 按 `created_at, id` 顺序轮询 `pending` 记录。当前进程内异步锁确保 API 触发和 runner 触发的函数一次只运行一条；部署时保持 worker 单副本。这个限制是 MVP 的确定性保证，不是未来并发调度的替代方案。

## 5. 已注册函数与输入契约

| 函数 | 输入 | 成功输出 |
|---|---|---|
| `teaching_performance@1.0.0` | `hours`、`rate` 必填且非负；`quality_factor` 可选、默认 `1`、非负 | `hours × rate × quality_factor` |
| `course_bonus@1.0.0` | `course_count` 非负整数；`level` 为 `national`、`provincial`、`school` | 数量乘对应等级固定标准 |
| `research_performance@1.0.0` | `papers`、`projects`、`funding` 与三项权重均非负；权重可省略 | 论文、项目和经费分项汇总 |

函数输入不满足契约时，HTTP 执行请求本身仍返回 `200`，但目标记录与对应尝试写为 `failed`，并带 `INVALID_FUNCTION_INPUT`。未知函数在创建阶段直接返回 `404 FUNCTION_NOT_FOUND`。

## 6. API 与权限

所有路径位于 `/api/v1`。已登录用户可读取函数目录；计算记录的创建、查询、执行、重载、重试、尝试历史和待执行循环目前限定为 `ADMIN`。这是当前 `ADMIN`/`USER` 两角色模型下的最小安全边界，院系和个人数据范围将在后续权限模型中增加。

| 接口 | 用途 |
|---|---|
| `GET /functions` | 已注册函数及其 JSON Schema |
| `GET /functions/{name}/versions/{version}` | 单一函数版本元数据 |
| `POST /records` | 以幂等键创建待执行记录 |
| `GET /records`、`GET /records/{id}` | 查询记录；列表支持表、状态、周期、函数与 `limit` |
| `POST /records/run-pending` | 执行 FIFO 待处理批次，`limit` 为 1–100 |
| `POST /records/{id}/execute` | 立即执行一条记录 |
| `POST /records/{id}/reload` | 只将目标记录恢复为 `pending` |
| `POST /records/{id}/retry` | 只重载并重试目标记录 |
| `GET /records/{id}/attempts` | 查询不可变的执行尝试历史 |

详细请求和响应见 [API接口文档.md](API接口文档.md)。

## 7. 验收结果

已在本地 MySQL 上完成正式服务端到端校验：

| 逻辑表 | 函数 | 输入 | 结果 |
|---|---|---|---|
| `teaching_rules` | `teaching_performance` | `hours=36`、`rate=80`、`quality_factor=1.1` | 成功，`amount=3168.0` |
| `research_rules` | `research_performance` | `papers=2`、`projects=1`、`funding=10000` | 成功 |
| `teaching_rules` | `course_bonus` | `course_count=1`、`level=municipal` | 失败，`INVALID_FUNCTION_INPUT`；局部重试后仍失败且有两条尝试历史 |

该校验后已清理专用测试记录。单元与接口回归测试也覆盖注册表、输入错误、认证和成果数据契约。

## 8. 外部执行器结果与故障语义

外部执行器成功时返回 `{"status":"success","output":{...}}`；业务失败时返回 `{"status":"failed","error":{"code":"...","message":"...","details":{...}}}`。核心会把两类结果写入同一次执行尝试。

`EXECUTOR_TIMEOUT`、`EXECUTOR_CONNECTION_ERROR`、`EXECUTOR_AUTH_FAILED`、`EXECUTOR_UNAVAILABLE` 和 `EXECUTOR_INVALID_RESPONSE` 均会使目标记录进入 `failed`，保留原始安全错误信息。调用方通过局部 `retry` 显式发起下一次尝试，核心不会自动重放外部业务调用。

成果数据到计算记录的按周期映射、批次、导入导出、插件和工作流仍属后续阶段，也只能经由本内核创建记录和提交结果。
