# CoursePilot 模块设计

## 1. 模块划分

建议代码布局如下，实际实现可在不改变职责的前提下微调：

```text
coursepilot/
├── app.py
├── ui/
├── agents/
├── tools/
├── retrieval/
├── ingestion/
├── services/
├── repositories/
├── models/
├── observability/
└── config/
tests/
```

| 模块 | 核心职责 | 主要需求 |
|---|---|---|
| `ui` | Streamlit 页面、表单和状态展示 | FR-040、FR-043 |
| `agents` | 主 Agent、4 个专业 Agent、提示词和编排 | FR-020～FR-029 |
| `tools` | 向 Agent 暴露边界稳定的函数工具 | FR-010～FR-015、FR-022 |
| `retrieval` | 过滤器、检索策略、证据规范化 | FR-010～FR-015 |
| `ingestion` | 文件校验、逐页解析、Markdown 生成和上传 | FR-002～FR-005 |
| `services` | 小组、唯一大作业、课程、共享答案、评审、修改用例 | FR-001、FR-006～FR-009、FR-032～FR-034 |
| `repositories` | SQLite 数据访问和事务 | FR-031～FR-034 |
| `models` | Pydantic 输入、输出、上下文和实体模型 | FR-002、FR-030、FR-041 |
| `observability` | tracing、日志、关联标识和脱敏 | FR-042、FR-043 |
| `config` | 环境变量、模型、数据库和限制配置 | NFR-006～NFR-009 |

## 2. 核心数据模型

```python
class MaterialMetadata(BaseModel):
    course_id: str
    course_name: str
    course_date: date
    teacher: str
    topic: str
    material_type: Literal["pdf", "pptx", "notes", "assignment", "feedback"]
    status: Literal["current", "archived"]

class CourseContext(BaseModel):
    active_course_id: str
    active_course_name: str
    team_id: str
    assignment_id: Literal["main_assignment"]
    current_answer: str | None = None
    latest_review: dict | None = None
    answer_version: int = 1

class TeamMember(BaseModel):
    id: str
    name: str
    role: str | None = None

class Team(BaseModel):
    id: Literal["main_team"]
    name: str
    members: list[TeamMember]

class Assignment(BaseModel):
    id: Literal["main_assignment"]
    team_id: Literal["main_team"]
    title: str
    requirements: str
    rubric: str | None = None

class SourceRef(BaseModel):
    material_id: str
    file_name: str
    course_id: str
    page_or_section: str
    excerpt: str

class DimensionScore(BaseModel):
    dimension: str
    score: int
    max_score: int
    deduction: int
    location: str
    evidence: list[SourceRef]
    reason: str
    revision_advice: str

class ReviewResult(BaseModel):
    total_score: int
    dimension_scores: list[DimensionScore]
    strengths: list[str]
    critical_issues: list[str]
    likely_teacher_questions: list[str]
    revision_priorities: list[str]
```

总分应等于各维度得分之和，维度得分不得超过满分，扣分项必须完整包含位置、依据、原因和修改建议。

## 3. `agents` 模块

### 3.1 MainAgent

输入：用户消息、`CourseContext`。输出：`MainAgentResult`（意图、调用记录、最终回复、上下文变更）。

职责：

- 判断意图与任务输入是否完整。
- 解析或确认当前课程。
- 选择专业 Agent，并在需要时组合调用。
- 不直接绕过工具访问数据库或向量库。
- 校验专业 Agent 输出，调用服务保存业务结果。

### 3.2 NotesAgent

工具：`search_current_course`、`search_course_archive`、`save_course_notes`。

处理顺序：当前课程检索 → 知识结构提取 → 必要时历史检索 → 结构化笔记 → 来源检查 → 保存。输出 `NotesResult`，字段覆盖课程问题、核心概念、分析方法、案例、常见错误、教师标准、实践用法、前序关系和来源。

### 3.3 AssignmentAgent

工具：`get_main_assignment`、`get_current_answer`、两个检索工具、`save_answer_version`。

处理顺序：读取唯一大作业和小组当前答案版本 → 提炼交付物和约束 → 检索当前课程标准 → 证据充分性判断 → 可选历史检索 → 完善共享答案 → 对照题目自检。输出 `AssignmentResult`，包括任务理解、共享答案、课程依据和不确定项。

### 3.4 ReviewAgent

工具：`get_main_assignment`、`get_current_answer`、`search_current_course`、`save_review`；只有符合历史检索条件时才可调用历史工具。

上下文隔离：只接收题目、资料、教师要求、评分标准和待评答案，不接收 AssignmentAgent 的隐藏推理或生成过程。输出严格采用 `ReviewResult`。

### 3.5 RevisionAgent

工具：`get_review_result`、两个检索工具、`save_revision`。

前置校验：原答案与评审均存在。处理顺序：问题排序 → 检索依据 → 按模式修改 → 对照严重问题复查 → 输出新稿和修改说明。输出 `RevisionResult`，包含模式、原版本、新版本、修改稿、逐项变更和未解决问题。

## 4. `tools` 与 `retrieval` 模块

Agent 工具只负责校验输入、调用应用服务并返回精简结果；具体 SDK 细节封装在 adapter 中。

```python
async def search_current_course(query: str, ctx: RunContext) -> SearchResult:
    # 读取 active_course_id，不允许调用者覆盖
    ...

async def search_course_archive(
    query: str,
    reason: ArchiveSearchReason,
    ctx: RunContext,
) -> SearchResult:
    # 排除 active_course_id，并将 reason 写入 trace
    ...
```

`ArchiveSearchReason` 限定为 `USER_REQUESTED`、`PREREQUISITE_REFERENCED`、`CURRENT_EVIDENCE_INSUFFICIENT`、`CROSS_COURSE_CONSISTENCY`。检索服务输出统一 `SearchResult(items, scope, query, reason)`，每个 item 都包含 `SourceRef`。

证据充分性由专业 Agent 根据任务要求判断，但工具层必须执行过滤边界。合并器按当前课程优先、相关度次之排序，并显式标记冲突证据。

## 5. `ingestion` 模块

### 5.1 接口

```python
class MaterialParser(Protocol):
    def supports(self, file_name: str) -> bool: ...
    def parse(self, path: Path) -> list[PageContent]: ...

class VectorStoreGateway(Protocol):
    async def upload(self, document: PreparedDocument) -> RemoteFileRef: ...
    async def delete(self, remote_file_id: str) -> None: ...
```

`PdfParser` 与 `PptxParser` 分别逐页返回 `PageContent(page_number, text)`；`MarkdownRenderer` 生成稳定页码标题；`MaterialIngestionService` 编排校验、哈希去重、解析、渲染、上传和状态保存。

异常类型至少包括：`UnsupportedFileType`、`FileTooLarge`、`EmptyExtraction`、`RemoteUploadFailed`、`IndexingFailed`。失败记录应可重试，不删除诊断信息。

## 6. `services` 与 `repositories` 模块

### 6.1 应用服务

- `TeamService`：初始化唯一小组、维护成员和记录当前操作成员。
- `CourseService`：创建/切换课程，同步 active course；课程不拥有独立作业。
- `AssignmentService`：初始化、读取和更新唯一大作业；拒绝创建第二份作业。
- `AnswerService`：保存唯一大作业的初稿和共享答案版本。
- `ReviewService`：保存评审并关联答案版本。
- `RevisionService`：在事务内保存修改记录和新答案版本。
- `ContextService`：加载/校验/更新 `CourseContext`，不替代业务 repository。

### 6.2 Repository 接口

```python
class AnswerRepository(Protocol):
    def get(self, answer_id: str) -> Answer | None: ...
    def get_latest(self) -> Answer | None: ...
    def add_version(self, answer: Answer) -> Answer: ...

class UnitOfWork(Protocol):
    answers: AnswerRepository
    reviews: ReviewRepository
    revisions: RevisionRepository
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

建议业务表关键字段：

| 表 | 关键字段 |
|---|---|
| `teams` | singleton_key, id, name, created_at；singleton_key 固定且唯一 |
| `team_members` | id, team_id, name, role, created_at |
| `assignment` | singleton_key, id, team_id, title, requirements, rubric；singleton_key 固定且唯一 |
| `courses` | id, name, course_date, teacher, topic, status |
| `materials` | id, course_id, file_name, file_hash, type, status, remote_file_id, index_status, error |
| `answers` | id, assignment_id, version, content, operated_by_member_id, created_at |
| `reviews` | id, answer_id, result_json, total_score, created_at |
| `revisions` | id, source_answer_id, review_id, result_answer_id, mode, change_summary |

## 7. `ui` 模块

页面/区域建议：

1. 侧栏：当前课程、课程切换、配置状态。
2. 资料管理：元数据表单、上传进度、索引状态、失败重试。
3. 对话区：消息流、当前意图、工具执行状态、最终结果。
4. 大作业工作区：固定展示唯一题目、共享答案版本、评审结果、修改模式、操作成员和版本对比，不提供作业列表或新增入口。

UI 只调用应用服务，不直接访问 repository 或 SDK；异常映射为用户可执行的提示，例如“未选择当前课程”“资料尚未完成索引”“请先生成评审”。

## 8. `observability` 与配置

`TraceContext` 至少包含 `request_id`、`session_id`、`active_course_id`、`intent`。工具 span 记录工具名、检索 scope、结果数、耗时、错误类别；历史检索额外记录原因。日志采用结构化格式并脱敏 API Key、授权头和不必要的正文。

配置项至少包含模型名、Vector Store ID、数据库路径、上传大小上限、检索结果上限、超时和重试次数。启动时验证必需配置，禁止在源代码中提供真实密钥默认值。

## 9. 测试设计

- 单元测试：意图到 Agent 路由、单例大作业约束、历史检索条件、过滤器构造、Pydantic 约束、页码渲染、共享答案版本事务。
- 集成测试：SQLite repositories、PDF/PPTX 解析、模拟 Vector Store gateway、主 Agent 工具链（使用模型替身）。
- 端到端测试：导入当前/历史资料后执行总结、完成、评审、修改，并检查 trace 和数据库关联。
- 回归夹具：准备当前/历史课程冲突语料，断言默认结果不被历史资料污染。

## 10. 需求到模块追踪

| 需求 | 实现模块 | 主要验证 |
|---|---|---|
| FR-001～FR-006 | ingestion, services, repositories, ui | 导入/切换集成测试 |
| FR-007～FR-009 | services, repositories, models, ui | 单小组、单作业和共享成果约束测试 |
| FR-010～FR-015 | tools, retrieval | 过滤和冲突语料测试 |
| FR-020～FR-029 | agents, models | 路由、上下文隔离、输出契约测试 |
| FR-030～FR-034 | services, repositories, models | 重启恢复和事务测试 |
| FR-040～FR-043 | ui, models, observability | 端到端和异常测试 |
| NFR-001～NFR-009 | 全局横切模块 | 安全、配置、性能基线和 trace 检查 |
