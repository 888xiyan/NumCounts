# NumCounts 数据 MVP 设计

## 1. 目标与边界

数据 MVP 将教学工作量、科研成果、社会服务和人才培养等异构来源，统一为可审核的“成果记录”。成果只有在院系审核通过后才可作为绩效计算输入；待审核与驳回记录不得进入计算。

本期保持既有两个身份：`USER` 与 `ADMIN`。`USER` 可手工申报并查看本人记录；`ADMIN` 暂时承担院系审核员和系统导入员职责。学院级审核员、组织数据范围和多级审批将在权限模型扩展后拆分。

## 2. 统一成果记录

| 字段 | 说明 |
|---|---|
| `teacher_id`、`teacher_name` | 教师稳定标识及显示名 |
| `department_id` | 院系标识；当前为受控字符串，后续关联组织表 |
| `achievement_type` | `teaching_workload`、`research_paper`、`research_project`、`research_funding`、`social_service`、`talent_cultivation` |
| `level` | 业务等级，例如课程层次、论文分区、项目级别 |
| `occurred_at` | 成果发生日期 |
| `source` | `academic_affairs`、`research_system` 或 `manual_declaration` |
| `source_record_id` | 外部源记录标识；同一来源内唯一，用于防重复导入 |
| `payload` | 各类成果的原始扩展字段 JSON，例如课时、作者排序、项目经费 |
| `status` | `pending_review`、`approved` 或 `rejected` |
| 审核字段 | 审核人、审核时间和审核意见 |

手工申报不接受客户端传入的教师身份；服务端取当前登录用户的 ID 和用户名，避免普通用户代他人申报。教务与科研系统导入则由管理员提供教师标识和外部源记录 ID。

## 3. 状态与审核流

```text
教务/科研接口导入 ─┐
                    ├─→ pending_review ── ADMIN 审核 ──→ approved ──→ 可计入计算
教师手工申报 ───────┘                         └──────→ rejected ──→ 不可计入计算
```

- 导入和手工申报一律创建 `pending_review` 记录；
- `ADMIN` 只能审核待审核记录，结果为通过或驳回；
- 已审核记录不允许再次审核，避免覆盖审核结论；
- `GET /achievements/eligible` 只返回 `approved` 记录，后续计算核心只能从该查询或等效仓储读取输入。

## 4. 业务服务边界

数据 MVP 的事实来源是成果记录与审核状态，不是 HTTP 路由。`backend/app/domain/achievements.py` 定义与接口无关的业务规则，`backend/app/services/achievement_service.py` 负责事务、去重和数据库访问。因此后续的接口、文件导入、定时任务或工作流都必须调用同一服务，不得直接修改审核状态。

| 业务动作 | 业务约束 |
|---|---|
| 手工申报 | 申报人身份绑定为教师身份，初始状态固定为 `pending_review` |
| 来源导入 | 仅 `ADMIN` 可导入；仅允许教务和科研系统来源；同一来源记录不得重复 |
| 审核 | 仅 `ADMIN` 是本期审核员；只能处理 `pending_review`；审核结论不可覆盖 |
| 计算取数 | 内部服务 `list_approved_for_calculation` 只返回 `approved` 记录，支持院系、教师、类型和发生日期范围过滤 |

数据服务不直接计算金额，也不写入 `calculation_records` 的输出或状态。后续批次/规则服务按周期和院系读取已审核成果，映射为 Input JSON 后再创建计算记录。

## 5. 接口适配层

现有 HTTP 路由只是上述业务服务的一个适配层，具体接口形式不影响成果模型和审核规则。

所有接口前缀为 `/api/v1`，并要求 Bearer JWT。

| 方法 | 路径 | 身份 | 作用 |
|---|---|---|---|
| `POST` | `/achievements/declarations` | `USER`、`ADMIN` | 教师手工申报，自动进入待审核 |
| `POST` | `/achievements/import` | `ADMIN` | 教务或科研系统批量导入，最多 100 条 |
| `GET` | `/achievements` | 登录用户 | 查询记录；普通用户自动限制为本人 |
| `GET` | `/achievements/{record_id}` | 登录用户 | 查询一条有权限访问的记录 |
| `POST` | `/achievements/{record_id}/review` | `ADMIN` | 通过或驳回待审核记录 |
| `GET` | `/achievements/eligible` | 登录用户 | 仅查询审核通过、可进入计算的记录 |

导入请求中的 `(source, source_record_id)` 具备去重约束。重复提交返回 `409 DUPLICATE_SOURCE_RECORD`，不会写入部分重复数据。

## 6. 与计算核心的连接

计算核心只能消费已审核成果；待审核和已驳回记录不能通过任何适配层进入计算。原始成果、审核结论与计算记录分离保存，使每个绩效结果可以回溯到其已通过的原始成果和具体计算函数。
