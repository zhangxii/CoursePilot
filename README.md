# CoursePilot

## TL;DR

CoursePilot 是一个面向学生小组的本地优先课程学习 Agent：导入 Markdown/TXT 课程资料后，可以用多个专业 Agent 协作完成知识总结、作业撰写、答案评审与修改，并按课程和题目保存全过程。

```powershell
conda create -n coursepilot python=3.12 -y
conda activate coursepilot
python -m pip install -e ".[dev]"
Copy-Item .env.example .env  # 填入 COURSEPILOT_LLM_API_KEY
.\start.ps1
```

然后访问 `http://localhost:8501`。需要 Python 3.12，以及支持工具调用和结构化输出的 OpenAI-compatible 模型服务。API Key 仅保存在本机 `.env`，课程资料与学习记录默认保存在本机 `data/`。

CoursePilot 是面向一个学生小组、多道小组作业题的课程学习 Agent 系统。它支持：

- 上传预先整理好的 Markdown 或 UTF-8 纯文本课程资料；
- 在多门课程之间切换，同时保持“当前课程优先”的检索边界；
- 通过 Notes、Assignment、Review、Revision 四个专业 Agent 完成总结、作业、评审和修改；
- 保存小组、多道题目，以及每道题各自的共享答案版本、评审和修改记录；
- 使用 Markdown、YAML 和 JSONL 保存业务数据与多轮会话，不依赖数据库。

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
COURSEPILOT_DATA_PATH=data
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
| `COURSEPILOT_DATA_PATH` | 否 | 文件数据根目录，默认 `data` |
| `COURSEPILOT_MAX_UPLOAD_MB` | 否 | Markdown/纯文本上传大小上限 |
| `COURSEPILOT_MAX_SEARCH_RESULTS` | 否 | 单次检索最大结果数 |
| `COURSEPILOT_FULL_CONTEXT_CHARS` | 否 | 全部资料直接送入模型的字符预算，默认 `60000` |

验证配置：

```powershell
coursepilot check-config
```

配置正确时会显示模型、服务地址和数据目录，不会输出 API Key。

### 使用第三方 LLM

模型服务需要兼容 OpenAI API。以第三方服务为例：

```dotenv
COURSEPILOT_LLM_API_KEY=your-third-party-key
COURSEPILOT_LLM_BASE_URL=https://your-provider.example.com/v1
COURSEPILOT_MODEL_NAME=your-provider-model
```

系统只需要这一套模型凭证。资料解析、保存和检索均在本地进行，也不会向 OpenAI tracing 上传运行轨迹。若使用 OpenAI 官方模型，保留 `LLM_API_KEY` 并把 `LLM_BASE_URL` 留空即可。

如果第三方服务不兼容 OpenAI Agents SDK 所需的工具调用和结构化输出，Agent 运行会失败；此时应改用支持这两项能力的模型。

## 4. 一行启动 Web 应用

完成环境安装和 `.env` 配置后，在项目根目录只需执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

启动脚本会自动：

1. 检查 `coursepilot` Conda 环境和配置；
2. 启动 Streamlit；
3. 首次写入时自动创建 `data/` 下的文件目录。

项目已关闭 Streamlit 首次邮箱提示和匿名使用统计，因此全新环境首次启动也不需要交互输入。

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

## 5. 首次使用顺序

### 5.1 初始化唯一小组

首次打开页面会出现初始化表单，填写：

1. 小组名称；
2. 首位成员姓名；
3. 首道作业题目；
4. 首道题的要求。

点击“初始化”。系统只维护一个小组，但初始化后可以继续新增作业题。每道题只有一份小组当前共享答案，并保留历史版本。

### 5.2 创建课程

在左侧栏展开“新增课程”，填写课程名称、课程 ID、日期、教师和主题。

第一门课程会自动成为当前课程。创建更多课程后，可以在左侧栏选择并确认切换。

建议课程 ID 使用稳定、无空格的格式，例如：

```text
system-requirements-20260701
architecture-design-20260717
```

### 5.3 上传课程资料

进入“课程资料”页签：

1. 确认左侧栏显示正确的当前课程；
2. 选择已经整理好的 UTF-8 `.md` 或 `.txt`；
3. 点击“保存到资料库”；
4. 等待资料出现在列表中。

上传文件的本地副本默认保存在：

```text
data/courses/<course_id>/materials/<material_id>.md
```

系统会自动为普通 `.md`/`.txt` 添加 YAML Front Matter，`.txt` 最终也保存为 `.md`。同一课程下重复上传相同内容会按文件哈希去重。当前检索范围内的资料总量不超过 `FULL_CONTEXT_CHARS` 时，系统会把全部正文交给模型；超过预算后，才按关键词选取最相关章节。保存失败时重新上传即可。

### 5.4 创建和切换作业题

在“作业”区域可以新增题目，并在题目列表中切换当前题目。题目切换与课程切换相互独立：当前课程决定默认资料检索范围，当前题目决定 Agent 读取和保存哪一份共享答案。

### 5.5 使用 Agent

进入“Agent 对话”页签，可以使用类似请求：

```text
总结当前课程的核心概念，并列出常见错误。
根据当前课程资料完善当前题目的小组共享答案。
按照评分标准评审当前共享答案。
根据最近评审保守修改当前答案。
回顾历史课程，检查当前答案是否存在跨课程冲突。
```

系统默认先检索当前课程。历史资料只有在当前课程检索完成且满足批准原因时才允许访问。

当修改请求没有对应评审时，系统会强制执行：

```text
评审并保存 → 刷新业务上下文 → 修改并保存新版本
```

### 5.6 查看共享成果

“作业”页签展示当前题目的：

- 当前共享答案及版本号；
- 最近评审分数；
- 修改模式；
- 操作成员和变更摘要；
- 已解决与未解决问题。

关闭并重新启动应用后，业务记录会从 Markdown/YAML 恢复，会话历史会从 JSONL 恢复。

## 6. 开发与测试

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

## 7. 数据文件

默认情况下，本地运行会产生：

```text
data/
├── workspace.yaml
├── courses/
│   ├── course-index.yaml
│   └── <course_id>/
│       ├── course.yaml
│       ├── materials/*.md
│       └── notes/*.yaml
├── assignment/
│   ├── assignment-index.yaml
│   └── <assignment_id>/
│       ├── assignment.md
│       ├── answers/*.md
│       ├── reviews/*.yaml
│       └── revisions/*.yaml
└── sessions/*.jsonl
```

当前版本不会读取旧版 `.db` 文件。若旧开发数据仍需保留，请在升级前导出为 Markdown/YAML；否则可从空的 `data/` 目录重新初始化。

需要全新开始时，请先停止 Streamlit，再备份并删除上述本地数据。不要删除仍需保留的作业版本。

## 8. 常见问题

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

### 资料保存或检索失败

依次检查：

- 上传文件是否为 UTF-8 `.md` 或 `.txt`，且未超过大小限制；
- `data/` 目录是否可写；
- YAML Front Matter 是否完整，以及查询是否属于当前课程。

### 切换课程失败

切换课程只更新 `course-index.yaml`，不访问外部服务。若切换失败，请确认目标课程文件仍存在并检查 `data/` 是否可写。

### PowerShell 无法执行检查脚本

使用当前进程级执行策略运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

## 9. 当前限制

- 只支持一个小组；支持多道题目，但每道题只有一份当前共享答案；
- 只接受预先处理好的 Markdown 和 UTF-8 纯文本，不解析 PDF/PPTX，也不包含 OCR；
- 纯文件存储面向单机单进程，不适合多人同时写入的生产部署；
- 首版不包含账号登录、权限系统和在线作业提交。
