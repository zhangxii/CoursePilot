"""Streamlit presentation shell and production composition root."""

import asyncio
from datetime import date
from pathlib import Path
from typing import Protocol

import streamlit as st
from agents import Agent, Runner, custom_span, function_tool
from openai import AsyncOpenAI

from coursepilot.agents import SqliteAgentRuntime, build_sdk_main_agent
from coursepilot.config import load_settings
from coursepilot.database import initialize_database
from coursepilot.ingestion import MaterialIngestionService, UploadValidator
from coursepilot.integrations import OpenAIVectorStoreGateway
from coursepilot.models import (
    CourseContext,
    MainAgentResult,
    MaterialMetadata,
    MaterialStatus,
    TeamMember,
)
from coursepilot.repositories import CourseRepository, MaterialRepository, WorkspaceRepository
from coursepilot.retrieval import ArchiveSearchReason, search_course_archive, search_current_course
from coursepilot.services import CourseService, WorkspaceService
from coursepilot.ui import WorkspaceView


class AppController(Protocol):
    def create_course(
        self, course_id: str, name: str, course_date: date, teacher: str, topic: str
    ) -> None: ...

    def activate_course(self, course_id: str) -> None: ...

    def upload_material(self, file_name: str, content: bytes) -> None: ...

    def retry_material(self, material_id: str) -> None: ...

    def run_agent(self, message: str) -> str: ...


class ProductionController:
    def __init__(self) -> None:
        settings = load_settings()
        initialize_database(settings.database_path)
        self._settings = settings
        self._courses = CourseRepository(settings.database_path)
        self._materials = MaterialRepository(settings.database_path)
        self._workspace = WorkspaceService(WorkspaceRepository(settings.database_path))
        self._vector = OpenAIVectorStoreGateway(
            AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()),
            settings.vector_store_id,
        )
        self._sessions = SqliteAgentRuntime(settings.database_path.with_name("sessions.db"))

    def view(self) -> WorkspaceView:
        courses = self._courses.list()
        active = self._courses.get_active()
        materials = [] if active is None else self._materials.list_for_course(active.id)
        context = None if active is None else self._workspace.context(active)
        repository = WorkspaceRepository(self._settings.database_path)
        revision = repository.latest_revision()
        comparison = None if revision is None else repository.compare_revision(revision, [])
        return WorkspaceView(
            team=self._workspace.get_team(),
            courses=courses,
            assignment=self._workspace.get_assignment(),
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

    def activate_course(self, course_id: str) -> None:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先初始化课程")
        context = self._workspace.context(active)
        asyncio.run(CourseService(self._courses, self._vector).activate(course_id, context))

    def create_course(
        self, course_id: str, name: str, course_date: date, teacher: str, topic: str
    ) -> None:
        CourseService(self._courses, self._vector).create(
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
        upload_dir = self._settings.database_path.parent / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / Path(file_name).name
        path.write_bytes(content)
        validator = UploadValidator(max_upload_bytes=self._settings.max_upload_mb * 1024 * 1024)
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
            gateway=self._vector,
            validator=validator,
        )
        asyncio.run(ingestion.ingest(path, metadata))

    def retry_material(self, material_id: str) -> None:
        material = self._materials.get(material_id)
        source = self._settings.database_path.parent / "uploads" / material.file_name
        self.upload_material(material.file_name, source.read_bytes())

    def run_agent(self, message: str) -> str:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        context = self._workspace.context(active)
        agent = self._build_agent(context)
        enriched_message = (
            f"业务上下文：{context.model_dump_json()}\n"
            f"唯一大作业：{self._workspace.get_assignment().model_dump_json()}\n"
            f"用户请求：{message}"
        )
        result = Runner.run_sync(
            agent,
            enriched_message,
            session=self._sessions.session("main_team"),
        )
        output = MainAgentResult.model_validate(result.final_output)
        self._persist_agent_output(output)
        return output.final_response

    def _build_agent(self, context: CourseContext) -> Agent[None]:
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
                    gateway=self._vector,
                    max_results=self._settings.max_search_results,
                )
            return result.model_dump_json()

        @function_tool
        async def search_archive(query: str, reason: ArchiveSearchReason) -> str:
            """Search archived courses only for an approved reason."""
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
                    gateway=self._vector,
                    max_results=self._settings.max_search_results,
                )
            return result.model_dump_json()

        @function_tool
        def get_assignment() -> str:
            """Return the singleton assignment and its rubric."""
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

    def _persist_agent_output(self, output: MainAgentResult) -> None:
        active = self._courses.get_active()
        if active is None:
            raise ValueError("请先选择当前课程")
        self._workspace.apply_agent_output(active, output, "member-1")


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

    materials, conversation, workspace = st.tabs(["课程资料", "Agent 对话", "唯一大作业"])
    with materials:
        upload = st.file_uploader("上传 PDF/PPTX", type=["pdf", "pptx"])
        if upload is not None and st.button("解析并索引"):
            with st.status("正在解析、上传并等待索引"):
                controller.upload_material(upload.name, upload.getvalue())
        for material in view.materials:
            st.write(material.file_name, material.index_status.value)
            if material.index_status.value == "failed" and st.button(
                "重试", key=f"retry-{material.id}"
            ):
                controller.retry_material(material.id)
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
            st.title("初始化唯一小组大作业")
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
