# CoursePilot 架构设计

## 1. 架构目标

架构围绕五个核心原则：主 Agent 保留控制权；当前课程优先、历史课程按需；对话记忆与业务记录分离；Agent 输出先形成候选稿、用户采用后才进入正式版本链；生成和优化默认经过独立自动审查。设计覆盖 `system-requirements.md` 中的 FR-001～FR-058 与 NFR-001～NFR-010。

## 2. 技术基线

| 层次 | 技术 |
|---|---|
| 运行环境 | Windows 11、Python 3.12 |
| UI | Streamlit |
| Agent 编排 | OpenAI Agents SDK |
| 知识检索 | 本地 Markdown 全文直传 / 超限关键词检索 |
| 会话与业务数据 | Markdown + YAML + JSONL |
| 文件输入 | 课程资料 `.md`/`.txt`；作业稿与优化方向 `.md`/`.txt`/`.docx` |
| 数据契约 | Pydantic |
| 可观测性 | 应用内结构化 trace + 日志；关闭远端 tracing 导出 |

## 3. 系统上下文

```text
学生小组
  │ 自然语言、课程资料、用户作业稿、优化方向和采用决策
  ▼
CoursePilot
  ├── OpenAI-compatible Model API：推理与工具选择
  ├── 本地 Markdown 文件：课程资料正文
  └── 本地文件：Markdown 正文、YAML 状态、JSONL 会话
```

系统信任边界外只包含配置的模型服务；LLM Key 和模型返回结果需经过配置、校验和错误处理。课程资料不上传到外部检索服务。

## 4. 逻辑架构

```text
┌──────────────── Streamlit Presentation ────────────────┐
│ 流程导航 │ 课程/题目 │ 稿件版本 │ 对话分支 │ 优化/审查/采用 │
└────────────────────────┬───────────────────────────────┘
                         ▼
┌──────────────── Application / Orchestration ───────────┐
│ Course Learning Main Agent                             │
│ ├─ 意图与课程解析    ├─ 检索策略决策                  │
│ ├─ 对话/版本绑定     ├─ 生成→审查→有界修正            │
│ └─ 候选稿与采用编排  └─ 响应整合与业务保存            │
│    ├─ Notes Agent      ├─ Assignment Agent             │
│    ├─ Review Agent     └─ Revision Agent               │
└──────────────┬──────────────────────┬───────────────────┘
               ▼                      ▼
┌──────────── Tools / Domain ───────┐ ┌──── Contracts ───┐
│ Current Search │ Archive Search   │ │ Pydantic models  │
│ Course/Assignment/Draft/Conversation services │ validation │
│ Material ingestion and citation  │ └──────────────────┘
└──────────────┬────────────────────┘
               ▼
┌──────────────── Infrastructure ─────────────────────────┐
│ Markdown/YAML Files │ JSONL Session │ File Repositories │ Trace │
└─────────────────────────────────────────────────────────┘
```

依赖方向由外层适配器指向应用与领域接口；Agent 不直接拼接 SQL，也不能绕过受控工具读取全部课程资料。

## 5. Agent 编排设计

采用“Agent 作为工具”而非 handoff。主 Agent 在整个 run 中持有 `ConversationContext`，专业 Agent 仅完成边界明确的任务并返回结构化结果。

```text
用户请求
  → 加载 ConversationContext 与其绑定的正式版本
  → 主 Agent 判断意图与输入完整性
  → 确定 active_course_id
  → 调用一个或多个专业 Agent
      → 默认 search_current_course
      → 满足策略条件时 search_course_archive
      → 返回 Pydantic 结果
  → 生成或优化任务：保存临时候选稿
  → 独立 ReviewAgent 审查候选稿
  → 对可自动修复问题执行至多一次修正并复核
  → 保存 ready_for_adoption 候选稿及审查摘要
  → 返回用户；仅在用户明确采用时事务化创建正式版本
  → 完成 trace
```

路由不是纯关键词匹配。主 Agent 需结合对话绑定版本、优化任务和用户表述判断。修改请求始终先获得独立审查；用户未提供优化方向时先返回问题分析供选择，不直接猜测修改目标。对话之间不共享消息，只有用户显式选择的正式版本、课程资料和附件可以成为新对话输入。

## 6. 检索架构与隔离策略

系统只暴露两个语义明确的应用工具：

```python
search_current_course(query, context)   # 强制 course_id == active_course_id
search_course_archive(query, reason, context)  # 强制排除当前课程且记录 reason
```

策略执行顺序：

1. 验证当前课程存在。
2. 使用当前课程过滤资料；总正文不超过字符预算时直接返回全文，否则最多返回 5 个相关章节。
3. 判断当前证据是否足以覆盖任务要求。
4. 仅在 FR-013 条件成立时发起历史检索。
5. 合并时当前课程证据排序优先；冲突时标记并以当前课程为准。
6. 输出 `SourceRef`，包含材料、课程、页码/章节和片段。

此边界同时在工具实现和 Agent 指令中约束，避免仅依赖提示词。

## 7. 数据与状态架构

### 7.1 对话状态

每条 `Conversation` 对应独立 `JsonlSession`；运行上下文额外维护经过 Pydantic 校验的 `ConversationContext`。上下文服务于本对话的代词解析和连续任务，不作为业务事实的唯一来源。新对话默认绑定当前正式版本但不复制旧消息；分支对话记录 `parent_conversation_id`、`forked_from_message_id`，并在新 Session 中保存截至该消息的不可变快照。

### 7.2 业务数据

业务文件保存一个小组、成员、多道题目、课程资料、正式答案版本、候选稿、评审、优化任务、对话元数据和附件。Markdown 保存规范化正文及 Front Matter，YAML 保存结构化状态，JSONL 保存各对话消息，上传目录保存原件；四者目录隔离，避免生命周期和查询职责混淆。

```text
team(singleton) 1──* team_members
team(singleton) 1──* assignments
courses 1──* materials
assignments 1──* answers(shared versions)
answers 1──* reviews
assignments 1──* conversations *──1 answers(base version)
answers 1──* candidate_drafts
optimization_tasks 1──1 answers(base version)
optimization_tasks 1──* candidate_drafts
candidate_drafts 1──* reviews(auto)
candidate_drafts 0..1──1 answers(adopted version)
candidate_drafts 0..1──* candidate_drafts(derived candidates)
answers 1──* reviews(formal)
assignments 1──* attachments
```

文件 repository 通过固定工作区文件确保不能创建第二个小组，通过索引分别维护 `active_assignment_id`、`active_course_id` 和 `active_conversation_id`。每道题的正式版本、候选稿、评审、优化任务和对话在独立目录内完成约束校验。采用候选稿或上传新正式稿时，通过临时文件原子替换更新正式版本指针；候选稿可以并存，但同题只有一条正式版本链。

## 8. 文件导入架构

文件导入存在两个独立 seam，不能用“上传”一个模糊入口混合：

- `MaterialIngestion`：课程资料，只接收 `.md`/`.txt`，为检索建立课程元数据和章节。
- `ArtifactIngestion`：作业稿件与优化方向，接收 `.md`/`.txt`/`.docx`，保存原件并提取规范化正文，不进入课程资料检索库。

```text
上传文件
 → 接受用户预处理的 .md 或 UTF-8 .txt
 → 校验编码、大小、非空内容和重复内容
 → 本地暂存
 → 附加 MaterialMetadata
 → 正文与自动生成的 YAML Front Matter 保存为单一 Markdown 文件
 → 小资料全文直传；超出字符预算时按章节进行关键词排序
```

课程资料仍由用户预处理。作业稿件上传必须显式选择设为初版、创建新正式版本或仅作参考附件；已有正式版本时禁止静默覆盖。优化方向作为 `OptimizationTask` 输入保存，不直接成为答案正文。

## 9. 候选稿、审查与采用事务

```text
Generate/Revise
 → candidate:draft
 → isolated ReviewAgent
 → bounded correction (最多一次)
 → candidate:ready_for_adoption
 → 用户查看差异与审查摘要
 → 采用：事务化创建 answer version + candidate:adopted
   或放弃：candidate:discarded
```

ReviewAgent 只接收题目、评分标准、课程证据和候选正文，不接收生成 Agent 的隐藏推理或旧对话消息。自动审查与正式评审共享结果契约，但以 `review_type` 区分。任何 Agent 都无权调用正式版本指针更新；采用动作是唯一外部 seam。继续修改候选稿会创建新的派生候选稿，原候选稿保留并标记 `superseded`，防止同一候选链上两个结果同时被采用。

## 10. 可靠性、安全与可观测性

- 对模型调用配置超时和有限重试；非幂等文件写入不做盲目重试。
- 所有业务写入使用事务；资料正文以 Markdown 文件在本地持久化。
- API Key 从环境变量/Streamlit secrets 读取并在日志中脱敏。
- 上传只允许白名单扩展名，并配置大小上限和安全文件名。
- `.docx` 仅提取文本，不执行宏或嵌入对象；原件与规范化正文使用不同目录。
- 每个请求生成关联标识，trace 记录 Agent 路由、工具名称、过滤条件摘要、耗时和错误；不记录密钥和不必要的完整作业内容。

## 11. 关键架构决策

| 决策 | 选择 | 理由 | 未来演进触发点 |
|---|---|---|---|
| 编排框架 | OpenAI Agents SDK | 抽象少，直接练习 Agent、工具和 tracing | 需要断点恢复、人工审批、复杂状态图时评估 LangGraph |
| Agent 协作 | Agent 作为工具 | 主 Agent 保留上下文和最终控制权 | 专业 Agent 需独立接管用户会话时评估 handoff |
| 检索边界 | 两个受控工具 | 从实现层保证当前课程隔离 | 多租户时增加 tenant/user 过滤 |
| 资料检索 | 小资料全文直传，超限本地关键词检索 | 无需额外 Key，适合单小组课程资料规模 | 资料规模或召回要求显著增长时再评估向量检索 |
| 作业聚合 | 单小组 + 多题目 + 单一正式版本指针 + 可并存候选稿 | 支持探索方案又不混淆正式成果 | 需要多人并发编辑时引入冲突合并 |
| 对话模型 | 每题多对话，显式绑定基础版本 | 用户可隔离探索 Agent 方案与自己的方案 | 需要跨对话知识复用时增加显式引用 |
| 结果发布 | 候选稿经用户采用后进入正式版本链 | 防止 Agent 静默覆盖用户成果 | 批处理场景再评估可配置自动采用 |
| 审查编排 | 生成/优化后强制独立审查并至多一次修正 | 提高质量且避免无限 Agent 循环 | 复杂审批链出现时评估状态图框架 |
| 状态存储 | 每对话 JSONL 与业务文件分离 | 对话记忆和业务事实生命周期不同 | 多小组/部署时再评估服务端数据库 |
| 文档索引 | 先转带页码 Markdown | 引用稳定、便于验证 | 图像内容重要时增加 OCR/多模态解析 |

## 12. 需求映射

| 架构区域 | 需求 |
|---|---|
| Streamlit Presentation | FR-040、FR-043、FR-055～FR-058、NFR-010 |
| Main/Professional Agents | FR-020～FR-029、FR-041 |
| Retrieval Policy & Tools | FR-010～FR-015、NFR-001～NFR-002 |
| Team, Assignments & Formal Answers | FR-007～FR-009、FR-030～FR-034 |
| Conversations, Candidates & Optimization | FR-044～FR-054 |
| Material Ingestion | FR-002～FR-005 |
| Session & Business Persistence | FR-030～FR-034、NFR-003 |
| Trace & Logging | FR-042、NFR-008 |
| 模块边界与配置 | NFR-004～NFR-007、NFR-009 |
