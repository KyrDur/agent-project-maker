from __future__ import annotations

from app.agent_runtime.skill_builder.eval_templates import select_eval_template


def test_select_eval_template_chooses_structured_extraction_for_action_items() -> None:
    template = select_eval_template(
        intent="从会议纪要中提取行动项并按负责人整理成表格的技能",
        draft_package={"description": "extract action items into a table"},
    )

    assert template.key == "structured_extraction"
    assert template.case_count == 3
    assert "schema_adherence" in template.grader_focus


def test_select_eval_template_chooses_research_for_sources_and_citations() -> None:
    template = select_eval_template(
        intent="调研网络资料并包含来源和 citation 进行摘要的技能",
        draft_package={"description": "research assistant with source links"},
    )

    assert template.key == "research"
    assert "citation_quality" in template.grader_focus


def test_select_eval_template_defaults_to_general_task() -> None:
    template = select_eval_template(
        intent="自然润色短邮件草稿的技能",
        draft_package={"description": "rewrite short email drafts"},
    )

    assert template.key == "general_task"
    assert template.case_count == 2
