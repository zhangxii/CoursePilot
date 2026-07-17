# CoursePilot

面向单个学生小组、单份持续迭代大作业的课程学习 Agent 系统。

## 安装

```powershell
conda create -n coursepilot python=3.12 -y
conda activate coursepilot
python -m pip install -e ".[dev]"
```

复制 `.env.example` 为 `.env`，填写 `COURSEPILOT_OPENAI_API_KEY` 和
`COURSEPILOT_VECTOR_STORE_ID`。密钥不得提交到仓库。

## 运行与测试

```powershell
coursepilot
streamlit run coursepilot/app.py
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

会话历史由 Agents SDK `SQLiteSession` 保存，课程、小组、唯一作业、答案、评审和修改
保存在独立的业务 SQLite 表中。默认检索仅使用当前课程；历史检索必须提供批准原因。

## 性能基线

普通请求默认最多返回 5 条当前课程检索结果且只调用一个专业 Agent。修改请求在缺少评审时
顺序调用 ReviewAgent 和 RevisionAgent。trace 记录工具调用、检索范围、结果数和耗时，便于在
真实样例运行后比较四类任务的延迟与调用数量。

CoursePilot 是面向单个学生小组和一份课程大作业的 Agent 学习助手。

## 开发环境

```powershell
conda activate coursepilot
python -m pip install -e ".[dev]"
```

复制 `.env.example` 为 `.env` 并填写配置。验证配置与初始化数据库：

```powershell
coursepilot check-config
coursepilot init-db
```

运行全部质量检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```
