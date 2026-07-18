"""Guided Streamlit workspace built on framework-neutral view state."""

from datetime import date
from typing import Any, Literal, Protocol

import streamlit as st

from coursepilot.models import (
    AnswerRecord,
    AnswerVersionComparison,
    AssignmentUploadPurpose,
    CandidateComparison,
    CandidateDraft,
    Conversation,
    OptimizationTask,
    OptimizationTaskStatus,
    RevisionMode,
)
from coursepilot.ui.view_model import WorkspaceView


class WorkspaceActions(Protocol):
    def activate_course(self, course_id: str) -> None: ...
    def create_course(
        self, course_id: str, name: str, course_date: date, teacher: str, topic: str
    ) -> None: ...
    def activate_assignment(self, assignment_id: str) -> None: ...
    def create_assignment(self, assignment_id: str, title: str, requirements: str) -> None: ...
    def upload_material(self, file_name: str, content: bytes) -> None: ...
    def upload_assignment(
        self,
        file_name: str,
        content: bytes,
        purpose: AssignmentUploadPurpose,
        version_note: str,
    ) -> Any: ...
    def create_conversation(
        self, title: str, *, blank: bool = False, answer_version_id: str | None = None
    ) -> Conversation: ...
    def activate_conversation(self, conversation_id: str) -> Conversation: ...
    def rename_conversation(self, conversation_id: str, title: str) -> Conversation: ...
    def archive_conversation(self, conversation_id: str) -> Conversation: ...
    def branch_conversation(
        self, parent_conversation_id: str, message_id: str, title: str
    ) -> Conversation: ...
    def conversation_messages(self, conversation_id: str) -> list[dict[str, object]]: ...
    def run_agent(self, message: str) -> str: ...
    def compare_candidate(self, candidate_id: str) -> CandidateComparison: ...
    def compare_answer_versions(
        self, source_answer_id: str, result_answer_id: str
    ) -> AnswerVersionComparison: ...
    def request_formal_review(self, answer_version_id: str) -> str: ...
    def adopt_candidate(self, candidate_id: str) -> AnswerRecord: ...
    def discard_candidate(self, candidate_id: str) -> CandidateDraft: ...
    def continue_candidate(self, candidate_id: str, content: str) -> CandidateDraft: ...
    def start_optimization(
        self,
        *,
        mode: RevisionMode,
        user_direction: str | None = None,
        base_answer_version_id: str | None = None,
        base_candidate_id: str | None = None,
        preserve_constraints: list[str] | None = None,
        prohibited_changes: list[str] | None = None,
        format_constraints: list[str] | None = None,
        max_words: int | None = None,
        max_characters: int | None = None,
    ) -> OptimizationTask: ...
    def upload_optimization_direction(
        self, task_id: str, file_name: str, content: bytes
    ) -> OptimizationTask: ...
    def analyze_optimization(self, task_id: str) -> OptimizationTask: ...
    def confirm_optimization_suggestions(
        self, task_id: str, suggestion_ids: list[str], supplemental_direction: str | None = None
    ) -> OptimizationTask: ...
    def generate_optimization(self, task_id: str) -> OptimizationTask: ...


SECTIONS = ["总览", "课程资料", "作业版本", "对话", "定向优化"]


def render_workspace(view: WorkspaceView, controller: WorkspaceActions) -> None:
    _initialize_state()
    st.set_page_config(
        page_title="CoursePilot 作业工作区",
        page_icon=":material/school:",
        layout="wide",
    )
    st.title("CoursePilot 作业工作区")
    st.caption("从课程资料和你的稿件出发，生成、审查、优化，再由你决定正式版本。")
    _render_sidebar(view, controller)
    _render_context_bar(view)
    if _is_first_use(view):
        _render_first_use()
    _render_workflow(view)
    selected = st.segmented_control(
        "工作区",
        SECTIONS,
        default=st.session_state.workspace_section,
        key="workspace_navigation",
        width="stretch",
    )
    section = selected or "总览"
    st.session_state.workspace_section = section
    if section == "总览":
        _render_overview(view)
    elif section == "课程资料":
        _render_materials(view, controller)
    elif section == "作业版本":
        _render_assignments(view, controller)
    elif section == "对话":
        _render_conversation(view, controller)
    else:
        _render_optimization(view, controller)


def _initialize_state() -> None:
    st.session_state.setdefault("workspace_section", "总览")
    st.session_state.setdefault("optimization_task_id", None)
    st.session_state.setdefault("chat_messages", {})


def _render_sidebar(view: WorkspaceView, controller: WorkspaceActions) -> None:
    with st.sidebar:
        st.subheader(view.team.name)
        st.caption(" · ".join(member.name for member in view.team.members))
        active_course = view.active_course
        selected_course = st.selectbox(
            "当前课程",
            view.courses,
            index=(
                None
                if active_course is None
                else next(i for i, item in enumerate(view.courses) if item.id == active_course.id)
            ),
            placeholder="选择课程",
            format_func=lambda item: item.name,
            key=f"course_selector_{active_course.id if active_course else 'none'}",
        )
        if (
            selected_course is not None
            and (active_course is None or selected_course.id != active_course.id)
            and st.button("切换到这门课程", icon=":material/swap_horiz:", width="stretch")
        ):
            controller.activate_course(selected_course.id)
            st.rerun()
        with (
            st.expander("添加课程", icon=":material/add:"),
            st.form("create_course_form"),
        ):
            name = st.text_input("课程名称")
            course_id = st.text_input("课程 ID")
            course_date = st.date_input("课程日期")
            teacher = st.text_input("教师")
            topic = st.text_input("课程主题")
            if st.form_submit_button("创建并设为当前课程", icon=":material/add_circle:"):
                controller.create_course(course_id, name, course_date, teacher, topic)
                st.rerun()

        selected_assignment = st.selectbox(
            "当前作业",
            view.assignments,
            index=next(
                i for i, item in enumerate(view.assignments) if item.id == view.assignment.id
            ),
            format_func=lambda item: item.title,
            key=f"assignment_selector_{view.assignment.id}",
        )
        if selected_assignment.id != view.assignment.id and st.button(
            "切换到这项作业", icon=":material/swap_horiz:", width="stretch"
        ):
            controller.activate_assignment(selected_assignment.id)
            st.session_state.optimization_task_id = None
            st.rerun()
        with (
            st.expander("添加作业", icon=":material/add:"),
            st.form("create_assignment_form"),
        ):
            assignment_id = st.text_input("作业 ID")
            title = st.text_input("作业标题")
            requirements = st.text_area("题目要求")
            if st.form_submit_button("创建并进入这项作业", icon=":material/add_circle:"):
                controller.create_assignment(assignment_id, title, requirements)
                st.rerun()

        active_conversation = view.active_conversation
        available = [item for item in view.conversations if item.status.value == "active"]
        if available:
            conversation_key = "none" if active_conversation is None else active_conversation.id
            selected_conversation = st.selectbox(
                "当前对话",
                available,
                index=next(
                    (
                        i
                        for i, item in enumerate(available)
                        if active_conversation is not None and item.id == active_conversation.id
                    ),
                    0,
                ),
                format_func=lambda item: item.title,
                key=f"conversation_selector_{conversation_key}",
            )
            if (
                active_conversation is None or selected_conversation.id != active_conversation.id
            ) and st.button("切换到这条对话", icon=":material/forum:", width="stretch"):
                controller.activate_conversation(selected_conversation.id)
                st.rerun()
        with st.expander("管理对话", icon=":material/forum:"):
            _render_conversation_management(view, controller)


def _render_conversation_management(view: WorkspaceView, controller: WorkspaceActions) -> None:
    with st.form("new_conversation_form"):
        title = st.text_input("新对话名称", placeholder="例如：我的方案后续优化")
        base_choice = st.segmented_control(
            "从哪里开始",
            ["当前正式版本", "空白对话"],
            default="当前正式版本",
        )
        if st.form_submit_button("开启新对话", icon=":material/add_comment:"):
            controller.create_conversation(
                title,
                blank=base_choice == "空白对话",
                answer_version_id=(
                    view.formal_answer.id
                    if base_choice == "当前正式版本" and view.formal_answer is not None
                    else None
                ),
            )
            st.rerun()
    active = view.active_conversation
    if active is not None:
        rename = st.text_input("重命名当前对话", value=active.title, key="rename_conversation")
        with st.container(horizontal=True):
            if st.button("保存新名称", icon=":material/edit:"):
                controller.rename_conversation(active.id, rename)
                st.rerun()
            if st.button("归档当前对话", icon=":material/archive:"):
                controller.archive_conversation(active.id)
                st.rerun()


def _render_context_bar(view: WorkspaceView) -> None:
    with st.container(border=True):
        columns = st.columns(4)
        columns[0].metric("当前作业", view.assignment.title)
        formal = view.formal_answer
        columns[1].metric(
            "正式版本",
            "尚未创建" if formal is None else f"v{formal.version}",
            help="只有你采用候选稿或上传新正式稿时才会变化。",
        )
        conversation = view.active_conversation
        basis = "空白"
        if conversation is not None and conversation.base_answer_version_id is not None:
            bound = next(
                (
                    item
                    for item in view.answer_versions
                    if item.id == conversation.base_answer_version_id
                ),
                None,
            )
            basis = (
                f"v{bound.version}"
                if bound is not None
                else conversation.base_answer_version_id[:8]
            )
        columns[2].metric(
            "当前对话",
            "尚未创建" if conversation is None else conversation.title,
            delta=None if conversation is None else f"依据：{basis}",
        )
        columns[3].metric(
            "资料与待处理",
            f"{len(view.materials)} 份课程资料",
            delta=f"{view.pending_issue_count} 项待处理",
            delta_color="off",
        )
        source = "无"
        if formal is not None:
            source = "用户上传" if formal.source.value == "user_upload" else "采用候选稿"
        st.caption(f"正式版本来源：{source} · 课程、作业和对话可独立切换。")


def _is_first_use(view: WorkspaceView) -> bool:
    return view.formal_answer is None and not view.materials and not view.candidates


def _render_first_use() -> None:
    st.subheader("从哪里开始？")
    st.caption("选择最符合你当前材料的入口，系统会带你进入对应步骤。")
    columns = st.columns(3)
    entries = (
        (
            "上传已有作业稿",
            "我已经有初稿或修改稿，希望导入后继续审查和优化。",
            "作业版本",
            ":material/upload_file:",
        ),
        (
            "上传题目资料并生成初版",
            "我只有题目和课程资料，希望 Agent 先生成候选初版。",
            "课程资料",
            ":material/auto_awesome:",
        ),
        (
            "先整理课程资料",
            "我想先建立课程资料库，再开始作业。",
            "课程资料",
            ":material/library_books:",
        ),
    )
    for column, (label, description, target, icon) in zip(columns, entries, strict=True):
        with column.container(border=True, height="stretch"):
            st.subheader(label)
            st.write(description)
            st.button(
                f"选择：{label}",
                key=f"first_use_{target}_{label}",
                icon=icon,
                width="stretch",
                on_click=_select_section,
                args=(target,),
            )


def _select_section(section: str) -> None:
    st.session_state.workspace_section = section
    st.session_state.workspace_navigation = section


def _render_workflow(view: WorkspaceView) -> None:
    formal = view.formal_answer
    has_ready_candidate = any(item.status.value == "ready_for_adoption" for item in view.candidates)
    has_draft_candidate = any(item.status.value == "draft" for item in view.candidates)
    has_ready_optimization = any(
        item.status is OptimizationTaskStatus.READY_FOR_DECISION for item in view.optimization_tasks
    )
    has_active_optimization = any(
        item.status is not OptimizationTaskStatus.READY_FOR_DECISION
        for item in view.optimization_tasks
    )
    steps = (
        ("1 创建作业", "已完成"),
        (
            "2 准备资料/稿件",
            "已完成" if view.materials or view.attachments or formal else "进行中",
        ),
        (
            "3 获得初版",
            (
                "已完成"
                if formal or has_ready_candidate
                else "进行中"
                if has_draft_candidate
                else "未开始"
            ),
        ),
        (
            "4 自动审查",
            "已完成" if has_ready_candidate else "进行中" if has_draft_candidate else "未开始",
        ),
        (
            "5 定向优化",
            (
                "需处理"
                if has_ready_optimization
                else "进行中"
                if has_active_optimization
                else "未开始"
            ),
        ),
        (
            "6 确认版本",
            (
                "已完成"
                if formal and formal.version > 1
                else "需处理"
                if has_ready_candidate
                else "未开始"
            ),
        ),
    )
    styles: dict[
        str,
        tuple[
            str,
            Literal["red", "orange", "yellow", "blue", "green", "violet", "gray"],
        ],
    ] = {
        "已完成": (":material/check_circle:", "green"),
        "进行中": (":material/progress_activity:", "blue"),
        "需处理": (":material/error:", "orange"),
        "未开始": (":material/radio_button_unchecked:", "gray"),
    }
    with st.container(border=True):
        st.subheader("当前流程")
        with st.container(horizontal=True):
            for label, status in steps:
                icon, color = styles[status]
                st.badge(f"{label} · {status}", icon=icon, color=color)
        next_section, next_label = _next_action(view)
        st.button(
            next_label,
            type="primary",
            icon=":material/arrow_forward:",
            on_click=_select_section,
            args=(next_section,),
        )


def _next_action(view: WorkspaceView) -> tuple[str, str]:
    if not view.materials and not view.attachments and view.formal_answer is None:
        return "作业版本", "下一步：上传已有作业稿"
    if view.formal_answer is None and not view.candidates:
        return "对话", "下一步：让 Agent 生成候选初版"
    if any(item.status.value == "ready_for_adoption" for item in view.candidates):
        return "作业版本", "下一步：审阅并决定候选稿"
    return "定向优化", "下一步：开始定向优化"


def _render_overview(view: WorkspaceView) -> None:
    st.subheader("下一步做什么")
    if view.active_course is None:
        st.info(
            "先在左侧添加课程，课程资料和 Agent 检索都会绑定当前课程。",
            icon=":material/add_circle:",
        )
    elif view.formal_answer is None and not view.candidates:
        st.info(
            "上传已有作业稿，或进入“对话”让 Agent 生成候选初版。",
            icon=":material/arrow_forward:",
        )
    elif any(item.status.value == "ready_for_adoption" for item in view.candidates):
        st.info(
            "已有完成自动审查的候选稿。进入“作业版本”查看差异并决定采用、继续修改或放弃。",
            icon=":material/rule:",
        )
    else:
        st.info(
            "进入“定向优化”输入方向；如果没有方向，可以让 Agent 先分析问题。",
            icon=":material/tune:",
        )
    with st.container(border=True):
        st.subheader(view.assignment.title)
        st.write(view.assignment.requirements)


def _render_materials(view: WorkspaceView, controller: WorkspaceActions) -> None:
    st.header("课程资料")
    st.caption("这里的资料会进入当前课程检索库；不要在这里上传你的作业稿。")
    if view.active_course is None:
        st.warning("请先在左侧创建或选择课程，再上传课程资料。")
        return
    with st.container(border=True):
        upload = st.file_uploader(
            "上传课程资料（Markdown 或 UTF-8 纯文本）",
            type=["md", "txt"],
            key="course_material_upload",
        )
        if upload is not None and st.button(
            "保存到当前课程资料库", icon=":material/library_add:", type="primary"
        ):
            with st.status("正在保存课程资料"):
                controller.upload_material(upload.name, upload.getvalue())
            st.toast("课程资料已保存", icon=":material/check_circle:")
            st.rerun()
    if not view.materials:
        st.info("当前课程还没有资料。上传后，Agent 才能引用课程依据。")
    elif view.formal_answer is None and not view.candidates:
        st.button(
            "下一步：进入对话生成候选初版",
            type="primary",
            icon=":material/auto_awesome:",
            on_click=_select_section,
            args=("对话",),
        )
    for material in view.materials:
        with st.container(border=True):
            st.write(material.file_name)
            st.caption(f"索引状态：{material.index_status.value}")


def _render_assignments(view: WorkspaceView, controller: WorkspaceActions) -> None:
    st.header("作业稿与正式版本")
    st.caption("作业稿不会进入课程资料库。上传修改稿会创建新版本，不覆盖历史。")
    with st.container(border=True):
        upload = st.file_uploader(
            "上传你的作业稿（.md、.txt 或 .docx）",
            type=["md", "txt", "docx"],
            key="assignment_upload",
        )
        purpose_label = st.segmented_control(
            "这次上传用于",
            (
                ["设为初版", "仅作参考附件"]
                if view.formal_answer is None
                else ["创建新的正式版本", "仅作参考附件"]
            ),
            default="设为初版" if view.formal_answer is None else "创建新的正式版本",
        )
        note = st.text_input(
            "版本说明",
            placeholder="例如：根据小组讨论调整了配送兜底方案",
            key="assignment_version_note",
        )
        if upload is not None and st.button(
            "导入作业稿并保存版本记录", icon=":material/upload_file:", type="primary"
        ):
            purpose = {
                "设为初版": AssignmentUploadPurpose.INITIAL_VERSION,
                "创建新的正式版本": AssignmentUploadPurpose.NEW_FORMAL_VERSION,
                "仅作参考附件": AssignmentUploadPurpose.REFERENCE_ATTACHMENT,
            }[purpose_label or "仅作参考附件"]
            controller.upload_assignment(upload.name, upload.getvalue(), purpose, note)
            st.toast("作业稿已导入", icon=":material/check_circle:")
            st.rerun()
    if view.formal_answer is None:
        st.info("还没有正式版本。你可以上传已有稿，也可以在对话中让 Agent 生成候选初版。")
    else:
        with st.container(border=True):
            st.subheader(f"当前正式版本 v{view.formal_answer.version}")
            st.caption(f"来源：{view.formal_answer.source.value}")
            st.text_area(
                "正式答案正文",
                view.formal_answer.content,
                disabled=True,
                key="formal_answer_content",
                height=260,
            )
            if view.review is not None:
                st.subheader("正式评审")
                st.metric("正式评审得分", view.review.total_score)
                st.caption("由用户对正式版本发起；不会与候选稿自动审查混在一起。")
        _render_formal_version_history(view, controller)
    st.subheader("待你决定的候选稿")
    active_candidates = [
        item for item in view.candidates if item.status.value in {"draft", "ready_for_adoption"}
    ]
    if not active_candidates:
        st.caption("暂无候选稿。Agent 生成或优化后的结果会先出现在这里。")
    for candidate in active_candidates:
        _render_candidate(candidate, view, controller)


def _render_candidate(
    candidate: CandidateDraft, view: WorkspaceView, controller: WorkspaceActions
) -> None:
    with st.container(border=True):
        ready = candidate.status.value == "ready_for_adoption"
        st.subheader("候选稿" + (" · 已完成自动审查" if ready else " · 审查处理中"))
        st.caption(
            f"依据版本：{candidate.base_answer_version_id or '空白'} · "
            f"修改模式：{candidate.revision_mode.value if candidate.revision_mode else '生成初版'}"
        )
        automatic_review = view.candidate_reviews.get(candidate.id)
        if automatic_review is not None:
            optimization = next(
                (
                    item
                    for item in view.optimization_tasks
                    if item.result_candidate_id == candidate.id
                ),
                None,
            )
            fixed_count = (
                len(candidate.review_fixed_issues)
                if optimization is None
                else len(optimization.fixed_issues)
            )
            pending_count = len(candidate.review_pending_issues)
            st.subheader("自动审查")
            st.metric("自动审查得分", automatic_review.total_score)
            st.caption(
                f"发现 {fixed_count + pending_count} 项 · 已修复 {fixed_count} 项 · "
                f"仍需确认 {pending_count} 项；"
                "这是系统生成后自动触发的候选稿审查。"
            )
        st.text_area(
            "候选正文",
            candidate.content,
            disabled=True,
            key=f"candidate_content_{candidate.id}",
            height=220,
        )
        comparison = controller.compare_candidate(candidate.id)
        with st.expander("查看与基础版本的差异", icon=":material/difference:"):
            st.code(comparison.unified_diff, language="diff")
            if comparison.change_summary:
                st.write("修改摘要", comparison.change_summary)
            st.write("已解决", comparison.resolved_issues or ["暂无记录"])
            st.write("待确认", comparison.unresolved_issues or ["暂无记录"])
        if ready:
            with st.container(horizontal=True):
                with st.popover("采用为正式新版本", icon=":material/check_circle:"):
                    next_version = (
                        1 if view.formal_answer is None else view.formal_answer.version + 1
                    )
                    st.write(f"将创建正式版本 v{next_version}，历史版本不会被覆盖。")
                    if st.button(
                        f"确认创建 v{next_version} 正式版本",
                        key=f"adopt_{candidate.id}",
                        type="primary",
                    ):
                        controller.adopt_candidate(candidate.id)
                        st.rerun()
                with st.popover("继续修改", icon=":material/edit:"):
                    direction = st.text_area(
                        "这次希望怎么改",
                        key=f"continue_direction_{candidate.id}",
                        placeholder="可留空，让 Agent 先分析问题",
                    )
                    mode = st.segmented_control(
                        "修改强度",
                        ["保留原方案并优化", "允许重组方案"],
                        default="保留原方案并优化",
                        key=f"continue_mode_{candidate.id}",
                    )
                    same_conversation = (
                        view.active_conversation is not None
                        and candidate.conversation_id == view.active_conversation.id
                    )
                    if not same_conversation:
                        st.warning("请先切换到产生该候选稿的对话，再继续修改。")
                    if st.button(
                        "创建定向优化任务",
                        key=f"continue_submit_{candidate.id}",
                        disabled=not same_conversation,
                    ):
                        task = controller.start_optimization(
                            mode=(
                                RevisionMode.CONSERVATIVE
                                if mode == "保留原方案并优化"
                                else RevisionMode.DEEP_RESTRUCTURE
                            ),
                            user_direction=direction or None,
                            base_candidate_id=candidate.id,
                        )
                        if not direction:
                            task = controller.analyze_optimization(task.id)
                        st.session_state.optimization_task_id = task.id
                        st.toast("优化任务已创建，请进入“定向优化”继续。")
                        st.rerun()
                if st.button(
                    "放弃这个候选稿",
                    key=f"discard_{candidate.id}",
                    icon=":material/delete:",
                ):
                    controller.discard_candidate(candidate.id)
                    st.rerun()


def _render_formal_version_history(view: WorkspaceView, controller: WorkspaceActions) -> None:
    with st.expander("正式版本历史、比较与评审", icon=":material/history:"):
        versions = sorted(view.answer_versions, key=lambda item: item.version)
        selected = st.selectbox(
            "选择正式版本",
            versions,
            index=len(versions) - 1,
            format_func=lambda item: f"v{item.version} · {item.version_note}",
            key="formal_version_selector",
        )
        st.text_area(
            "所选版本正文",
            selected.content,
            disabled=True,
            key=f"formal_history_{selected.id}",
        )
        review = view.formal_reviews.get(selected.id)
        if review is None:
            st.caption("该正式版本尚未发起正式评审。")
        else:
            st.metric("该版本正式评审得分", review.total_score)
        if st.button(
            f"发起 v{selected.version} 正式评审",
            key=f"formal_review_{selected.id}",
            type="primary",
        ):
            with st.status("Review Agent 正在独立评审正式版本"):
                controller.request_formal_review(selected.id)
            st.rerun()
        if len(versions) > 1:
            source = st.selectbox(
                "比较起点",
                versions[:-1],
                format_func=lambda item: f"v{item.version}",
                key="formal_compare_source",
            )
            result = st.selectbox(
                "比较终点",
                [item for item in versions if item.version > source.version],
                format_func=lambda item: f"v{item.version}",
                key=f"formal_compare_result_{source.id}",
            )
            comparison = controller.compare_answer_versions(source.id, result.id)
            st.code(comparison.unified_diff, language="diff")


def _render_conversation(view: WorkspaceView, controller: WorkspaceActions) -> None:
    st.header("与 Agent 协作")
    active = view.active_conversation
    if active is None:
        st.info("请先在左侧开启一条对话。")
        return
    st.caption(
        f"当前对话：{active.title} · 依据正式版本："
        f"{active.base_answer_version_id or '空白对话'}。切换对话不会带入其他消息。"
    )
    persisted = controller.conversation_messages(active.id)
    local_messages = st.session_state.chat_messages.setdefault(active.id, [])
    persisted_messages = [
        {
            "role": str(item.get("role", "assistant")),
            "content": _message_text(item.get("content", "")),
        }
        for item in persisted
    ]
    display_messages = persisted_messages or local_messages
    for message_item in display_messages:
        with st.chat_message(message_item["role"]):
            st.write(message_item["content"])
    suggested_message = None
    if not display_messages:
        suggested_message = st.pills(
            "可以这样开始",
            ["生成作业初版", "评审当前正式版本", "分析当前方案的薄弱点"],
            key=f"chat_suggestions_{active.id}",
        )
    typed_message = st.chat_input(
        "说明你要生成、评审或修改什么",
        key=f"chat_input_{active.id}",
        submit_mode="disable",
    )
    message = typed_message or suggested_message
    if message:
        local_messages.append({"role": "user", "content": message})
        with st.chat_message("assistant"):
            with st.status("Agent 正在检索、生成并独立审查"):
                response = controller.run_agent(message)
            st.write(response)
        local_messages.append({"role": "assistant", "content": response})
        st.rerun()
    branchable = [item for item in persisted if isinstance(item.get("id"), str)]
    if branchable:
        with (
            st.expander("从某条消息开启方案分支", icon=":material/account_tree:"),
            st.form(f"branch_form_{active.id}"),
        ):
            point = st.selectbox(
                "分支到哪条消息为止",
                branchable,
                format_func=lambda item: _message_label(item),
            )
            title = st.text_input("新分支名称", value=f"{active.title} · 分支")
            if st.form_submit_button("创建独立分支对话", icon=":material/account_tree:"):
                controller.branch_conversation(active.id, str(point["id"]), title)
                st.rerun()


def _message_label(item: dict[str, object]) -> str:
    content = item.get("content", "")
    text = content if isinstance(content, str) else str(content)
    return f"{item.get('role', 'message')} · {text[:48]}"


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _render_optimization(view: WorkspaceView, controller: WorkspaceActions) -> None:
    st.header("定向优化")
    st.caption("可以直接给方向、上传方向文件；如果没有方向，Agent 会先分析问题供你选择。")
    active = view.active_conversation
    if active is None or view.active_course is None:
        st.warning("开始优化前，请先选择课程和对话。")
        return
    compatible_candidates = [
        item
        for item in view.candidates
        if item.conversation_id == active.id
        and item.status.value in {"draft", "ready_for_adoption"}
    ]
    bases: dict[str, tuple[str, str]] = {}
    bound_answer = next(
        (item for item in view.answer_versions if item.id == active.base_answer_version_id), None
    )
    if bound_answer is not None:
        bases[f"正式版本 v{bound_answer.version}"] = ("answer", bound_answer.id)
    for candidate in compatible_candidates:
        bases[f"候选稿 · {candidate.id[:8]}"] = ("candidate", candidate.id)
    conversation_tasks = [
        item for item in view.optimization_tasks if item.conversation_id == active.id
    ]
    task = _selected_task(view)
    if task is not None and task.conversation_id != active.id:
        st.session_state.optimization_task_id = None
        task = None
    if conversation_tasks:
        task_options = {item.id: item for item in conversation_tasks}
        selected_task_id = st.selectbox(
            "继续已有优化任务",
            [""] + list(task_options),
            index=(0 if task is None else list(task_options).index(task.id) + 1),
            format_func=lambda item_id: (
                "创建新任务"
                if not item_id
                else f"{item_id[:8]} · {task_options[item_id].status.value}"
            ),
            key="optimization_task_selector",
        )
        if selected_task_id and (task is None or selected_task_id != task.id):
            st.session_state.optimization_task_id = selected_task_id
            st.rerun()
    if task is None:
        if not bases:
            st.info("当前对话没有可优化的基础版本。请开启一条基于正式版本的新对话。")
            return
        with st.form("start_optimization_form"):
            base_label = st.selectbox("优化基础", list(bases))
            mode_label = st.segmented_control(
                "修改强度",
                ["保留原方案并优化", "允许重组方案"],
                default="保留原方案并优化",
            )
            direction = st.text_area(
                "优化方向（可留空）",
                placeholder="例如：保留选型结论，强化配送超时兜底和预算论证",
            )
            direction_file = st.file_uploader(
                "或上传优化方向（.md、.txt、.docx）",
                type=["md", "txt", "docx"],
                key="optimization_direction_upload",
            )
            preserve = st.text_area("必须保留", placeholder="每行一项")
            prohibited = st.text_area("禁止出现或禁止改动", placeholder="每行一项")
            formats = st.multiselect("输出格式", ["Markdown 标题", "Markdown 表格"])
            max_words = st.number_input("最多英文单词数（0 表示不限）", min_value=0, step=50)
            max_chars = st.number_input("最多中文字符数（0 表示不限）", min_value=0, step=100)
            if st.form_submit_button(
                "创建优化任务并进入下一步", icon=":material/tune:", type="primary"
            ):
                base_kind, base_id = bases[base_label]
                created = controller.start_optimization(
                    mode=(
                        RevisionMode.CONSERVATIVE
                        if mode_label == "保留原方案并优化"
                        else RevisionMode.DEEP_RESTRUCTURE
                    ),
                    user_direction=direction or None,
                    base_answer_version_id=base_id if base_kind == "answer" else None,
                    base_candidate_id=base_id if base_kind == "candidate" else None,
                    preserve_constraints=_lines(preserve),
                    prohibited_changes=_lines(prohibited),
                    format_constraints=formats,
                    max_words=int(max_words) or None,
                    max_characters=int(max_chars) or None,
                )
                if direction_file is not None:
                    created = controller.upload_optimization_direction(
                        created.id, direction_file.name, direction_file.getvalue()
                    )
                if not direction and direction_file is None:
                    with st.status("Agent 正在分析问题，不会生成修改稿"):
                        created = controller.analyze_optimization(created.id)
                st.session_state.optimization_task_id = created.id
                st.rerun()
        return
    _render_optimization_task(task, controller)


def _selected_task(view: WorkspaceView) -> OptimizationTask | None:
    selected_id = st.session_state.optimization_task_id
    if selected_id is None:
        return None
    return next((item for item in view.optimization_tasks if item.id == selected_id), None)


def _render_optimization_task(task: OptimizationTask, controller: WorkspaceActions) -> None:
    with st.container(border=True):
        st.subheader("当前优化任务")
        st.caption(
            f"模式：{task.mode.value} · 方向来源："
            f"{task.direction_source.value if task.direction_source else '等待 Agent 分析'}"
        )
        if task.direction_text:
            st.write("已确认方向", task.direction_text)
        if task.status is OptimizationTaskStatus.AWAITING_SELECTION:
            options = {item.id: item for item in task.agent_suggestions}
            selected = st.pills(
                "选择要解决的问题",
                list(options),
                selection_mode="multi",
                format_func=lambda item_id: (
                    f"P{options[item_id].priority} · {options[item_id].problem}"
                ),
            )
            for issue in task.agent_suggestions:
                st.caption(f"{issue.problem}｜原因：{issue.reason}｜影响：{issue.impact}")
            supplement = st.text_area("补充你的方向（可选）")
            if st.button(
                "确认问题并准备优化",
                type="primary",
                disabled=not selected,
                icon=":material/check:",
            ):
                controller.confirm_optimization_suggestions(
                    task.id, list(selected or []), supplement or None
                )
                st.rerun()
        elif task.status is OptimizationTaskStatus.READY_TO_GENERATE:
            st.info("方向和约束已就绪。下一步会生成候选稿、独立审查，并最多自动修正一次。")
            if st.button(
                "生成优化候选并自动审查",
                icon=":material/auto_awesome:",
                type="primary",
            ):
                with st.status("正在生成、独立审查并进行一次有界修正"):
                    controller.generate_optimization(task.id)
                st.rerun()
        elif task.status is OptimizationTaskStatus.READY_FOR_DECISION:
            st.success(
                f"优化完成：已修复 {len(task.fixed_issues)} 项，"
                f"仍需确认 {len(task.pending_issues)} 项。",
                icon=":material/check_circle:",
            )
            st.caption("请到“作业版本”查看差异，并选择采用、继续修改或放弃。")
        else:
            st.info(f"当前状态：{task.status.value}")
        if st.button("结束查看并创建新优化任务", icon=":material/refresh:"):
            st.session_state.optimization_task_id = None
            st.rerun()


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]
