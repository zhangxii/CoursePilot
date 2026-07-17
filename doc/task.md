
项目名称：CoursePilot
你这个目的下，**应该用 Agent 框架**。因为你不仅是在做一个课程工具，还要练习：

* Agent 如何判断用户意图；
* 如何选择资料范围；
* 如何调用检索、评分、修改等工具；
* 如何维护当前课程上下文；
* 如何观察和调试完整执行链路。

但不建议直接上复杂 LangGraph。当前最合适的是：

# 最终技术选型

```text
Windows 11
Python 3.12
Streamlit
OpenAI Agents SDK
Markdown 本地资料库（小规模全文输入，超预算后关键词检索）
YAML + JSONL 文件持久化
Markdown / UTF-8 纯文本文件
Pydantic
```

OpenAI Agents SDK本身已经提供Agent循环、函数工具、Agent作为工具、会话记忆和Tracing，抽象比较少，适合第一次系统练习Agent开发。([OpenAI GitHub Pages][1])

---

# 一、建议做成“1个主Agent + 4个专业Agent”

```text
课程学习主Agent
├── 笔记总结Agent
├── 作业完成Agent
├── 作业评审Agent
└── 作业修改Agent
```

主Agent负责：

1. 判断用户现在要做什么；
2. 确定当前课程；
3. 决定检索当前资料还是历史资料；
4. 调用对应专业Agent；
5. 整理最终输出。

专业Agent负责单一任务。

这比“四个固定按钮”更像真正的智能体，同时复杂度仍然可控。Agents SDK支持把一个Agent作为另一个Agent的工具，也支持Handoff；你的场景更适合“Agent作为工具”，因为主Agent应该保留对整个任务的控制权。([OpenAI GitHub Pages][1])

---

# 二、资料要分成“当前课程”和“历史课程”

你的关键约束是：

> 课程资料会不断增加，但课堂作业主要围绕当前课程展开。

所以不能每次把所有课程都检索一遍，否则容易出现：

* 旧课程内容干扰当前作业；
* 引入老师尚未讲过的方法；
* 答案看起来丰富，但偏离本次课程要求；
* 检索结果越来越杂；
* Token和响应时间持续增长。

推荐采用以下结构：

```text
全部课程知识库
├── 当前课程资料
│   ├── 当前PPT
│   ├── 当天课堂笔记
│   ├── 当前作业题
│   └── 老师当前反馈
│
└── 历史课程资料
    ├── 用户需求
    ├── 系统需求与DFX
    ├── 架构设计
    ├── 方案选型
    ├── 模块设计
    ├── 测试理念
    └── 业务排障
```

每个文件需要附带元数据：

```python
{
    "course_id": "module_design_20260716",
    "course_name": "模块设计的理念及思维",
    "course_date": "2026-07-16",
    "teacher": "刘飞",
    "topic": "模块设计",
    "material_type": "ppt",
    "status": "current"
}
```

本系统把正文和自动生成的 YAML Front Matter 保存为独立 Markdown 文件；检索工具在本地强制执行 `course_id` 和 `status` 过滤，只把正文交给模型。当前检索范围的总正文不超过配置预算时全部提供，超过预算后才按关键词选取相关章节。

---

# 三、不要让Agent自由检索所有资料

应该给它两个语义明确的工具。

## 工具一：检索当前课程

```python
search_current_course(query)
```

固定限制：

```text
course_id = 当前课程ID
```

用于：

* 总结当前课堂笔记；
* 完成当前作业；
* 提取当前评分标准；
* 判断答案是否符合本节课要求。

## 工具二：检索历史课程

```python
search_course_archive(query)
```

只在以下情况调用：

* 用户明确要求结合以前课程；
* 当前课程引用了前序知识；
* 当前资料不足以解释某个概念；
* 修改答案时需要检查前后课程逻辑一致性。

主Agent的指令应明确：

```text
默认只检索当前课程资料。
只有当前资料无法支持任务，或者用户明确要求结合历史内容时，
才能调用历史课程检索工具。
历史资料不得覆盖当前课程老师给出的定义、标准和任务要求。
```

这个检索策略是整个系统最重要的设计之一。

---

# 四、四个Agent分别怎么设计

## 1. 笔记总结Agent

可用工具：

```text
search_current_course
search_course_archive
save_course_notes
```

默认流程：

```text
识别当前课程
→ 检索当前课程全部章节
→ 提取课程目标和知识结构
→ 生成结构化笔记
→ 标注资料来源
→ 保存笔记
```

输出结构：

```text
课程要解决的问题
核心概念
关键分析方法
课程案例
容易犯的错误
老师强调的判断标准
如何用于课堂实践
与前序课程的关系
```

它不能只做普通摘要，而要结合实践告诉你：

> 这个知识点做题时具体怎么用。

---

## 2. 作业完成Agent

可用工具：

```text
search_current_course
search_course_archive
get_current_assignment
```

建议让它自己决定检索步骤，但规定必须先分析任务：

```text
读取作业要求
→ 判断真正的任务目标
→ 检索当前课程标准
→ 判断资料是否充分
→ 必要时检索历史课程
→ 生成答案
→ 对照题目进行一次自检
```

输出中应包含：

```text
任务理解
正式答案
答案使用的课程依据
仍存在的不确定信息
```

不要让它直接从“题目”跳到“正式答案”，否则很容易写得完整却偏题。

---

## 3. 作业评审Agent

这个Agent要与作业完成Agent分离。

原因是：

> 生成答案的Agent很容易延续自己的推理，对自己的答案评价偏高。

评审Agent只接收：

```text
作业题目
当前课程资料
老师要求
评分标准
待评审答案
```

不要把作业完成Agent的中间思考或生成过程传给它。

评审流程：

```text
提取任务要求
→ 建立评分维度
→ 检索对应课程依据
→ 逐项评分
→ 找出严重问题
→ 模拟老师追问
→ 给出修改方向
```

输出使用Pydantic固定结构：

```python
class ReviewResult(BaseModel):
    total_score: int
    dimension_scores: list
    strengths: list[str]
    critical_issues: list
    likely_teacher_questions: list[str]
    revision_priorities: list[str]
```

重点是每项扣分都必须包含：

```text
扣了多少分
问题在哪里
依据是什么
为什么构成问题
应该怎么修改
```

---

## 4. 作业修改Agent

可用工具：

```text
search_current_course
search_course_archive
get_review_result
```

它不能在没有评分报告时直接随意重写。

流程：

```text
读取原答案
→ 读取评审结果
→ 按严重程度排序
→ 检索相关课程依据
→ 逐项修改
→ 再次检查修改是否解决问题
→ 输出修改稿和修改说明
```

提供两种模式：

### 保守修改

尽量保留原答案结构，只修正明确问题。

### 深度重构

重新组织目标、分析、方案、取舍和结论。

这样你们赶时间时可以直接保守修改，答案逻辑明显有问题时再深度重构。

---

# 五、主Agent应该维护什么上下文

在Session中保存：

```python
class CourseContext(BaseModel):
    active_course_id: str
    active_course_name: str
    active_assignment_id: str | None
    assignment_title: str | None
    assignment_requirements: str | None
    current_answer: str | None
    latest_review: dict | None
    answer_version: int = 1
```

例如用户说：

> 帮我们把刚才的答案再优化一下。

主Agent需要知道：

* “刚才的答案”是哪一版；
* 当前是哪门课；
* 上一次评分结果是什么；
* 用户要局部修改还是完整重构。

Agents SDK 的 Session 接口能够在多轮运行间维护会话历史；本项目使用 JSONL adapter 持久化消息。([OpenAI GitHub Pages][3])

Markdown/YAML 还要单独保存业务数据：

```text
courses
materials
assignments
answers
reviews
revisions
```

**JSONL Session 是对话记忆，Markdown/YAML 是业务记录，两者不要混为一谈。**

---

# 六、课程资料怎么导入

系统首版只接收用户预处理好的 UTF-8 `.md` 或 `.txt`。如果来源是 PDF/PPTX，请在上传前自行提取文本并保留所需页码或章节，例如：

```text
原始课程资料
→ 用户自行提取和校对
→ 整理成带页码/章节的 Markdown 或纯文本
→ 上传 CoursePilot
→ 统一保存为 Markdown 文件
```

转换结果类似：

```markdown
# 《模块设计的理念及思维》

## 第1页
课程标题……

## 第2页
模块设计的目标……

## 第3页
模块职责和边界……
```

这样Agent回答时可以引用：

> 依据《模块设计》第12页，模块目标需要由系统目标推导。

系统不会读取原始 PDF/PPTX，因此页码与文本质量由上传前的预处理结果决定。

---

# 七、推荐的Agent执行架构

```text
用户输入
   ↓
课程学习主Agent
   ↓
判断当前意图
   ├── 总结资料 → 笔记Agent
   ├── 完成作业 → 作业Agent
   ├── 评分评价 → 评审Agent
   └── 修改答案 → 修改Agent
                    ↓
          默认检索当前课程
                    ↓
      当前资料不足才检索历史课程
                    ↓
              输出结构化结果
                    ↓
          保存答案、评分与版本
```

主Agent不是简单的关键词路由器，它还负责判断：

* 当前课程是什么；
* 是否需要历史知识；
* 当前输入缺少什么；
* 应先评审还是直接修改；
* 是否需要调用多个专业Agent。

---

# 八、为什么现在选Agents SDK，而不是LangGraph

LangGraph更适合：

* 有严格的节点执行顺序；
* 需要长流程断点恢复；
* 需要复杂循环和条件边；
* 需要人工审批后继续；
* 需要查看和修改每一步状态。

它提供图状态、检查点、持久化、长短期记忆和人工中断等能力。([Docs by LangChain][5])

但你的主要流程只有：

```text
识别意图
→ 检索资料
→ 调用专业Agent
→ 输出和保存
```

用LangGraph会让你先花大量时间学习State、Node、Edge、Checkpoint，而不是练习Agent的工具选择、上下文管理和检索策略。

因此建议：

> **第一版使用OpenAI Agents SDK；做到需要复杂状态机、可暂停恢复和人工审核时，再用LangGraph重构。**

---

# 九、最终建议版本

```text
前端：Streamlit
Agent框架：OpenAI Agents SDK
Agent模式：1个主Agent + 4个专业Agent作为工具
当前会话：JSONL Session
业务数据：Markdown + YAML 文件
长期资料：带 YAML Front Matter 的本地 Markdown 文件
检索策略：当前课程优先，历史课程按需
文件输入：用户预处理的 Markdown / UTF-8 纯文本
输出约束：Pydantic
调试：应用结构化日志与本地 trace 事件
```

应用层记录检索范围、工具调用和专业 Agent 执行顺序，便于观察主 Agent 为什么选择某个资料范围，以及哪一步导致结果偏离；运行轨迹不依赖 OpenAI tracing 服务。

这套设计既能较快完成产品，又能真正练到**Agent编排、工具调用、RAG、记忆、上下文隔离、结构化输出和可观测性**，而不是只给普通大模型应用套一个“智能体”名字。

[1]: https://openai.github.io/openai-agents-python/?utm_source=chatgpt.com
[2]: https://developers.openai.com/api/docs/guides/retrieval?utm_source=chatgpt.com
[3]: https://openai.github.io/openai-agents-python/sessions/?utm_source=chatgpt.com
[4]: https://developers.openai.com/api/docs/guides/tools-file-search?utm_source=chatgpt.com
[5]: https://docs.langchain.com/oss/python/langgraph/persistence?utm_source=chatgpt.com
[6]: https://openai.github.io/openai-agents-python/tracing/?utm_source=chatgpt.com
