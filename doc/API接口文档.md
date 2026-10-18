# NumCounts API 接口文档

## 1. 文档范围

本文定义 NumCounts 正式 FastAPI 服务的 REST API。接口覆盖计算记录、函数元数据、规则插件、顺序工作流、执行、局部重载、重试和健康检查。所有计算都由服务端受控函数、已登记外部执行器或冻结的插件引用完成；客户端不能提交可执行 Python、JavaScript、SQL 或任意 URL。

当前 Python 与 SQLite 原型保留为语义基线；本文描述已经落地的 FastAPI 与 MySQL 服务。未标记为“后续”的接口均可用。

## 2. 通用约定

| 项目 | 约定 |
|---|---|
| 服务前缀 | `/api/v1` |
| 数据格式 | `application/json; charset=utf-8` |
| 标识 | UUID 字符串 |
| 时间 | UTC ISO 8601，例如 `2026-10-16T08:30:00.123456Z` |
| 金额与系数 | JSON 数值；格式化由前端负责 |
| 列表限制 | `limit` 默认为 100，范围 1–100；当前不提供分页总数 |
| 身份认证 | 除健康检查外使用 `Authorization: Bearer <JWT>` |
| 请求追踪 | 客户端可传 `X-Request-Id`；服务端未收到时自动生成并在响应头返回 |
| 幂等创建 | `POST /records` 必须携带 `Idempotency-Key` UUID |

资源详情接口直接返回资源对象；列表接口使用 `data` 和 `pagination` 包装。

### 2.1 登录与令牌

当前仅提供预置用户登录，不提供注册、自助重置密码或公开用户管理接口。角色固定为 `ADMIN` 与 `USER`：`ADMIN` 用于系统管理和后续受保护的管理操作，`USER` 用于普通使用者。令牌中含用户 ID、用户名和角色，默认有效期由 `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` 配置。

#### 登录

`POST /api/v1/auth/login`

```json
{
  "username": "admin",
  "password": "<seed password>"
}
```

成功返回：

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

用户名或密码错误统一返回 `401 INVALID_CREDENTIALS`，避免泄露用户是否存在。

#### 当前用户

`GET /api/v1/auth/me`

请求必须带 `Authorization: Bearer <JWT>`。成功响应返回当前用户的 `id`、`username` 与 `role`。缺少、无效、过期令牌或已停用用户返回 `401`。

### 2.2 标准错误响应

```json
{
  "error": {
    "code": "INVALID_FUNCTION_INPUT",
    "message": "function input did not satisfy its contract",
    "details": {
      "errors": ["Pydantic 字段错误明细"]
    },
    "retryable": false
  },
  "request_id": "d3f1e4a9-7f2d-4c6e-a8c6-f7e1e0ad11c7"
}
```

| HTTP 状态 | 使用场景 |
|---|---|
| `400` | JSON 格式、请求头或参数格式错误 |
| `401` | 缺少或无效访问令牌 |
| `403` | 身份已认证但没有资源范围权限 |
| `404` | 记录、函数或其他资源不存在 |
| `409` | 幂等键冲突、记录正在执行或状态不允许操作 |
| `422` | 表名、Function 或业务输入不符合契约 |
| `429` | 请求频率超过限制 |
| `500` | 未处理的内部错误，响应不得包含堆栈或密钥 |
| `502`、`504` | 当前同步执行接口不会直接返回；执行器无效响应或超时会以 `200` 的失败记录写入对应错误码 |

## 3. 核心数据模型

### 3.1 Function

```json
{
  "kind": "registered",
  "name": "teaching_performance",
  "version": "1.0.0"
}
```

| 字段 | 要求 |
|---|---|
| `kind` | `registered`、`external` 或 `plugin` |
| `name` | 已登记函数名称，或外部执行器提供的函数名称 |
| `version` | 已登记函数版本，或外部执行器兼容的函数版本 |

外部函数必须额外包含受控的 `executor_id`，例如：

```json
{
  "kind": "external",
  "executor_id": "research-policy-runner",
  "name": "calculate_paper_performance",
  "version": "2.1.0"
}
```

记录不得包含外部服务地址、认证令牌或源码。服务端仅从 `EXTERNAL_EXECUTORS` 部署配置中解析 `executor_id`。

已启用的规则插件可作为操作员友好的函数引用：

```json
{
  "kind": "plugin",
  "plugin_id": "11111111-1111-1111-1111-111111111111"
}
```

创建时服务端冻结插件的版本、默认输入和最终函数引用；记录响应的 `plugin` 字段返回该快照。停用插件后不能创建新引用，但已创建记录仍按快照执行。

### 3.2 CalculationRecord

```json
{
  "id": "4a353e8e-3578-4dda-954d-5d5063d4509e",
  "table_name": "teaching_rules",
  "period_id": "2026-spring",
  "input": {
    "hours": 36,
    "rate": 80,
    "quality_factor": 1.1
  },
  "function": {
    "kind": "registered",
    "name": "teaching_performance",
    "version": "1.0.0"
  },
  "output": {
    "metric": "teaching_performance",
    "amount": 3168.0
  },
  "status": "success",
  "error": null,
  "attempt_count": 1,
  "created_at": "2026-10-16T08:30:00.000000Z",
  "updated_at": "2026-10-16T08:30:01.231000Z"
}
```

`table_name` 只能包含小写字母、数字和下划线，长度不超过 64。`input` 必须是 JSON 对象，最大 64 KiB。`output`、`status`、`error` 和 `attempt_count` 均由计算核心维护。

## 4. 计算记录 API

### 4.1 创建记录

`POST /api/v1/records`

请求头：

```http
Content-Type: application/json
Authorization: Bearer <JWT>
Idempotency-Key: 4a353e8e-3578-4dda-954d-5d5063d4509e
```

请求体：

```json
{
  "table_name": "teaching_rules",
  "period_id": "2026-spring",
  "input": {
    "hours": 36,
    "rate": 80,
    "quality_factor": 1.1
  },
  "function": {
    "kind": "registered",
    "name": "teaching_performance",
    "version": "1.0.0"
  }
}
```

成功创建返回 `201 Created` 和状态为 `pending` 的完整记录。相同幂等键与相同请求体返回首次创建的记录和 `200 OK`；相同键与不同请求体返回 `409 IDEMPOTENCY_KEY_REUSED`。计算记录接口目前仅限 `ADMIN`。

### 4.2 查询单条记录

`GET /api/v1/records/{record_id}`

成功返回 `200 OK` 和完整记录。当前仅 `ADMIN` 可以访问计算记录；组织和周期数据范围属于后续权限能力。

### 4.3 查询记录列表

`GET /api/v1/records`

支持的查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `table_name` | string | 精确过滤逻辑表名 |
| `period_id` | string | 精确过滤考核周期 |
| `status` | string | `pending`、`running`、`success`、`failed` |
| `function_name` | string | 精确过滤函数名称 |
| `limit` | integer | 返回数量，默认 100，范围 1–100 |

响应：

```json
{
  "data": [
    {
      "id": "4a353e8e-3578-4dda-954d-5d5063d4509e",
      "table_name": "teaching_rules",
      "status": "success",
      "attempt_count": 1,
      "updated_at": "2026-10-16T08:30:01.231000Z"
    }
  ]
}
```

列表默认按 `created_at ASC, id ASC` 排序，确保执行和查询顺序稳定。

### 4.4 执行指定记录

`POST /api/v1/records/{record_id}/execute`

请求体为空对象 `{}`。服务端对该记录加互斥锁，创建一次执行尝试，增加 `attempt_count`，然后同步完成内置函数计算或受控外部执行器调用。

成功计算返回 `200 OK` 与 `status=success` 的记录。业务输入错误同样返回 `200 OK`，但记录状态为 `failed` 且包含 `error`，因为本次执行请求已被成功处理。请求状态或权限错误才返回 `4xx`。

### 4.5 执行待处理记录

`POST /api/v1/records/run-pending`

请求体：

```json
{
  "limit": 100
}
```

服务端按 `created_at ASC, id ASC` 顺序执行最多 `limit` 条 `pending` 记录；MVP 的执行器只允许单个实例运行。

响应：

```json
{
  "processed": 3,
  "succeeded": 2,
  "failed": 1,
  "skipped": 0,
  "records": [{"id": "record-id-1", "status": "success"}]
}
```

### 4.6 局部重载

`POST /api/v1/records/{record_id}/reload`

局部重载只影响路径中的一条记录：清空 `output` 和 `error`，并把状态改为 `pending`。它不增加 `attempt_count`，不重跑其他记录，不改变其他表，也不传播跨表状态。

若记录为 `running`，返回 `409 RECORD_RUNNING`。

### 4.7 重试记录

`POST /api/v1/records/{record_id}/retry`

服务端依次执行局部重载和一次执行。返回新的完整记录。失败重试仍返回 `200 OK` 与 `status=failed`，错误详情位于 `error`，并且 `attempt_count` 增加一。

## 5. 函数 API

### 5.1 函数列表

`GET /api/v1/functions`

当前不支持过滤。响应列出所有已注册函数的名称、描述、固定版本、输入 JSON Schema 和输出 Schema；任一已登录用户都可查询。

### 5.2 函数版本详情

`GET /api/v1/functions/{name}/versions/{version}`

响应示例：

```json
{
  "name": "teaching_performance",
  "version": "1.0.0",
  "kind": "registered",
  "input_schema": {
    "required": ["hours", "rate"],
    "properties": {
      "hours": {"type": "number", "minimum": 0},
      "rate": {"type": "number", "minimum": 0},
      "quality_factor": {"type": "number", "minimum": 0, "default": 1}
    }
  },
  "output_schema": {
    "required": ["metric", "amount"]
  }
}
```

当前注册表代码只读，函数版本不可经 API 修改。后续函数治理会将元数据持久化，并继续保持“新增版本而非覆盖历史引用”的规则。

## 6. 成果数据 API

成果记录将异构教学、科研、社会服务和人才培养数据统一为可审核输入。数据导入和手工申报均创建 `pending_review`；只有 `approved` 记录可进入后续绩效计算。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| `POST` | `/achievements/declarations` | 登录用户 | 手工申报本人成果，教师 ID 由服务端取当前用户 |
| `POST` | `/achievements/import` | `ADMIN` | 导入教务或科研来源记录，单次最多 100 条 |
| `GET` | `/achievements` | 登录用户 | 查询成果；非管理员仅返回本人记录 |
| `GET` | `/achievements/{record_id}` | 登录用户 | 查询单条有权限访问的成果 |
| `POST` | `/achievements/{record_id}/review` | `ADMIN` | 审核待审核成果，`approve` 或 `reject` |
| `GET` | `/achievements/eligible` | 登录用户 | 仅返回已审核通过的可计算成果 |

导入请求必须指定 `source=academic_affairs` 或 `research_system`。同一 `(source, source_record_id)` 只能导入一次，重复时返回 `409 DUPLICATE_SOURCE_RECORD`。完整字段和状态机见 [数据MVP设计.md](数据MVP设计.md)。

### 6.1 教师手工申报

`POST /api/v1/achievements/declarations`

```json
{
  "department_id": "computer-science",
  "achievement_type": "research_paper",
  "level": "A",
  "occurred_at": "2026-10-16",
  "payload": {
    "title": "Example paper",
    "author_rank": 1,
    "author_count": 3
  }
}
```

服务端使用当前 JWT 用户作为 `teacher_id` 和 `teacher_name`，忽略并拒绝客户端伪造的教师字段；成功返回 `201` 与 `status=pending_review`。

### 6.2 教务或科研来源导入

`POST /api/v1/achievements/import`

```json
{
  "source": "academic_affairs",
  "records": [
    {
      "source_record_id": "course-1001",
      "teacher_id": "teacher-001",
      "teacher_name": "张老师",
      "department_id": "computer-science",
      "achievement_type": "teaching_workload",
      "level": "undergraduate",
      "occurred_at": "2026-09-01",
      "payload": {"hours": 36}
    }
  ]
}
```

仅 `ADMIN` 可以调用。导入批次中任一来源记录重复时，整批返回 `409`，不会创建部分记录。

### 6.3 审核与可计算查询

`POST /api/v1/achievements/{record_id}/review`

```json
{
  "decision": "approve",
  "comment": "材料核验通过"
}
```

仅 `ADMIN` 可以审核，且仅 `pending_review` 可以审核。通过后状态变为 `approved`；驳回后状态变为 `rejected`。`GET /api/v1/achievements/eligible` 只返回 `approved` 记录，是后续规则计算的唯一数据入口。

## 7. 健康检查 API

| 路径 | 认证 | 说明 |
|---|---|---|
| `GET /api/v1/health/live` | 否 | 进程存活，返回 `200` 即可 |
| `GET /api/v1/health/ready` | 否 | MySQL、函数注册表和必要配置就绪时返回 `200` |

`ready` 失败返回 `503 Service Unavailable`，供 Docker、Kubernetes 或负载均衡停止向未就绪实例分发请求。

## 8. 外部执行器协议

当 Function 使用 `kind=external` 时，计算核心根据 `executor_id` 在受控配置中查找服务地址、认证方式与超时，调用：

`POST {executor-base-url}/v1/executions`

```json
{
  "execution_id": "d353e8e9-3578-4dda-954d-5d5063d4509e",
  "record_id": "4a353e8e-3578-4dda-954d-5d5063d4509e",
  "table_name": "research_rules",
  "function": {
    "name": "calculate_paper_performance",
    "version": "2.1.0"
  },
  "input": {
    "paper_level": "A",
    "author_rank": 1,
    "author_count": 3
  },
  "timeout_ms": 5000
}
```

成功响应：

```json
{
  "status": "success",
  "output": {
    "metric": "research_performance",
    "amount": 12000
  }
}
```

失败响应：

```json
{
  "status": "failed",
  "error": {
    "code": "INVALID_AUTHOR_RANK",
    "message": "author_rank must be between 1 and author_count",
    "retryable": false
  }
}
```

相同 `execution_id` 必须幂等。核心不对超时请求自动创建新的业务结果；调用方通过记录重试 API 明确发起下一次尝试。

## 9. 权限与审计

M1 的实际角色仅为 `ADMIN` 与 `USER`。下面的绩效管理员、学院管理员与教职工数据范围属于后续角色扩展，不作为当前接口授权承诺。

| 操作 | 系统管理员 | 绩效管理员 | 学院管理员 | 教职工 |
|---|---:|---:|---:|---:|
| 查询函数 | 是 | 是 | 是 | 是 |
| 创建与执行本范围记录 | 是 | 是 | 是 | 否 |
| 查询全校记录 | 是 | 是 | 否 | 否 |
| 查询本学院记录 | 是 | 是 | 是 | 否 |
| 查询本人已发布结果 | 是 | 是 | 是 | 是 |
| 重载与重试 | 是 | 是 | 本学院 | 否 |
| 管理函数与执行器 | 是 | 否 | 否 | 否 |

当前已保存不可变执行尝试快照；完整审计事件（操作者、对象、前后状态与请求 ID）属于后续治理能力。

## 10. 版本与兼容性

- API 大版本通过 URL 管理，例如 `/api/v1`；破坏性变更发布 `/api/v2`。
- 在同一大版本中，只新增可选字段，不改变既有字段类型和含义。
- `Function.version` 与 API 版本无关；函数版本独立冻结。
- 接口废弃至少提前一个发布周期标记，并在 OpenAPI 描述和发布说明中注明替代接口。
- FastAPI 自动生成的 `/docs` 仅在受控环境开放；生产环境应要求管理员认证或关闭公开访问。

## 11. 规则插件与工作流

本阶段接口面向当前 `ADMIN` 角色。插件与工作流均是声明式 JSON 配置，不接受可执行源码。

### 11.1 规则插件

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/rule-plugins` | 创建默认停用的插件版本 |
| `GET` | `/rule-plugins` | 按可选 `status` 查询插件目录 |
| `GET` | `/rule-plugins/{plugin_id}` | 查询单个插件版本 |
| `POST` | `/rule-plugins/{plugin_id}/enable` | 启用以供新记录或工作流引用 |
| `POST` | `/rule-plugins/{plugin_id}/disable` | 停用新引用，不影响历史快照 |

创建插件示例：

```json
{
  "plugin_key": "teaching_hourly",
  "version": "1.0.0",
  "name": "教学课时绩效",
  "description": "使用固定单价和质量系数",
  "function": {
    "kind": "registered",
    "name": "teaching_performance",
    "version": "1.0.0"
  },
  "input_defaults": {"rate": 80, "quality_factor": 1.1}
}
```

同一 `plugin_key + version` 返回 `409 RULE_PLUGIN_VERSION_EXISTS`；未知函数或执行器返回对应 `404`；停用插件被新记录引用时返回 `409 RULE_PLUGIN_DISABLED`。

### 11.2 工作流定义与运行

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/workflows` | 创建草稿工作流及冻结节点插件快照 |
| `GET` | `/workflows` | 按可选 `status` 查询工作流 |
| `GET` | `/workflows/{workflow_id}` | 查询定义和有序节点 |
| `POST` | `/workflows/{workflow_id}/activate` | 激活工作流 |
| `POST` | `/workflows/{workflow_id}/disable` | 禁止发起新运行 |
| `POST` | `/workflows/{workflow_id}/runs` | 使用上下文同步运行工作流 |
| `GET` | `/workflows/{workflow_id}/runs` | 查询运行历史 |
| `GET` | `/workflow-runs/{workflow_run_id}` | 查询一次运行和全部节点详情 |

工作流目前支持 `plugin` 节点和 `aggregate` 节点。插件节点的输入只能从顶层运行上下文读取或写入 JSON 字面量；聚合节点只能读取前序成功节点的 `output.amount`。一次运行失败时，失败节点保存结构化错误，余下节点为 `skipped`，HTTP 请求仍返回 `201` 与该次运行详情。

完整节点配置、运行状态与验收样例见 [规则插件与工作流设计.md](规则插件与工作流设计.md)。
