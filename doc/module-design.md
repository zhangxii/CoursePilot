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
| `ui` | Streamlit 流程导航、页面、表单、空状态和状态展示 | FR-040、FR-043、FR-055～FR-058 |
| `agents` | 主 Agent、4 个专业 Agent、自动审查和有界修正编排 | FR-020～FR-029、FR-051、FR-053～FR-054 |
| `tools` | 向 Agent 暴露边界稳定的函数工具 | FR-010～FR-015、FR-022 |
| `retrieval` | 课程过滤、全文预算、关键词排序、证据规范化 | FR-010～FR-015 |
| `ingestion` | 课程资料、作业稿和优化方向的分类校验、正文规范化与原件保存 | FR-002～FR-005、FR-044～FR-045、FR-050 |
| `services` | 小组、课程、题目、正式版本、候选稿、对话、审查和优化用例 | FR-001、FR-006～FR-009、FR-030～FR-054 |
| `repositories` | Markdown/YAML/JSONL/原件访问、约束和原子写入 | FR-031～FR-054 |
| `models` | Pydantic 输入、输出、上下文和实体模型 | FR-002、FR-030、FR-041 |
| `observability` | tracing、日志、关联标识和脱敏 | FR-042、FR-043 |
| `config` | 环境变量、模型、数据目录和限制配置 | NFR-006～NFR-009 |

## 2. 核心数据模型

```python
class MaterialMetadata(BaseModel):
    course_id: str
    course_name: str
    course_date: date
    teacher: str
    topic: str
    material_type: Literal["markdown", "text"]
    status: Literal["current", "archived"]

class ConversationContext(BaseModel):
    conversation_id: str
    active_course_id: str
    active_course_name: str
    team_id: str
    active_assignment_id: str
    base_answer_version_id: str | None = None
    current_formal_answer: str | None = None
    latest_review: dict | None = None
    parent_conversation_id: str | None = None

class TeamMember(BaseModel):
    id: str
    name: str
    role: str | None = None

class Team(BaseModel):
    id: Literal["main_team"]
    name: str
    members: list[TeamMember]

class Assignment(BaseModel):
    id: str
    team_id: Literal["main_team"]
    title: str
    requirements: str
    rubric: str | None = None

class AnswerVersion(BaseModel):
    id: str
    assignment_id: str
    version: int
    content: str
    source: Literal["user_upload", "adopted_candidate"]
    based_on_version_id: str | None = None
    operated_by_member_id: str

class CandidateDraft(BaseModel):
    id: str
    assignment_id: str
    conversation_id: str
    base_answer_version_id: str | None = None
    derived_from_candidate_id: str | None = None
    superseded_by_candidate_id: str | None = None
    content: str
    status: Literal[
        "draft", "ready_for_adoption", "adopted", "discarded", "superseded"
    ]

class Conversation(BaseModel):
    id: str
    assignment_id: str
    title: str
    base_answer_version_id: str | None = None
    parent_conversation_id: str | None = None
    forked_from_message_id: str | None = None
    status: Literal["active", "archived"]

class OptimizationTask(BaseModel):
    id: str
    assignment_id: str
    conversation_id: str
    base_answer_version_id: str | None = None
    base_candidate_draft_id: str | None = None
    mode: Literal["preserve", "restructure"]
    user_direction: str | None = None
    selected_agent_suggestions: list[str] = Field(default_factory=list)
    preserve_constraints: list[str] = Field(default_factory=list)
    prohibited_changes: list[str] = Field(default_factory=list)
    format_constraints: list[str] = Field(default_factory=list)

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

`OptimizationTask` 的 `base_answer_version_id` 与 `base_candidate_draft_id` 必须恰好填写一个。`Conversation.parent_conversation_id` 与 `forked_from_message_id` 也必须同时为空或同时存在。继续修改候选稿时创建新的 `CandidateDraft`，写入 `derived_from_candidate_id`；原候选稿保留并标记为 `superseded`，不能再被采用。

总分应等于各维度得分之和，维度得分不得超过满分，扣分项必须完整包含位置、依据、原因和修改建议。

## 3. `agents` 模块

### 3.1 MainAgent

输入：用户消息、`ConversationContext`。输出：`MainAgentResult`（意图、调用记录、最终回复、候选稿和上下文变更建议）。

职责：

- 判断意图与任务输入是否完整。
- 解析或确认当前课程。
- 选择专业 Agent，并在需要时组合调用。
- 不直接绕过 repository 访问业务文件或课程资料。
- 校验专业 Agent 输出；生成和优化结果保存为候选稿，不直接创建正式版本。
- 编排独立自动审查和至多一次修正；正式版本只能由采用用例创建。

### 3.2 NotesAgent

工具：`search_current_course`、`search_course_archive`、`save_course_notes`。

处理顺序：当前课程检索 → 知识结构提取 → 必要时历史检索 → 结构化笔记 → 来源检查 → 保存。输出 `NotesResult`，字段覆盖课程问题、核心概念、分析方法、案例、常见错误、教师标准、实践用法、前序关系和来源。

### 3.3 AssignmentAgent

工具：`get_active_assignment`、`get_base_answer_version`、两个检索工具、`save_candidate_draft`。

处理顺序：读取当前题目和对话绑定的基础版本 → 提炼交付物和约束 → 检索当前课程标准 → 证据充分性判断 → 可选历史检索 → 生成候选答案。输出 `AssignmentResult`，包括任务理解、候选答案、课程依据和不确定项。自检不能替代独立 ReviewAgent。

### 3.4 ReviewAgent

工具：`get_active_assignment`、`get_review_target`、`search_current_course`、`save_review`；只有符合历史检索条件时才可调用历史工具。

上下文隔离：只接收题目、资料、教师要求、评分标准和待评正文，不接收生成 Agent 的隐藏推理或所属对话消息。输出严格采用 `ReviewResult`，并以 `review_type=automatic|formal` 区分自动审查和正式评审。

### 3.5 RevisionAgent

工具：`get_optimization_task`、`get_review_result`、两个检索工具、`save_candidate_draft`。

前置校验：基础正式版本与优化任务存在；用户未提供方向时，任务还必须包含用户已确认的 Agent 问题分析。处理顺序：合并用户方向和选中的 Agent 建议 → 检索依据 → 遵守保留项/禁止项 → 按模式修改 → 输出候选稿和修改说明。候选稿产生后才进入独立自动审查、一次可选修正和复核。输出 `RevisionResult`，包含模式、基础版本、候选稿、逐项变更和未解决问题。

## 4. `tools` 与 `retrieval` 模块

Agent 工具只负责校验输入、调用应用模块并返回精简结果；正文读取和预算策略封装在本地检索 adapter 中。

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
class MaterialIngestionService:
    async def ingest(self, path: Path, metadata: MaterialMetadata) -> MaterialRecord: ...

class LocalMaterialSearchGateway:
    async def search(
        self, query: str, filters: SearchFilter, max_results: int
    ) -> list[MaterialSearchHit]: ...

class ArtifactIngestionService:
    def ingest_assignment(
        self, path: Path, purpose: AssignmentUploadPurpose
    ) -> ImportedArtifact: ...
    def ingest_optimization_direction(self, path: Path) -> ImportedArtifact: ...
```

`MarkdownValidator` 接受课程资料的 UTF-8 `.md` 和 `.txt`；`MaterialIngestionService` 编排校验、哈希去重、统一 `.md` 文件保存和状态更新，不负责解析 PDF/PPTX。`ArtifactIngestionService` 独立处理作业稿件和优化方向的 `.md`、`.txt`、`.docx`，保存原件并返回规范化正文，不把稿件加入课程检索库。

异常类型至少包括：`UnsupportedFileType`、`FileTooLarge`、`EmptyDocument`、`DocumentExtractionFailed`。`.docx` 只读取普通文本，不执行宏和嵌入对象。失败记录保留诊断信息，用户可重新上传同一内容进行修复。

## 6. `services` 与 `repositories` 模块

### 6.1 应用服务

- `TeamService`：初始化唯一小组、维护成员和记录当前操作成员。
- `CourseService`：创建/切换课程，同步 active course；课程与当前题目是独立选择轴。
- `AssignmentService`：创建、列出、读取、更新和切换题目，维护 active assignment。
- `AnswerVersionService`：创建用户上传初版/新稿，采用候选稿，并保证每题只有一条正式版本链。
- `CandidateDraftService`：保存 Agent 候选稿及状态，不允许直接更新当前正式版本。
- `ConversationService`：新建、分支、切换、重命名和归档对话，维护其基础版本与独立 Session。
- `ReviewService`：保存自动审查或正式评审并关联明确目标。
- `OptimizationService`：保存用户方向、Agent 建议、模式和约束，编排候选稿产生过程。
- `ContextService`：加载/校验 `ConversationContext`，不替代业务 repository。

### 6.2 Repository 接口

```python
class AnswerVersionRepository(Protocol):
    def get(self, version_id: str) -> AnswerVersion | None: ...
    def get_current(self, assignment_id: str) -> AnswerVersion | None: ...
    def add(self, version: AnswerVersion) -> AnswerVersion: ...

class UnitOfWork(Protocol):
    answer_versions: AnswerVersionRepository
    candidate_drafts: CandidateDraftRepository
    reviews: ReviewRepository
    conversations: ConversationRepository
    optimization_tasks: OptimizationTaskRepository
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

正式版本创建只暴露一个深接口：

```python
class AdoptCandidateService:
    def adopt(self, candidate_id: str, member_id: str) -> AnswerVersion: ...
```

该接口内部校验候选稿状态、题目归属、基础版本是否仍为当前正式版本和自动审查是否完成，并原子地创建新版本、更新正式版本指针和候选稿状态。UI 和 Agent 均不能绕过此 seam。

建议业务表关键字段：

| 表 | 关键字段 |
|---|---|
| `teams` | singleton_key, id, name, created_at；singleton_key 固定且唯一 |
| `team_members` | id, team_id, name, role, created_at |
| `assignments` | id, team_id, title, requirements, rubric；id 唯一 |
| `assignment-index.yaml` | active_assignment_id, assignment_ids |
| `courses` | id, name, course_date, teacher, topic, status |
| 资料 Front Matter | id, course_id, original_file_name, source_type, content_hash, uploaded_at |
| `answer_versions` | id, assignment_id, version, source, based_on_version_id, operated_by_member_id, created_at |
| `candidate_drafts` | id, assignment_id, conversation_id, base_answer_version_id, derived_from_candidate_id, superseded_by_candidate_id, status, created_at |
| `conversations` | id, assignment_id, title, base_answer_version_id, parent_conversation_id, forked_from_message_id, status |
| `reviews` | id, target_type, target_id, review_type, result_json, total_score, created_at |
| `optimization_tasks` | id, base_answer_version_id, base_candidate_draft_id, conversation_id, mode, directions, constraints, status |
| `attachments` | id, assignment_id, purpose, original_file_name, normalized_path, content_hash |

## 7. `ui` 模块

页面采用任务流程而非裸功能页签：

1. 首次入口：选择“已有作业稿”“只有题目和资料”“先整理课程资料”。
2. 常驻状态栏：当前作业、正式版本及来源、当前对话、对话依据、资料数和待处理问题数。
3. 首页流程：创建作业 → 准备资料/稿件 → 获得初版 → 自动审查 → 定向优化 → 确认版本；每一步显示状态和一个主操作。
4. 课程资料：明确说明这里只上传 Agent 的参考资料，提供上传、列表和继续下一步。
5. 作业稿件与版本：上传用户稿、生成初版、查看历史、比较版本；空状态同时提供“上传我的作业”和“让 Agent 生成初版”。
6. 与 Agent 协作：显示对话列表、基础版本、新建空白对话、基于正式版本新建、分支、重命名和归档。
7. 优化：选择基础版本和修改强度，输入/上传方向或请求 Agent 分析，生成候选稿并展示差异。
8. 审查：展示自动审查摘要和正式评审；候选稿区提供“采用为正式新版本”“继续修改”“放弃候选稿”。

按钮必须采用动作与结果兼具的措辞，例如“上传并加入当前课程”“让 Agent 生成初版”“分析问题并提出方向”“采用为正式新版本”。不得展示未连接业务行为的单选框或按钮。关键操作前说明影响，例如“采用后创建 v3，不覆盖 v2”。

UI 只调用应用服务，不直接访问 repository 或 SDK；异常映射为用户可执行的提示，例如“未选择当前课程”“资料尚未完成索引”“请先生成评审”。

## 8. `observability` 与配置

`TraceContext` 至少包含 `request_id`、`session_id`、`active_course_id`、`intent`。工具 span 记录工具名、检索 scope、结果数、耗时、错误类别；历史检索额外记录原因。日志采用结构化格式并脱敏 API Key、授权头和不必要的正文。

配置项至少包含模型名、LLM Key、可选 OpenAI-compatible Base URL、数据根目录、全文字符预算、上传大小上限、检索结果上限、超时和重试次数。启动时验证必需配置，禁止在源代码中提供真实密钥默认值。

## 9. 测试设计

- 单元测试：意图路由、多题目/多对话隔离、候选状态机、采用前置条件、历史检索条件、上传用途、Pydantic 约束和正式版本事务。
- 集成测试：文件 repositories、Front Matter、每对话 JSONL Session、`.docx` 正文提取、本地检索、生成→审查→修正编排（使用模型替身）。
- 端到端测试：上传用户稿或生成初版，建立分支对话，输入/上传优化方向，获得经审查候选稿，采用并比较正式版本。
- UI 测试：首次入口、所有关键空状态、常驻上下文、动作型按钮及关键操作影响说明。
- 回归夹具：准备当前/历史课程冲突语料，断言默认结果不被历史资料污染。

## 10. 需求到模块追踪

| 需求 | 实现模块 | 主要验证 |
|---|---|---|
| FR-001～FR-006 | ingestion, services, repositories, ui | 导入/切换集成测试 |
| FR-007～FR-009 | services, repositories, models, ui | 单小组、多题目和每题单一正式版本约束测试 |
| FR-010～FR-015 | tools, retrieval | 过滤和冲突语料测试 |
| FR-020～FR-029 | agents, models | 路由、上下文隔离、输出契约测试 |
| FR-030～FR-034 | services, repositories, models | 重启恢复和事务测试 |
| FR-040～FR-043 | ui, models, observability | 端到端和异常测试 |
| FR-044～FR-054 | ingestion, services, repositories, agents, models | 上传、隔离、候选、审查、优化和采用测试 |
| FR-055～FR-058 | ui | 首次入口、流程、空状态和措辞测试 |
| NFR-001～NFR-010 | 全局横切模块 | 安全、配置、性能、可理解性和 trace 检查 |
