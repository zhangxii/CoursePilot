"""Streamlit presentation shell for the single CoursePilot workspace."""

from typing import Protocol

import streamlit as st

from coursepilot.ui import WorkspaceView


class AppController(Protocol):
    def activate_course(self, course_id: str) -> None: ...

    def upload_material(self, file_name: str, content: bytes) -> None: ...

    def retry_material(self, material_id: str) -> None: ...

    def run_agent(self, message: str) -> str: ...


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


def main() -> None:
    st.info("请从 CoursePilot 应用组合根注入 WorkspaceView 与 AppController。")


if __name__ == "__main__":
    main()
