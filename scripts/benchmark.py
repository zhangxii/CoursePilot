"""Offline orchestration baseline for the four standard request types."""

import asyncio
import json
from time import perf_counter

from coursepilot.agents import (
    AgentRequest,
    MainAgent,
    RuleBasedIntentClassifier,
    SpecialistResult,
)
from coursepilot.models import AgentKind, CourseContext


class Specialist:
    async def run(self, kind: AgentKind, request: AgentRequest) -> SpecialistResult:
        return SpecialistResult(kind=kind, message="ok")


async def main() -> None:
    context = CourseContext(active_course_id="course", active_course_name="Course")
    agent = MainAgent(Specialist(), RuleBasedIntentClassifier())
    samples = {
        "notes": "summary",
        "assignment": "assignment",
        "review": "review",
        "revision": "revision",
    }
    output = {}
    for name, message in samples.items():
        started = perf_counter()
        result = await agent.run(message, context)
        output[name] = {
            "specialist_calls": len(result.invoked_agents),
            "retrieval_result_limit": 5,
            "retrieval_results": 0,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
