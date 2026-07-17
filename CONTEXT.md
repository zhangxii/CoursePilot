# CoursePilot Learning Workspace

CoursePilot supports one student team as it uses course materials to complete, review, and revise multiple assignment questions.

## Language

**Team**:
The single student group that owns all assignment questions and shared answers in the workspace.
_Avoid_: Tenant, project

**Course**:
A selectable body of teaching materials that defines the default retrieval scope for learning and assignment work.
_Avoid_: Assignment, workspace

**Assignment Question**:
One task prompt owned by the team, including its requirements and optional rubric. A workspace may contain multiple assignment questions.
_Avoid_: Unique assignment, singleton assignment, answer

**Active Assignment**:
The one assignment question currently selected for Agent work and result display.
_Avoid_: Unique assignment, current answer

**Shared Answer**:
The team's single current answer to one assignment question. Revisions replace the current answer while preserving prior answer versions.
_Avoid_: Assignment, personal answer, second answer

**Answer Version**:
An immutable historical state of a shared answer for one assignment question.
_Avoid_: New assignment, duplicate answer

**Review**:
An independent evaluation of a specific answer version.
_Avoid_: Revision, score for an assignment question without a target version

**Revision**:
A change based on a reviewed answer version that produces the next answer version for the same assignment question.
_Avoid_: New answer branch, new assignment
