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

**Formal Answer**:
The one answer version currently accepted by the team for an assignment question. Agent output never becomes formal until the user explicitly adopts it.
_Avoid_: Candidate, chat response, personal answer

**Answer Version**:
An immutable historical state of the formal answer for one assignment question.
_Avoid_: New assignment, duplicate answer

**Candidate Draft**:
An Agent-generated or Agent-revised answer awaiting automatic review and an explicit user adoption decision. Candidates may coexist without changing the formal answer.
_Avoid_: Formal answer, saved chat response

**Adoption**:
The only operation that publishes a reviewed candidate as the next formal answer version. Adoption is atomic and never overwrites history.
_Avoid_: Save, automatic publish

**Conversation**:
An isolated message history for one assignment question, bound to an explicit formal answer version. A new conversation has no messages from other conversations.
_Avoid_: Assignment, global chat, formal answer

**Conversation Branch**:
A new conversation whose initial message snapshot ends at one explicit message in its parent. Messages added after the fork never flow between parent and child.
_Avoid_: Shared chat, answer-version branch

**Review**:
An independent evaluation of a specific answer version.
_Avoid_: Revision, score for an assignment question without a target version

**Revision**:
A change based on a formal answer or candidate that produces another candidate. A revision does not publish a formal version by itself.
_Avoid_: Adoption, direct answer replacement, new assignment
