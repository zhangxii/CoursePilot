# M2–M4 验收证据

| 系统验收标准 | 自动化证据 | 结论 |
|---|---|---|
| PDF/PPTX 导入、页码与当前课程检索 | `test_ingestion.py`、`test_material_sync.py`、`test_retrieval.py` | 通过 |
| 当前/历史冲突隔离 | `test_retrieval.py::test_merge_keeps_current_course_first_and_marks_cross_course_conflict` | 通过 |
| 四类请求路由及结构化输出 | `test_agents.py`、`test_specialists.py`、`test_models.py` | 通过 |
| 可解释评审 | `test_models.py`、`test_workspace.py` | 通过 |
| 单小组与唯一大作业 | `test_database.py`、`test_workspace.py`、`test_delivery.py` | 通过 |
| 无评审不修改、评审后产生新版本 | `test_agents.py`、`test_specialists.py`、`test_workspace.py` | 通过 |
| 重启恢复会话和业务记录 | `test_agents.py::test_sqlite_agent_runtime_restores_messages_after_restart`、`test_workspace.py` | 通过 |
| 主 Agent、专业 Agent、工具与异常可追踪 | `test_agents.py::test_main_agent_trace_records_ordered_specialist_sequence`、`test_delivery.py` | 通过 |

Streamlit 的布局和交互入口由 `coursepilot/app.py` 提供；发布演示前需在有效 API Key 与
Vector Store 环境下执行一次人工冒烟，确认浏览器上传、流式反馈及远端 trace 仪表板可见。
