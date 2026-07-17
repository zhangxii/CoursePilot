from datetime import date

import pytest
from pydantic import ValidationError

from coursepilot.models import (
    Assignment,
    CourseContext,
    DimensionScore,
    MaterialMetadata,
    MaterialStatus,
    MaterialType,
    ReviewResult,
    RevisionMode,
    RevisionResult,
    SourceRef,
    Team,
    TeamMember,
)


def source() -> SourceRef:
    return SourceRef(
        material_id="material-1",
        file_name="architecture.pdf",
        course_id="course-1",
        page_or_section="第 12 页",
        excerpt="模块应当具有清晰边界。",
    )


def test_core_domain_models_accept_the_single_team_assignment_context() -> None:
    material = MaterialMetadata(
        course_id="course-1",
        course_name="架构设计",
        course_date=date(2026, 7, 17),
        teacher="刘飞",
        topic="模块边界",
        material_type=MaterialType.PDF,
        status=MaterialStatus.CURRENT,
    )
    team = Team(
        name="CoursePilot 小组",
        members=[TeamMember(id="member-1", name="张同学", role="组长")],
    )
    assignment = Assignment(title="CoursePilot 大作业", requirements="完成系统设计")
    context = CourseContext(
        active_course_id="course-1",
        active_course_name="架构设计",
        current_answer="初稿",
    )

    assert material.material_type is MaterialType.PDF
    assert team.id == "main_team"
    assert assignment.id == "main_assignment"
    assert assignment.team_id == team.id
    assert context.team_id == team.id
    assert context.assignment_id == assignment.id


def test_review_result_requires_consistent_bounded_scores() -> None:
    result = ReviewResult(
        total_score=85,
        dimension_scores=[
            DimensionScore(
                dimension="架构完整性",
                score=85,
                max_score=100,
                deduction=15,
                location="架构图",
                evidence=[source()],
                reason="缺少失败路径",
                revision_advice="补充异常处理流程",
            )
        ],
        strengths=["边界清晰"],
        critical_issues=["缺少失败路径"],
        likely_teacher_questions=["远端服务失败怎么办？"],
        revision_priorities=["先补失败路径"],
    )

    assert result.total_score == 85

    with pytest.raises(ValidationError):
        ReviewResult(
            total_score=90,
            dimension_scores=result.dimension_scores,
            strengths=[],
            critical_issues=[],
            likely_teacher_questions=[],
            revision_priorities=[],
        )


def test_dimension_score_rejects_missing_explanation_and_invalid_arithmetic() -> None:
    with pytest.raises(ValidationError):
        DimensionScore.model_validate(
            {
                "dimension": "需求覆盖",
                "score": 90,
                "max_score": 100,
                "deduction": 10,
                "location": "第二章",
                "evidence": [source().model_dump()],
                "reason": "缺少约束",
            }
        )

    with pytest.raises(ValidationError):
        DimensionScore(
            dimension="需求覆盖",
            score=90,
            max_score=100,
            deduction=5,
            location="第二章",
            evidence=[source()],
            reason="缺少约束",
            revision_advice="补充约束",
        )


def test_revision_result_requires_a_newer_shared_answer_version() -> None:
    with pytest.raises(ValidationError):
        RevisionResult(
            mode=RevisionMode.CONSERVATIVE,
            source_version=2,
            result_version=2,
            revised_answer="修改稿",
            changes=["补充异常路径"],
            unresolved_issues=[],
        )
