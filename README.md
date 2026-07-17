# CoursePilot

CoursePilot 是面向一个学生小组、一份持续迭代大作业的课程学习 Agent 系统。它支持：

- 导入 PDF、PPTX 课程资料并保存在本地资料库；
- 在多门课程之间切换，同时保持“当前课程优先”的检索边界；
- 通过 Notes、Assignment、Review、Revision 四个专业 Agent 完成总结、作业、评审和修改；
- 保存小组、唯一大作业、共享答案版本、评审和修改记录；
- 使用 SQLite 保存业务数据与多轮会话。

## 1. 运行条件

- Windows 11（项目当前主要验证环境）
- Conda 或 Miniconda
- Python 3.12
- 一个支持工具调用和结构化输出的 OpenAI-compatible 模型服务及 API Key

> API Key 只写入本机 `.env`，不要提交到 Git。资料检索完全在本地完成，不需要额外的 OpenAI Key 或 Vector Store。

## 2. 创建 Conda 环境

在项目根目录打开 PowerShell：

```powershell
conda create -n coursepilot python=3.12 -y
conda activate coursepilot
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

检查依赖是否完整：

```powershell
python -m pip check
```

预期输出：

```text
No broken requirements found.
```

## 3. 配置 `.env`

复制配置模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
COURSEPILOT_LLM_API_KEY=your-provider-key
# 使用 OpenAI 官方服务时保持为空；第三方服务填写兼容的 /v1 地址
COURSEPILOT_LLM_BASE_URL=
COURSEPILOT_MODEL_NAME=gpt-5-mini
COURSEPILOT_DATABASE_PATH=data/coursepilot.db
COURSEPILOT_MAX_UPLOAD_MB=50
COURSEPILOT_MAX_SEARCH_RESULTS=5
COURSEPILOT_FULL_CONTEXT_CHARS=60000
COURSEPILOT_REQUEST_TIMEOUT_SECONDS=60
COURSEPILOT_MAX_RETRIES=2
```

关键配置说明：

| 配置项 | 是否必填 | 说明 |
|---|---|---|
| `COURSEPILOT_LLM_API_KEY` | 是 | OpenAI 或第三方 OpenAI-compatible 模型服务的 Key |
| `COURSEPILOT_LLM_BASE_URL` | 否 | 第三方服务的 OpenAI-compatible `/v1` 地址；OpenAI 官方服务留空 |
| `COURSEPILOT_MODEL_NAME` | 否 | Agent 使用的模型，默认 `gpt-5-mini` |
| `COURSEPILOT_DATABASE_PATH` | 否 | 业务数据库路径，默认 `data/coursepilot.db` |
| `COURSEPILOT_MAX_UPLOAD_MB` | 否 | PDF/PPTX 上传大小上限 |
| `COURSEPILOT_MAX_SEARCH_RESULTS` | 否 | 单次检索最大结果数 |
| `COURSEPILOT_FULL_CONTEXT_CHARS` | 否 | 全部资料直接送入模型的字符预算，默认 `60000` |

验证配置：

```powershell
coursepilot check-config
```

配置正确时会显示模型、服务地址和数据库路径，不会输出 API Key。

### 使用第三方 LLM

模型服务需要兼容 OpenAI API。以第三方服务为例：

```dotenv
COURSEPILOT_LLM_API_KEY=your-third-party-key
COURSEPILOT_LLM_BASE_URL=https://your-provider.example.com/v1
COURSEPILOT_MODEL_NAME=your-provider-model
```

系统只需要这一套模型凭证。资料解析、保存和检索均在本地进行，也不会向 OpenAI tracing 上传运行轨迹。若使用 OpenAI 官方模型，保留 `LLM_API_KEY` 并把 `LLM_BASE_URL` 留空即可。

如果第三方服务不兼容 OpenAI Agents SDK 所需的工具调用和结构化输出，Agent 运行会失败；此时应改用支持这两项能力的模型。

## 4. 初始化数据库

```powershell
coursepilot init-db
```

该命令会创建或升级业务数据库。重复执行是安全的。

从旧的 Vector Store 版本升级时，旧记录没有可迁移的本地正文，因此会被标记为 `pending`。原文件仍在 `data/uploads/` 时，请在页面中重新导入一次；新版本会解析并保存本地正文，此后不再依赖远端索引。

会话数据库会在首次对话时自动创建在业务数据库同目录，默认路径为：

```text
data/sessions.db
```

## 5. 一行启动 Web 应用

完成环境安装和 `.env` 配置后，在项目根目录只需执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

启动脚本会自动：

1. 检查 `coursepilot` Conda 环境和配置；
2. 创建或升级 SQLite 数据库；
3. 启动 Streamlit。

如果当前 PowerShell 允许执行本地脚本，也可以使用更短的命令：

```powershell
.\start.ps1
```

等价的手动启动方式如下：

确保当前仍在 `coursepilot` 环境中：

```powershell
conda activate coursepilot
streamlit run coursepilot/app.py
```

Streamlit 默认打开：

```text
http://localhost:8501
```

如果浏览器没有自动打开，可手动访问该地址。停止应用时在终端按 `Ctrl+C`。

## 6. 首次使用顺序

### 6.1 初始化唯一小组和大作业

首次打开页面会出现初始化表单，填写：

1. 小组名称；
2. 首位成员姓名；
3. 大作业题目；
4. 作业要求。

点击“初始化”。系统只维护一个小组和一份大作业，不提供第二份作业入口。

### 6.2 创建课程

在左侧栏展开“新增课程”，填写课程名称、课程 ID、日期、教师和主题。

第一门课程会自动成为当前课程。创建更多课程后，可以在左侧栏选择并确认切换。

建议课程 ID 使用稳定、无空格的格式，例如：

```text
system-requirements-20260701
architecture-design-20260717
```

### 6.3 上传课程资料

进入“课程资料”页签：

1. 确认左侧栏显示正确的当前课程；
2. 选择 PDF 或 PPTX；
3. 点击“解析并保存”；
4. 等待状态变为 `indexed`。

上传文件的本地副本默认保存在：

```text
data/uploads/
```

处理失败时页面会显示 `failed`，可以点击“重试”。同一课程下重复上传相同内容会按文件哈希去重。当前检索范围内的资料总量不超过 `FULL_CONTEXT_CHARS` 时，系统会把全部正文交给模型；超过预算后，才按关键词选取最相关章节。

### 6.4 使用 Agent

进入“Agent 对话”页签，可以使用类似请求：

```text
总结当前课程的核心概念，并列出常见错误。
根据当前课程资料完善小组大作业答案。
按照评分标准评审当前共享答案。
根据最近评审保守修改当前答案。
回顾历史课程，检查当前答案是否存在跨课程冲突。
```

系统默认先检索当前课程。历史资料只有在当前课程检索完成且满足批准原因时才允许访问。

当修改请求没有对应评审时，系统会强制执行：

```text
评审并保存 → 刷新业务上下文 → 修改并保存新版本
```

### 6.5 查看共享成果

“唯一大作业”页签展示：

- 当前共享答案及版本号；
- 最近评审分数；
- 修改模式；
- 操作成员和变更摘要；
- 已解决与未解决问题。

关闭并重新启动应用后，这些业务记录和会话历史仍会从 SQLite 恢复。

## 7. 开发与测试

运行完整质量门禁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

该命令依次运行：

1. Ruff 格式检查；
2. Ruff 静态检查；
3. strict mypy；
4. Pytest 全套测试。

也可以分别运行：

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
python scripts/benchmark.py
```

## 8. 数据文件

默认情况下，本地运行会产生：

```text
data/
├── coursepilot.db   # 业务数据
├── sessions.db      # Agents SDK 多轮会话
└── uploads/         # 上传文件的本地副本
```

需要全新开始时，请先停止 Streamlit，再备份并删除上述本地数据。不要删除仍需保留的作业版本。

## 9. 常见问题

### `coursepilot` 命令不存在

确认已激活正确环境并重新安装项目：

```powershell
conda activate coursepilot
python -m pip install -e ".[dev]"
```

### 提示配置缺失

确认 `.env` 位于项目根目录，变量名以 `COURSEPILOT_` 开头，然后运行：

```powershell
coursepilot check-config
```

### 资料解析或检索失败

依次检查：

- 上传文件是否为有效 PDF/PPTX，且未超过大小限制。
- PDF 是否包含可提取文字（当前版本不支持扫描件 OCR）；
- `data/` 目录是否可写；
- 资料是否显示为 `indexed`，以及查询是否属于当前课程。

### 切换课程失败

切换课程只更新本地课程与资料状态，不访问外部服务。若切换失败，请确认目标课程仍存在并检查本地数据库是否可写。

### PowerShell 无法执行检查脚本

使用当前进程级执行策略运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

## 10. 当前限制

- 只支持一个小组和一份大作业；
- 只支持 PDF、PPTX，不包含 OCR；
- 默认使用本地 SQLite，不适合多人同时写入的生产部署；
- 首版不包含账号登录、权限系统和在线作业提交。
