# CoursePilot 架构设计

## 1. 架构目标

架构围绕三个核心原则：主 Agent 保留控制权；当前课程优先、历史课程按需；会话记忆与业务记录分离。设计覆盖 `system-requirements.md` 中的 FR-001～FR-043 与 NFR-001～NFR-009。

## 2. 技术基线

| 层次 | 技术 |
|---|---|
| 运行环境 | Windows 11、Python 3.12 |
| UI | Streamlit |
| Agent 编排 | OpenAI Agents SDK |
| 知识检索 | 本地 Markdown 全文直传 / 超限关键词检索 |
| 会话与业务数据 | Markdown + YAML + JSONL |
| 文件输入 | 用户预处理的 Markdown / UTF-8 纯文本 |
| 数据契约 | Pydantic |
| 可观测性 | 应用内结构化 trace + 日志；关闭远端 tracing 导出 |

## 3. 系统上下文

```text
学生小组
  │ 自然语言、课程资料、唯一大作业共享答案
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
│ 小组信息 │ 唯一大作业 │ 课程选择 │ 导入 │ 对话/版本展示  │
└────────────────────────┬───────────────────────────────┘
                         ▼
┌──────────────── Application / Orchestration ───────────┐
│ Course Learning Main Agent                             │
│ ├─ 意图与课程解析    ├─ 检索策略决策                  │
│ ├─ 专业 Agent 调用   └─ 响应整合与业务保存            │
│    ├─ Notes Agent      ├─ Assignment Agent             │
│    ├─ Review Agent     └─ Revision Agent               │
└──────────────┬──────────────────────┬───────────────────┘
               ▼                      ▼
┌──────────── Tools / Domain ───────┐ ┌──── Contracts ───┐
│ Current Search │ Archive Search   │ │ Pydantic models  │
│ Course/Assignment/Answer services │ │ validation       │
│ Material ingestion and citation  │ └──────────────────┘
└──────────────┬────────────────────┘
               ▼
┌──────────────── Infrastructure ─────────────────────────┐
│ Markdown/YAML Files │ JSONL Session │ File Repositories │ Trace │
└─────────────────────────────────────────────────────────┘
```

依赖方向由外层适配器指向应用与领域接口；Agent 不直接拼接 SQL，也不能绕过受控工具读取全部课程资料。

## 5. Agent 编排设计

采用“Agent 作为工具”而非 handoff。主 Agent 在整个 run 中持有 `CourseContext`，专业 Agent 仅完成边界明确的任务并返回结构化结果。

```text
用户请求
  → 加载 CourseContext
  → 主 Agent 判断意图与输入完整性
  → 确定 active_course_id
  → 调用一个或多个专业 Agent
      → 默认 search_current_course
      → 满足策略条件时 search_course_archive
      → 返回 Pydantic 结果
  → 主 Agent 整合结果
  → 事务化保存唯一大作业的共享成果并更新上下文
  → 返回用户 + 完成 trace
```

路由不是纯关键词匹配。主 Agent 需结合当前答案、最近评审和用户表述判断。例如“优化刚才答案”且存在最近评审时调用修改 Agent；没有评审时先调用评审 Agent，再调用修改 Agent。

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

### 7.1 会话状态

`JsonlSession` 保存对话消息；运行上下文额外维护经过 Pydantic 校验的 `CourseContext`。它服务于代词解析和连续任务，不作为业务事实的唯一来源。

### 7.2 业务数据

业务文件保存一个小组、成员、唯一大作业、课程资料、共享答案、评审和修改。Markdown 保存正文及 Front Matter，YAML 保存结构化状态，JSONL 保存会话；三者目录隔离，避免生命周期和查询职责混淆。

```text
team(singleton) 1──* team_members
team(singleton) 1──1 assignment(singleton)
courses 1──* materials
assignment(singleton) 1──* answers(shared versions)
answers 1──* reviews
answers 1──* revisions *──1 reviews
revisions 1──1 answers(new shared version)
```

文件 repository 通过固定路径和写入前校验确保不能创建第二个小组或第二份作业。答案版本、评审和修改先完成全部约束校验，再通过临时文件原子替换写入。资料保存失败时不产生半成品，用户可重新上传。

## 8. 文件导入架构

```text
上传文件
 → 接受用户预处理的 .md 或 UTF-8 .txt
 → 校验编码、大小、非空内容和重复内容
 → 本地暂存
 → 附加 MaterialMetadata
 → 正文与自动生成的 YAML Front Matter 保存为单一 Markdown 文件
 → 小资料全文直传；超出字符预算时按章节进行关键词排序
```

系统不承担原始资料预处理。重复上传通过文件哈希和课程 ID 判断；同一文件内容更新时保存为新的 Markdown 资料。

## 9. 可靠性、安全与可观测性

- 对模型调用配置超时和有限重试；非幂等文件写入不做盲目重试。
- 所有业务写入使用事务；资料正文以 Markdown 文件在本地持久化。
- API Key 从环境变量/Streamlit secrets 读取并在日志中脱敏。
- 上传只允许白名单扩展名，并配置大小上限和安全文件名。
- 每个请求生成关联标识，trace 记录 Agent 路由、工具名称、过滤条件摘要、耗时和错误；不记录密钥和不必要的完整作业内容。

## 10. 关键架构决策

| 决策 | 选择 | 理由 | 未来演进触发点 |
|---|---|---|---|
| 编排框架 | OpenAI Agents SDK | 抽象少，直接练习 Agent、工具和 tracing | 需要断点恢复、人工审批、复杂状态图时评估 LangGraph |
| Agent 协作 | Agent 作为工具 | 主 Agent 保留上下文和最终控制权 | 专业 Agent 需独立接管用户会话时评估 handoff |
| 检索边界 | 两个受控工具 | 从实现层保证当前课程隔离 | 多租户时增加 tenant/user 过滤 |
| 资料检索 | 小资料全文直传，超限本地关键词检索 | 无需额外 Key，适合单小组课程资料规模 | 资料规模或召回要求显著增长时再评估向量检索 |
| 作业聚合 | 单小组 + 单例大作业 | 真实业务只有一份持续迭代的小组作业 | 出现多项目或多小组并行需求时再引入集合模型 |
| 状态存储 | JSONL Session 与业务文件分离 | 对话记忆和业务事实生命周期不同 | 多小组/部署时再评估服务端数据库 |
| 文档索引 | 先转带页码 Markdown | 引用稳定、便于验证 | 图像内容重要时增加 OCR/多模态解析 |

## 11. 需求映射

| 架构区域 | 需求 |
|---|---|
| Streamlit Presentation | FR-040、FR-043 |
| Main/Professional Agents | FR-020～FR-029、FR-041 |
| Retrieval Policy & Tools | FR-010～FR-015、NFR-001～NFR-002 |
| Team & Singleton Assignment | FR-007～FR-009、FR-030～FR-034 |
| Material Ingestion | FR-002～FR-005 |
| Session & Business Persistence | FR-030～FR-034、NFR-003 |
| Trace & Logging | FR-042、NFR-008 |
| 模块边界与配置 | NFR-004～NFR-007、NFR-009 |
