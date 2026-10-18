# NumCounts 文档

仓库根目录仅保留 `backend/`、`frontend/` 与 `doc/`：后端实现、未来操作员界面与项目文档分别独立维护。

## NumCounts 最小内核

计算核心的 API、外部执行器调用方式和输入契约见 [计算核心MVP设计.md](计算核心MVP设计.md)。

整体架构、阶段计划、当前范围和交付标准见 [整体开发文档.md](整体开发文档.md)。

基于 FastAPI 和 MySQL 的正式系统开发方案见 [开发技术文档.md](开发技术文档.md)。

FastAPI 服务的对外接口规范见 [API接口文档.md](API接口文档.md)，里程碑、质量门槛和发布流程见 [项目管理文档.md](项目管理文档.md)。

异构业务数据的统一成果记录、导入、申报与审核流见 [数据MVP设计.md](数据MVP设计.md)。

规则插件、工作流节点、运行状态与操作接口见 [规则插件与工作流设计.md](规则插件与工作流设计.md)。

跨表链接、依赖等待、下游失效、恢复、审计与运行指标见 [跨表链接与运行治理设计.md](跨表链接与运行治理设计.md)。

下文保留的是基于 Python 标准库和 SQLite 的最小原型说明；正式内核以 FastAPI 和 MySQL 为准。每条记录均持久化以下核心字段：

| 字段 | 存储方式 | 作用 |
|---|---|---|
| Input | `input_json` | 函数执行所需输入 |
| Function | `function_json` | 受控函数的 JSON 描述 |
| Output | `output_json` | 函数执行后持久化的结果 |

记录同时保存 ID、表名、状态、错误信息、执行尝试次数和时间戳。`Function` 不是 Python 或 JavaScript 源码，而是由程序读取的 JSON 对象；当前仅支持调用已注册函数：

```json
{
  "kind": "registered",
  "name": "teaching_performance",
  "version": "1.0.0"
}
```

内核通过 `kind`、`name` 和 `version` 定位受控函数，不能执行任意字符串表达式。后续可在不改变数据模型的前提下扩展 `expression` 和 `plugin` 类型。

## 最小内核验收场景

示例创建两个逻辑表、三条不同规则：

| 表 | 规则 | 函数 | 预期 |
|---|---|---|---|
| `teaching_rules` | 课时绩效 | `teaching_performance@1.0.0` | 成功，`36 × 1.2 × 80 = 3456.0` |
| `teaching_rules` | 精品课程奖励 | `course_bonus@1.0.0` | 失败，课程等级为无效值 `municipal` |
| `research_rules` | 科研绩效 | `research_performance@1.0.0` | 成功，`12 × 300 = 3600.0` |

课时绩效计算公式：

```text
绩效金额 = 课时数 × 课程系数 × 课时单价
```

运行示例：

```bash
python3 -m demo.demo --database /tmp/numcounts-demo.db
```

示例会先执行三条待执行记录，然后仅重载并重试失败的精品课程奖励记录。重试后的输出保留错误提示和 `attempt_count: 2`；两条成功记录不会被重新执行。

运行测试：

```bash
python3 -m unittest -v
```

## 最小执行循环

`PerformanceKernel.run_pending()` 按创建时间顺序读取所有 `pending` 记录，并在单线程中逐条执行。每条记录会经历 `pending → running → success/failed` 状态变化；无效输入会写入错误信息，而不会中断其他待执行记录。

原型只支持局部重载：`reload_record(record_id)` 仅清除指定记录的输出和错误，并将其放回 `pending`。`retry_record(record_id)` 会在局部重载后立即重试该记录。正式内核已经实现受控跨表链接、依赖等待与下游失效传播；插队和批量重载仍未实现。
