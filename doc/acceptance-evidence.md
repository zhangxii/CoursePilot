# CoursePilot 验收证据

## 1. 当前实现基线（M2–M4）

下表只证明重构前的历史基线，不代表 `system-requirements.md` 新增的 FR-044～FR-058 已实现。

| 系统验收标准 | 自动化证据 | 结论 |
|---|---|---|
| Markdown/纯文本导入、文件化正文保存与当前课程检索 | `test_ingestion.py`、`test_local_material_library.py`、`test_retrieval.py` | 通过 |
| 当前/历史冲突隔离 | `test_retrieval.py::test_merge_keeps_current_course_first_and_marks_cross_course_conflict` | 通过 |
| 四类请求路由及结构化输出 | `test_agents.py`、`test_specialists.py`、`test_models.py` | 通过 |
| 可解释评审 | `test_models.py`、`test_workspace.py` | 通过 |
| 历史基线：单小组、多题目与每题单一当前答案 | `test_file_store.py`、`test_workspace.py`、`test_delivery.py`、`test_app_flow.py` | 通过 |
| 历史基线：无评审不修改、评审后直接产生新版本 | `test_agents.py`、`test_specialists.py`、`test_workspace.py` | 通过；将由候选稿采用流替代 |
| 重启恢复会话和业务记录 | `test_agents.py::test_jsonl_agent_runtime_restores_messages_after_restart`、`test_workspace.py` | 通过 |
| 主 Agent、专业 Agent、工具与异常可追踪 | `test_agents.py::test_main_agent_trace_records_ordered_specialist_sequence`、`test_delivery.py` | 通过 |

Streamlit 的布局和交互入口由 `coursepilot/app.py` 提供；发布演示前需使用有效的
OpenAI-compatible 模型凭证执行一次人工冒烟，确认浏览器导入、本地检索和 Agent 回复可用。

## 2. 本轮扩展验收矩阵（M5–M8）

| 目标能力 | 需求 | 需要的权威证据 | 当前结论 |
|---|---|---|---|
| 上传用户 `.md`/`.txt`/`.docx` 作业并保存原件/正文 | FR-044～FR-045 | `test_assignment_artifacts.py` 导入与原件恢复测试；`test_app_flow.py` 验证独立作业上传入口及版本绑定后续对话 | 通过 |
| 用户稿创建正式版本且不覆盖历史 | FR-033、FR-045 | `test_assignment_artifacts.py::test_offline_edit_creates_a_new_formal_version_without_overwriting_history` | 通过 |
| Agent 结果先成为候选稿 | FR-025、FR-046 | `test_assignment_artifacts.py` 候选状态与派生链测试；`test_app_flow.py` 生产 Controller 生成与自动审查链路 | 通过 |
| 用户采用后才创建正式版本 | FR-047 | `test_assignment_artifacts.py` 显式采用和过期基础版本拒绝测试 | 通过 |
| 正式版本和候选稿差异可查看 | FR-048 | `test_assignment_artifacts.py::test_candidate_comparison_shows_the_base_and_candidate_changes`；`test_app_flow.py::test_guided_workspace_exposes_context_and_candidate_decisions` | 通过 |
| 多对话新建、切换、分支和归档 | FR-030～FR-031 | `tests/test_conversations.py` 覆盖生命周期、精确消息分支、回滚与重启恢复；`test_app_flow.py` 覆盖界面入口 | 通过 |
| Agent 方案与用户方案对话隔离 | FR-049 | `tests/test_conversations.py` 覆盖数据与检索隔离；`test_app_flow.py::test_production_conversations_keep_prompts_sessions_and_versions_isolated` 覆盖提示词、Session、基础版本及候选稿归属 | 通过 |
| 文字/文件优化方向与 Agent 问题分析 | FR-050～FR-052 | `test_optimization.py` 覆盖方向、建议、双模式与基础目标；`test_app_flow.py` 覆盖界面输入及入口 | 通过 |
| 生成/优化后独立自动审查和一次修正 | FR-023、FR-053 | `test_optimization.py` 覆盖独立输入契约、一次修正与复核；`test_app_flow.py` 验证生产生成后使用无 Session 审查 | 通过 |
| 自动审查与正式评审区分 | FR-054 | 自动/正式记录包含不同 `review_type` 与 `triggered_by`；正式答案卡和候选稿卡分别展示 | 通过 |
| 首次三入口、流程、空状态、动作按钮 | FR-055～FR-057 | `test_app_flow.py` Streamlit AppTest 验证三入口、动作型按钮、六步状态与导航 | 自动化通过；发布前保留人工冒烟 |
| 常驻上下文信息准确 | FR-058 | `test_app_flow.py::test_guided_workspace_exposes_context_and_candidate_decisions` 验证作业、版本和对话上下文 | 通过 |

当前自动化门禁为 Ruff、MyPy 与 Pytest；发布演示前仍需使用有效模型凭证执行一次浏览器人工冒烟。
