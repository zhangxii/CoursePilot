# CoursePilot

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
