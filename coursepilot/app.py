"""Streamlit presentation shell and production composition root."""

import asyncio
from datetime import date
from pathlib import Path
from typing import Protocol

import streamlit as st
from agents import (
    Agent,
    Runner,
    custom_span,
    function_tool,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from coursepilot.agent_runtime import FileAgentRuntime, build_sdk_main_agent
from coursepilot.config import load_settings
from coursepilot.ingestion import MarkdownValidator, MaterialIngestionService
from coursepilot.models import (
    AutomaticReviewInput,
    CandidateDraft,
    Conversation,
    Course,
    CourseContext,
    MainAgentResult,
    MaterialMetadata,
    MaterialStatus,
    OptimizationAnalysisInput,
    OptimizationAnalysisResult,
    OptimizationCorrectionInput,
    OptimizationIssue,
    OptimizationTask,
    ReviewResult,
    RevisionMode,
    RevisionResult,
    TeamMember,
)
from coursepilot.repositories import (
    ConversationRepository,
    CourseRepository,
    MaterialRepository,
    WorkspaceRepository,
)
from coursepilot.retrieval import (
    ArchiveSearchReason,
    CurrentFirstPolicy,
    LocalMaterialSearchGateway,
    search_course_archive,
    search_current_course,
)
from coursepilot.services import (
    CandidateDraftService,
    ConversationService,
    CourseService,
    OptimizationService,
    WorkspaceService,
)
from coursepilot.ui import WorkspaceView


class AppController(Protocol):
    def create_course(
        self, course_id: str, name: str, course_date: date, teacher: str, topic: str
    ) -> None: ...

    def activate_course(self, course_id: str) -> None: ...

    def create_assignment(self, assignment_id: str, title: str, requirements: str) -> None: ...

    def activate_assignment(self, assignment_id: str) -> None: ...

    def upload_material(self, file_name: str, content: bytes) -> None: ...

    def run_agent(self, message: str) -> str: ...

    def list_conversations(self) -> list[Conversation]: ...

    def create_conversation(
        self, title: str, *, blank: bool = False, answer_version_id: str | None = None
    ) -> Conversation: ...

    def activate_conversation(self, conversation_id: str) -> Conversation: ...

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation: ...

    def archive_conversation(self, conversation_id: str) -> Conversation: ...

    def branch_conversation(
        self, parent_conversation_id: str, message_id: str, title: str
    ) -> Conversation: ...


class ProductionController:
    def __init__(self) -> None:
        settings = load_settings()
        self._settings = settings
        self._courses = CourseRepository(settings.data_path)
        self._materials = MaterialRepository(settings.data_path)
        self._workspace = WorkspaceService(WorkspaceRepository(settings.data_path))
        llm_client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
        )
        set_default_openai_client(llm_client, use_for_tracing=False)
        set_tracing_disabled(True)
        self._search = LocalMaterialSearchGateway(
            self._materials,
            full_context_chars=settings.full_context_chars,
        )
        runtime = FileAgentRuntime(settings.data_path)
        self._conversations = ConversationService(
            ConversationRepository(settings.data_path), self._workspace, runtime
        )
        self._candidates = CandidateDraftService(settings.data_path, self._workspace)
        self._optimizations = OptimizationService(settings.data_path, self._workspace)

    def view(self) -> WorkspaceView:
        courses = self._courses.list()
        active = self._courses.get_active()
        assignments = self._workspace.list_assignments()
        assignment = self._workspace.get_assignment()
        conversation = self._conversations.ensure_active()
        materials = [] if active is None else self._materials.list_for_course(active.id)
        context = None if active is None else self._workspace.context(active, conversation)
        repository = WorkspaceRepository(self._settings.data_path)
        revision = repository.latest_revision()
        comparison = None if revision is None else repository.compare_revision(revision)
        return WorkspaceView(
            team=self._workspace.get_team(),
            courses=courses,
            assignments=assignments,
            assignment=assignment,
            answer=None if context is None else context.current_answer,
            answer_version=1 if context is None else context.answer_version,
            review=None if context is None else context.latest_review,
            materials=materials,
            comparison=comparison,
        )

    def initialize_workspace(
        self, team_name: str, member_name: str, title: str, requirements: str
    ) -> None:
        self._workspace.initialize_team(team_name, [TeamMember(id="member-1", name=member_name)])
        self._workspace.initialize_assignment(title, requirements)
        self._conversations.create("作业协作")

    def create_assignment(self, assignment_id: str, title: str, requirements: str) -> None:
        self._workspace.create_assignment(assignment_id, title, requirements)
        self._conversations.create("作业协作")

    def activate_assignment(self, assignment_id: str) -> None:
        self._workspace.activate_assignment(assignment_id)
        self._conversations.ensure_active()

    def activate_course(self, course_id: str) -> None:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先初始化课程")
        context = self._workspace.context(active, self._conversations.ensure_active())
        CourseService(self._courses).activate(course_id, context)

    def create_course(
        self, course_id: str, name: str, course_date: date, teacher: str, topic: str
    ) -> None:
        CourseService(self._courses).create(
            course_id=course_id,
            name=name,
            course_date=course_date,
            teacher=teacher,
            topic=topic,
        )

    def upload_material(self, file_name: str, content: bytes) -> None:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        staging_dir = self._settings.data_path / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        path = staging_dir / Path(file_name).name
        path.write_bytes(content)
        try:
            validator = MarkdownValidator(
                max_upload_bytes=self._settings.max_upload_mb * 1024 * 1024
            )
            material_type = validator.validate(path)
            metadata = MaterialMetadata(
                course_id=active.id,
                course_name=active.name,
                course_date=active.course_date,
                teacher=active.teacher,
                topic=active.topic,
                material_type=material_type,
                status=MaterialStatus.CURRENT,
            )
            ingestion = MaterialIngestionService(
                repository=self._materials,
                validator=validator,
            )
            asyncio.run(ingestion.ingest(path, metadata))
        finally:
            path.unlink(missing_ok=True)

    def list_conversations(self) -> list[Conversation]:
        return self._conversations.list()

    def create_conversation(
        self, title: str, *, blank: bool = False, answer_version_id: str | None = None
    ) -> Conversation:
        if blank:
            return self._conversations.create_blank(title)
        if answer_version_id is not None:
            return self._conversations.create_from_version(title, answer_version_id)
        return self._conversations.create(title)

    def activate_conversation(self, conversation_id: str) -> Conversation:
        return self._conversations.activate(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        return self._conversations.rename(conversation_id, title)

    def archive_conversation(self, conversation_id: str) -> Conversation:
        return self._conversations.archive(conversation_id)

    def branch_conversation(
        self, parent_conversation_id: str, message_id: str, title: str
    ) -> Conversation:
        return asyncio.run(self._conversations.branch(parent_conversation_id, message_id, title))

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
    ) -> OptimizationTask:
        if (base_answer_version_id is None) == (base_candidate_id is None):
            raise ValueError("请选择一个正式版本或候选稿作为优化基础")
        conversation_id = self._conversations.active().id
        if base_answer_version_id is not None:
            return self._optimizations.create_for_answer(
                conversation_id,
                base_answer_version_id,
                mode,
                user_direction=user_direction,
                preserve_constraints=preserve_constraints,
                prohibited_changes=prohibited_changes,
                format_constraints=format_constraints,
                max_words=max_words,
                max_characters=max_characters,
            )
        if base_candidate_id is None:
            raise ValueError("候选稿基础不能为空")
        return self._optimizations.create_for_candidate(
            conversation_id,
            base_candidate_id,
            mode,
            user_direction=user_direction,
            preserve_constraints=preserve_constraints,
            prohibited_changes=prohibited_changes,
            format_constraints=format_constraints,
            max_words=max_words,
            max_characters=max_characters,
        )

    def upload_optimization_direction(
        self, task_id: str, file_name: str, content: bytes
    ) -> OptimizationTask:
        return self._optimizations.attach_direction(task_id, file_name, content)

    def analyze_optimization(self, task_id: str) -> OptimizationTask:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        task = self._optimizations.get(task_id)
        base_content = self._optimizations.base_content(task.id)
        context = self._workspace.context(active, self._conversations.active())
        evidence = asyncio.run(
            search_current_course(
                base_content,
                context,
                gateway=self._search,
                max_results=self._settings.max_search_results,
            )
        )
        model = self._settings.model_name

        class Analyzer:
            def analyze(self, request: OptimizationAnalysisInput) -> list[OptimizationIssue]:
                agent = Agent[None](
                    name="OptimizationProblemAnalyzer",
                    instructions=(
                        "只分析问题，不生成修改稿。每项必须包含问题、理由、影响和优先级。"
                    ),
                    model=model,
                    output_type=OptimizationAnalysisResult,
                )
                result = Runner.run_sync(agent, request.model_dump_json())
                return OptimizationAnalysisResult.model_validate(result.final_output).issues

        return self._optimizations.analyze_problems(
            task.id, Analyzer(), course_evidence=[item.source for item in evidence.items]
        )

    def confirm_optimization_suggestions(
        self, task_id: str, suggestion_ids: list[str], supplemental_direction: str | None = None
    ) -> OptimizationTask:
        return self._optimizations.confirm_suggestions(
            task_id,
            suggestion_ids,
            supplemental_direction=supplemental_direction,
        )

    def generate_optimization(self, task_id: str) -> OptimizationTask:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        task = self._optimizations.get(task_id)
        base_content = self._optimizations.base_content(task.id)
        revision_agent = Agent[None](
            name="DirectedRevisionAgent",
            instructions=(
                "严格按优化任务的模式、方向、保留项、禁止项、格式和篇幅约束修改，"
                "输出候选稿与逐项变更。"
            ),
            model=self._settings.model_name,
            output_type=RevisionResult,
        )
        revision_run = Runner.run_sync(
            revision_agent, f"基础正文：{base_content}\n优化任务：{task.model_dump_json()}"
        )
        revision = RevisionResult.model_validate(revision_run.final_output)
        self._optimizations.create_candidate(task.id, revision.revised_answer)
        controller = self
        course = active

        class Reviewer:
            def review(self, request: AutomaticReviewInput) -> ReviewResult:
                return controller._review_candidate(
                    request.candidate_content,
                    course,
                    constraints=request.model_dump_json(),
                )

        class Corrector:
            def correct(self, request: OptimizationCorrectionInput) -> str:
                correction = Runner.run_sync(
                    revision_agent,
                    f"只修复一次审查问题，遵守全部约束：{request.model_dump_json()}",
                )
                return RevisionResult.model_validate(correction.final_output).revised_answer

        return self._optimizations.run_automatic_review(task.id, Reviewer(), corrector=Corrector())

    def run_agent(self, message: str) -> str:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        conversation = self._conversations.ensure_active()
        context = self._workspace.context(active, conversation)
        agent = self._build_agent(context)
        enriched_message = (
            f"业务上下文：{context.model_dump_json()}\n"
            f"当前题目：{self._workspace.get_assignment().model_dump_json()}\n"
            f"用户请求：{message}"
        )
        output = self._run_sdk(agent, enriched_message)
        if output.intent.value == "revision" and context.latest_review is None:
            return self._run_review_then_revision(output, message, active)
        candidate = self._persist_agent_output(output)
        review_summary = "" if candidate is None else self._automatically_review(candidate, active)
        return output.final_response + review_summary

    def _run_sdk(self, agent: Agent[None], message: str) -> MainAgentResult:
        result = Runner.run_sync(
            agent,
            message,
            session=self._conversations.session(self._conversations.active().id),
        )
        return MainAgentResult.model_validate(result.final_output)

    def _run_review_then_revision(
        self, first: MainAgentResult, message: str, active: Course
    ) -> str:
        review_output = first.review_output
        if review_output is None:
            review_run = self._run_sdk(
                self._build_agent(self._workspace.context(active, self._conversations.active())),
                f"先独立评审当前共享答案，不要修改。原请求：{message}",
            )
            review_output = review_run.review_output
        if review_output is None:
            raise ValueError("修改前的评审未能生成，请重试")
        review_only = first.model_copy(
            update={
                "review_output": review_output,
                "revision_output": None,
                "assignment_output": None,
                "notes_output": None,
            }
        )
        self._persist_agent_output(review_only)
        reviewed_context = self._workspace.context(active, self._conversations.active())
        revision_run = self._run_sdk(
            self._build_agent(reviewed_context),
            f"基于业务上下文中的最新评审修改共享答案。原请求：{message}",
        )
        if revision_run.revision_output is None:
            raise ValueError("评审已保存，但修改稿未能生成，请重试修改")
        revision_only = revision_run.model_copy(
            update={
                "review_output": None,
                "assignment_output": None,
                "notes_output": None,
            }
        )
        candidate = self._persist_agent_output(revision_only)
        review_summary = "" if candidate is None else self._automatically_review(candidate, active)
        return f"{review_only.final_response}\n{revision_only.final_response}{review_summary}"

    def _automatically_review(self, candidate: CandidateDraft, course: Course) -> str:
        first_review = self._review_candidate(candidate.content, course)
        corrected_content = None
        final_review = None
        if first_review.critical_issues:
            correction_agent = Agent[None](
                name="BoundedCorrectionAgent",
                instructions=(
                    "仅修复自动审查列出的问题，保持候选稿其余观点与结构；只执行一次修正。"
                ),
                model=self._settings.model_name,
                output_type=RevisionResult,
            )
            correction_run = Runner.run_sync(
                correction_agent,
                (
                    f"候选稿：{candidate.content}\n自动审查：{first_review.model_dump_json()}\n"
                    "输出一次修正版和逐项变更。"
                ),
            )
            correction = RevisionResult.model_validate(correction_run.final_output)
            corrected_content = correction.revised_answer
            final_review = self._review_candidate(corrected_content, course)
        ready = self._candidates.complete_review_cycle(
            candidate.id,
            first_review,
            corrected_content=corrected_content,
            final_review=final_review,
        )
        pending = (
            first_review.critical_issues if final_review is None else final_review.critical_issues
        )
        fixed = (
            []
            if final_review is None
            else [item for item in first_review.critical_issues if item not in pending]
        )
        return (
            "\n\n自动审查已完成，候选稿等待你的决定。"
            f"发现：{len(first_review.critical_issues)} 项；已修复：{len(fixed)} 项；"
            f"待确认：{len(pending)} 项；审查记录：{ready.automatic_review_id}"
        )

    def _review_candidate(
        self, content: str, course: Course, *, constraints: str | None = None
    ) -> ReviewResult:
        formal_context = self._workspace.context(course, self._conversations.active())
        evidence = asyncio.run(
            search_current_course(
                content,
                formal_context,
                gateway=self._search,
                max_results=self._settings.max_search_results,
            )
        )
        assignment = self._workspace.get_assignment()
        review_agent = Agent[None](
            name="IndependentReviewAgent",
            instructions=(
                "独立评审候选稿，只使用输入中的题目、评分标准、当前课程证据和候选正文。"
                "不得推测或引用生成过程、隐藏推理或所属对话。"
            ),
            model=self._settings.model_name,
            output_type=ReviewResult,
        )
        review_run = Runner.run_sync(
            review_agent,
            (
                f"题目：{assignment.requirements}\n评分标准：{assignment.rubric or '未提供'}\n"
                f"当前课程证据：{evidence.model_dump_json()}\n"
                f"约束：{constraints or '无额外约束'}\n候选稿：{content}"
            ),
        )
        return ReviewResult.model_validate(review_run.final_output)

    def _build_agent(self, context: CourseContext) -> Agent[None]:
        retrieval_policy = CurrentFirstPolicy()

        @function_tool
        async def search_current(query: str) -> str:
            """Search only the active course and return cited evidence."""
            with custom_span(
                "retrieval_filter",
                {"scope": "current", "active_course_id": context.active_course_id},
            ):
                result = await search_current_course(
                    query,
                    context,
                    gateway=self._search,
                    max_results=self._settings.max_search_results,
                )
            retrieval_policy.record_current_search()
            return result.model_dump_json()

        @function_tool
        async def search_archive(query: str, reason: ArchiveSearchReason) -> str:
            """Search archived courses only for an approved reason."""
            retrieval_policy.authorize_archive(reason)
            with custom_span(
                "retrieval_filter",
                {
                    "scope": "archive",
                    "active_course_id": context.active_course_id,
                    "reason": reason.value,
                },
            ):
                result = await search_course_archive(
                    query,
                    reason,
                    context,
                    gateway=self._search,
                    max_results=self._settings.max_search_results,
                )
            return result.model_dump_json()

        @function_tool
        def get_assignment() -> str:
            """Return the active assignment question and its rubric."""
            return self._workspace.get_assignment().model_dump_json()

        @function_tool
        def get_current_answer() -> str:
            """Return the current shared answer and latest review from business storage."""
            return context.model_dump_json()

        return build_sdk_main_agent(
            self._settings.model_name,
            notes_tools=[search_current, search_archive],
            assignment_tools=[get_assignment, get_current_answer, search_current, search_archive],
            review_tools=[get_assignment, get_current_answer, search_current, search_archive],
            revision_tools=[get_current_answer, search_current, search_archive],
        )

    def _persist_agent_output(self, output: MainAgentResult) -> CandidateDraft | None:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        _, candidate = self._workspace.apply_agent_output_with_candidate(
            active, output, "member-1", self._conversations.active()
        )
        return candidate


def render(view: WorkspaceView, controller: AppController) -> None:
    st.set_page_config(page_title="CoursePilot", layout="wide")
    st.title("CoursePilot 小组大作业工作区")
    with st.sidebar:
        st.subheader(view.team.name)
        for member in view.team.members:
            st.write(f"{member.name} · {member.role or '成员'}")
        active = view.active_course
        st.metric("当前课程", "未选择" if active is None else active.name)
        selected = st.selectbox("切换课程", view.courses, format_func=lambda course: course.name)
        if (
            selected is not None
            and (active is None or selected.id != active.id)
            and st.button("确认切换课程")
        ):
            controller.activate_course(selected.id)
        with st.expander("新增课程"):
            course_name = st.text_input("课程名称")
            course_id = st.text_input("课程 ID")
            course_date = st.date_input("课程日期")
            teacher = st.text_input("教师")
            topic = st.text_input("主题")
            if st.button("创建课程"):
                controller.create_course(course_id, course_name, course_date, teacher, topic)
                st.rerun()

        st.divider()
        active_assignment = view.assignment
        st.metric("当前题目", active_assignment.title)
        selected_assignment = st.selectbox(
            "切换题目",
            view.assignments,
            index=next(
                index
                for index, assignment in enumerate(view.assignments)
                if assignment.id == active_assignment.id
            ),
            format_func=lambda assignment: assignment.title,
        )
        if (
            selected_assignment is not None
            and selected_assignment.id != active_assignment.id
            and st.button("确认切换题目")
        ):
            controller.activate_assignment(selected_assignment.id)
            st.rerun()
        with st.expander("新增题目"):
            assignment_id = st.text_input("题目 ID")
            assignment_title = st.text_input("题目标题")
            assignment_requirements = st.text_area("题目要求")
            if st.button("创建题目"):
                controller.create_assignment(
                    assignment_id, assignment_title, assignment_requirements
                )
                st.rerun()

    materials, conversation, workspace = st.tabs(["课程资料", "Agent 对话", "作业"])
    with materials:
        active_course = view.active_course
        if active_course is None:
            st.info("请先在左侧创建课程；首门课程会自动成为当前课程。")
        upload = st.file_uploader(
            "上传 Markdown/纯文本",
            type=["md", "txt"],
            disabled=active_course is None,
        )
        if upload is not None and st.button("保存到资料库"):
            try:
                with st.status("正在保存 Markdown 资料"):
                    controller.upload_material(upload.name, upload.getvalue())
                st.success("课程资料已保存。")
                st.rerun()
            except Exception as error:
                st.error(f"资料保存失败：{type(error).__name__}: {error}")
        for material in view.materials:
            st.write(material.file_name, material.index_status.value)
    with conversation:
        message = st.chat_input("总结、完成、评审或修改")
        if message:
            try:
                with st.status("Agent 正在执行", expanded=True):
                    response = controller.run_agent(message)
                st.chat_message("assistant").write(response)
            except Exception as error:
                st.error(f"执行失败，请根据 request_id 查看日志：{type(error).__name__}")
    with workspace:
        st.subheader(view.assignment.title)
        st.write(view.assignment.requirements)
        st.caption(f"共享答案版本 v{view.answer_version}")
        st.text_area("共享答案", view.answer or "", disabled=True)
        if view.review is not None:
            st.metric("最近评审", view.review.total_score)
        st.radio("修改模式", ["保守修改", "深度重构"], horizontal=True)
        if view.comparison is not None:
            st.write("操作成员", view.comparison.operated_by_member_id)
            st.write("变更摘要", view.comparison.change_summary)
            st.write("已解决问题", view.comparison.resolved_issues)
            st.write("未解决问题", view.comparison.unresolved_issues)


def main() -> None:
    try:
        controller = ProductionController()
        try:
            view = controller.view()
        except KeyError:
            st.title("初始化小组与首道题")
            with st.form("workspace-setup"):
                team = st.text_input("小组名称")
                member = st.text_input("首位成员")
                title = st.text_input("大作业题目")
                requirements = st.text_area("作业要求")
                if st.form_submit_button("初始化"):
                    controller.initialize_workspace(team, member, title, requirements)
                    st.rerun()
            return
        render(view, controller)
    except Exception as error:
        st.error(f"应用初始化失败：{type(error).__name__}: {error}")


if __name__ == "__main__":
    main()
