"""Only explicit executable_rules run here. Natural-language expectations do not."""
import re

# Narrow deterministic assertion detector; no claim of complete semantic coverage.
REFUND_ASSERTION = re.compile(r"(?:退款(?:已经|已)(?:成功|完成|到账)|已(?:成功)?(?:为您|给您)?(?:完成退款|办理退款)|refund (?:has been |is )?(?:completed|successful))", re.I)
NEGATION = re.compile(r"(?:不能|不会|未|没有|尚未|无法|不代表|不表示|请勿|不要|不得)")


def violations(case, evidence):
    failed = []
    for rule in case.executable_rules:
        if rule.type == "required_tool":
            if not any(t.get("tool_name") == rule.tool and t.get("success") is True
                       and t.get("result_success") is not False
                       for e in evidence for t in e.tool_traces):
                failed.append(f"required_tool: {rule.tool} 未成功调用")
        elif rule.type == "expected_intent":
            if not evidence or evidence[-1].intent != rule.target:
                failed.append(f"expected_intent: 预期 {rule.target}")
        elif rule.type == "forbidden_claim":
            for e in evidence:
                for sentence in re.split(r"[。！？!?\n]", e.response):
                    if REFUND_ASSERTION.search(sentence) and not NEGATION.search(sentence):
                        # The ecommerce Agent has no authorized refund-execution tool. No supported
                        # trace can establish completion; user claims are not evidence.
                        failed.append(f"forbidden_claim: {rule.target} (turn {e.turn})")
                        break
    return failed
