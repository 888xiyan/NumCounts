# NumCounts 协作指南

## 项目简介

NumCounts 是面向高校绩效核算的可配置系统。底层以计算记录的 `Input`、`Function`、`Output` 为核心，后端负责受控函数执行、状态管理和结果追溯；规则插件封装版本化计算规则，工作流帮助操作员顺序编排计算与汇总。

当前技术栈为 FastAPI、SQLAlchemy、Alembic、MySQL 和原生 HTML/CSS/JavaScript 本地操作台。SQLite 原型仅用于保留最小计算语义和演示。

## 目录结构

```text
backend/
  app/                 # FastAPI 应用、领域模型、服务与 API
  alembic/             # 数据库迁移脚本
  tests/               # Python 自动化测试
  demo/                # SQLite 原型演示
  legacy/              # SQLite 最小内核
  .venv/               # 本地 Python 虚拟环境
  pyproject.toml       # Python 依赖、测试与 Ruff 配置
frontend/
  index.html           # 本地操作员页面
  app.js               # 页面交互与 API 调用
  styles.css           # 页面样式
doc/                   # 产品、技术、接口与阶段设计文档
```

## 安装、运行与检查

所有后端命令均在 `backend/` 目录执行。

### 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

配置 `.env` 中的本地 MySQL 连接、JWT 密钥和种子用户密码后再启动服务。

### 运行后端

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

如需处理待执行计算记录，在另一终端运行：

```bash
.venv/bin/python -m app.workers.runner
```

### 运行本地操作员页面

先启动后端，再在 `frontend/` 目录运行：

```bash
python3 -m http.server 4173
```

访问 `http://127.0.0.1:4173`。默认后端 API 地址为 `http://127.0.0.1:8000/api/v1`。

### 测试与 lint

```bash
cd backend
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pytest -q
```

如明确需要核对已存在数据库的 ORM 与迁移一致性，可运行：

```bash
.venv/bin/python -m alembic check
```

## 代码风格与命名

- Python 使用 Python 3.12、4 空格缩进、类型标注和 Ruff 配置；不直接调用 `ruff` 二进制，使用 `.venv/bin/python -m ruff`。
- 模块、函数、变量使用 `snake_case`；类、Pydantic 模型和 SQLAlchemy 模型使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- API 路径使用小写复数 kebab-case，例如 `/rule-plugins`；JSON 字段使用 `snake_case`。
- 新 API 使用 Pydantic 请求/响应模型，错误必须使用 `APIError` 的标准错误信封。
- 计算逻辑必须走受控函数、外部执行器或规则插件；`Function` 字段不得存放或执行 Python、JavaScript、SQL、Shell 或任意 URL。
- 规则插件和工作流定义不可原地修改。规则变化必须创建新版本，并保持历史计算的快照可追溯。
- 前端只能调用后端 API，不能直接写入计算状态、输出或数据库。
- 文档、接口、模型和迁移语义发生变化时，同步更新 `doc/` 中对应说明。

## 禁止事项

- **没有用户明确要求时，不要执行数据库迁移。** 不运行 `alembic upgrade`、`alembic downgrade`，也不手工修改 MySQL 表结构或数据。
- 不提交 `.env`、真实账号密码、JWT 密钥、执行器令牌、真实绩效数据或数据库文件。
- 不使用破坏性 Git 操作，例如 `git reset --hard`、强制推送或覆盖用户已有改动，除非用户明确要求。
- 不绕过函数白名单、插件快照、工作流节点或计算服务直接写入 `calculation_records.output_data`、状态或执行历史。
- 不在未获得明确需求时引入任意代码执行、动态 SQL、动态远程 URL 或表达式引擎。

## 完成标准

每次代码改动完成前必须：

1. 保留并检查用户已有的无关改动。
2. 为新增行为或修复补充相应测试。
3. 在 `backend/` 运行并通过：

   ```bash
   .venv/bin/python -m ruff check app tests
   .venv/bin/python -m pytest -q
   ```

4. 更新受影响的接口或设计文档。
5. 在交付说明中报告测试结果、未验证项和任何需要用户确认的数据库操作。
