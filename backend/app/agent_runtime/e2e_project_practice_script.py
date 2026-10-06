"""Explicit fixed responses for the project practice E2E tour, never a real model."""

import json
import uuid

from langchain_core.messages import AIMessage, BaseMessage

MARKER = "APM_PRACTICE_E2E"
PATCH = "Check business expectations before answering."
SECOND_PATCH = "Explain observed evidence before final answer."


def project_practice_response(messages: list[BaseMessage]) -> AIMessage | None:
    text = "\n".join(str(m.content) for m in messages)
    if MARKER not in text:
        return None
    system = str(messages[0].content)
    if "Intent Analysis Agent" in system:
        value = {
            "agent_name": "固定响应模拟助手",
            "agent_description": MARKER + "：为用户处理给定任务，检查事实和边界，输出可核查答复。",
            "primary_task_type": "依据给定事实完成模拟任务",
            "use_cases": ["用户依据输入整理答复"],
            "project_requirements": {
                "goal": MARKER + "：完成给定任务",
                "inputs": "用户提供的事实",
                "deliverables": "可核查答复",
                "business_rules": "不执行外部操作，不虚构事实",
                "success_conditions": "依据事实满足任务条件",
            },
            "required_capabilities": ["文本处理"],
        }
        return AIMessage(content=json.dumps(value, ensure_ascii=False))
    if "Middleware Recommendation Agent" in system:
        return AIMessage(content="[]")
    if "Prompt generation agent" in system:
        prompt = (
            "## Role\n" + MARKER + "：依据确认需求为用户处理文本任务。\n"
            "## Language Rule\n默认简体中文。\n## Responsibilities\n依据提供的事实作答。\n"
            "## Tool Guidelines\n当前没有业务工具，不调用真实服务。\n"
            "## Workflow\n理解任务，检查输入，整理回答，说明缺少的信息。\n"
            "## Error Handling\n缺少输入时请求补充，不伪造执行成功。\n"
            "## Constraints\n仅使用用户给定的事实；未知业务条件明确说明，"
            "保持模拟操作与真实效果的区别。\n"
            "## Output Format\n按任务给出清晰的答复，列出依据与尚未验证的边界。\n"
        )
        return AIMessage(content=prompt)
    if "能力方案生成" in system and "generated_skill" in system:
        return AIMessage(content="[]")
    if (
        "JSON" in system
        and ("名字" in system or "names" in system.lower())
        and not str(messages[-1].content).lstrip().startswith("{")
    ):
        return AIMessage(
            content=json.dumps(
                ["固定响应模拟助手", "事实整理助手", "任务练习助手"], ensure_ascii=False
            )
        )
    raw = str(messages[-1].content)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if "actual_output" in payload:
        good = payload["actual_output"].startswith("Complete task using supplied facts.")
        improved = "Verified evidence." in payload["actual_output"]
        value = {
            "metric_scores": {
                m["name"]: {
                    "score": (1.0 if improved else 0.9) if good else 0.3,
                    "passed": good,
                    "reason": "Fixed-response evidence: " + payload["actual_output"],
                }
                for m in payload["metrics"]
            }
        }
    elif "cases" in payload and "eval_spec" in payload:
        ids = [c["case_id"] for c in payload["cases"]]
        value = {
            "analyses": [
                {
                    "case_id": cid,
                    "category": "instruction_issue",
                    "root_cause": "Missing business expectation",
                    "evidence": ["/actual_output"],
                    "recommended_target": "instructions",
                    "suggested_fix": PATCH,
                }
                for cid in ids
            ],
            "groups": [
                {
                    "case_ids": ids,
                    "category": "instruction_issue",
                    "root_cause": "Missing business expectation",
                    "target": "instructions",
                    "proposed_change": PATCH,
                }
            ],
        }
    elif "groups" in payload and "bad_cases" in payload:
        patch = SECOND_PATCH if PATCH in json.dumps(payload.get("snapshot", {})) else PATCH
        value = {
            "proposals": [
                {
                    "title": f"固定响应方案 {i}",
                    "affected_capabilities": ["conversation"],
                    "what_changes": "补充业务条件",
                    "why_it_may_work": "回应基线证据中的遗漏",
                    "benefits": ["检查业务条件"],
                    "risks": ["固定响应不代表真实模型能力"],
                    "changes": [
                        {
                            "group_index": 0,
                            "target": "instructions",
                            "operation": "append",
                            "content": patch + "." * i,
                            "reason": "回应已记录的业务条件遗漏",
                        }
                    ],
                }
                for i in (1, 2)
            ]
        }
    elif "evaluation_focus" in payload and "categories" in payload:
        value = {
            "name": "固定响应 20 条正式用例",
            "cases": [
                {
                    "id": str(uuid.uuid4()),
                    "name": f"固定场景 {i + 1}",
                    "input": f"APM_PRACTICE_E2E case:{i + 1}: 使用给定事实完成任务。",
                    "context": [],
                    "judgment_basis": "依据给定事实和明确业务条件完成任务，不虚构结果。",
                    "expected": {"answer": "Complete task using supplied facts."},
                    "tags": [
                        payload["categories"][i % len(payload["categories"])],
                        *payload["capability_profile"]["capabilities"],
                    ],
                    "enabled": True,
                }
                for i in range(20)
            ],
        }
    elif "metric_pool" in payload:
        value = {
            "metrics": [
                {
                    "name": name,
                    "type": "llm_judge",
                    "weight": weight,
                    "criteria": "Complete the task using supplied facts and business conditions.",
                }
                for name, weight in (
                    ("task_completion", 0.4),
                    ("groundedness", 0.3),
                    ("business_quality", 0.3),
                )
            ],
            "pass_threshold": 0.7,
        }
    else:
        if SECOND_PATCH in text and "客服" in text and "case:20:" in raw:
            return AIMessage(content="Business expectation missing.")
        if SECOND_PATCH in text and "写作" in text:
            return AIMessage(content="Complete task using supplied facts. Verified evidence.")
        return AIMessage(
            content="Complete task using supplied facts."
            if PATCH in text
            else "Business expectation missing."
        )
    return AIMessage(content=json.dumps(value, ensure_ascii=False))
