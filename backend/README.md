# NumCounts

NumCounts 是面向高校绩效核算的可配置计算系统。SQLite 原型保留为计算语义基线；FastAPI/MySQL 正式内核已实现 M0–M3：迁移、JWT 登录、成果审核、受控函数、计算记录、规则插件、顺序工作流、单线程执行、局部重载与重试。

项目文档位于 [../doc](../doc)：

- [产品需求文档](../doc/产品需求文档.md)
- [开发技术文档](../doc/开发技术文档.md)
- [API 接口文档](../doc/API接口文档.md)
- [项目管理文档](../doc/项目管理文档.md)
- [数据 MVP 设计](../doc/数据MVP设计.md)
- [规则插件与工作流设计](../doc/规则插件与工作流设计.md)

## 本地启动

本地开发默认连接本机 MySQL（`127.0.0.1:3306`）。迁移会创建用户、计算记录和成果记录表；种子账号可通过 `POST /api/v1/auth/login` 登录。成果数据接口与审核语义见 [数据 MVP 设计](../doc/数据MVP设计.md)。

复制 `.env.example` 为 `.env`，替换初始密码与 `JWT_SECRET` 后执行：

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.db.seed
.venv/bin/python -m uvicorn app.main:app --reload
```

如需常驻处理待执行记录，在另一终端启动单线程 worker：

```bash
.venv/bin/python -m app.workers.runner
```

计算记录 API 目前由 `ADMIN` 调用。`Function` 字段只接受服务端注册函数、受控外部执行器或已启用规则插件的 JSON 引用；可通过 `GET /api/v1/functions` 查看内置函数和输入 Schema。

## 规则插件与工作流

管理员通过 `/api/v1/rule-plugins` 创建、启用和停用版本化规则插件；插件将受控函数和默认输入封装为无需源码的 JSON 引用。通过 `/api/v1/workflows` 创建和启用顺序工作流；当前支持插件计算节点与金额汇总节点。一次运行的每个节点都会创建或关联一条底层计算记录，完整操作方式见 [规则插件与工作流设计](../doc/规则插件与工作流设计.md)。

如需使用本地操作员页面，先启动后端，再在 `frontend/` 目录运行 `python3 -m http.server 4173` 并访问 `http://127.0.0.1:4173`。示例配置允许该本地来源跨域；部署时请通过 `CORS_ORIGINS` 配置实际管理端地址。

## 外部执行器

复杂规则可使用 `kind=external` 的函数引用，但记录中只能传递受控 `executor_id`、函数名称和版本，不能传递 URL 或令牌。部署环境通过 `EXTERNAL_EXECUTORS` 配置受信任执行器，例如：

```text
EXTERNAL_EXECUTORS=[{"executor_id":"research-policy-runner","base_url":"https://executor.example.edu","authorization_token":"<service-token>","timeout_ms":5000}]
```

执行器固定接收 `POST /v1/executions`，并返回 `success + output` 或 `failed + error`。认证、超时、连接失败和无效响应会被核心写入对应执行尝试。完整契约见 [计算核心 MVP 设计](../doc/计算核心MVP设计.md)。

SQLite 原型示例仍可运行：

```bash
python3 -m demo.demo --database /tmp/numcounts-demo.db
```
