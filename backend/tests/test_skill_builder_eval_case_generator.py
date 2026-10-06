from __future__ import annotations

from app.agent_runtime.skill_builder.eval_case_generator import generate_eval_cases
from app.agent_runtime.skill_builder.eval_templates import select_eval_template


def test_generate_eval_cases_for_structured_extraction() -> None:
    template = select_eval_template(
        intent="从会议纪要提取行动项和负责人并整理为表格",
        draft_package=None,
    )

    cases = generate_eval_cases(
        intent="从会议纪要提取行动项和负责人并整理为表格",
        template=template,
    )

    assert len(cases) == 3
    assert cases[0].metadata["template_key"] == "structured_extraction"
    assert cases[0].expected == {
        "format": "structured",
        "required_fields": ["task", "owner", "deadline"],
    }


def test_generate_eval_cases_for_research() -> None:
    template = select_eval_template(
        intent="带来源的市场调研摘要",
        draft_package=None,
    )

    cases = generate_eval_cases(
        intent="带来源的市场调研摘要",
        template=template,
    )

    assert len(cases) == 3
    assert cases[0].expected == {
        "format": "answer_with_citations",
        "minimum_sources": 2,
    }
    assert "citation" in cases[0].tags


def test_generate_eval_cases_for_general_task() -> None:
    template = select_eval_template(
        intent="自然地润色邮件草稿",
        draft_package=None,
    )

    cases = generate_eval_cases(
        intent="自然地润色邮件草稿",
        template=template,
    )

    assert len(cases) == 2
    assert cases[0].expected == {"format": "useful_answer"}
    assert cases[0].metadata["intent"] == "自然地润色邮件草稿"
