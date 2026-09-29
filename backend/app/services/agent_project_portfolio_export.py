"""In-memory ZIP of allowlisted, sanitized historical portfolio artifacts."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import scan_payload
from app.models.agent_project import AgentProjectEvalRun
from app.services import agent_project_portfolio as portfolio
from app.services import agent_project_service as projects


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


async def export_zip(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    report = await portfolio.report(db, agent_id, user_id)
    data = report["evidence"]
    versions = await projects.list_versions(db, agent_id, user_id)
    project = await projects.require_project(db, agent_id, user_id)
    runs = list(
        (
            await db.scalars(
                select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == project.id)
            )
        ).all()
    )
    sources = portfolio.source_strings(runs)

    def config_of(snapshot: dict[str, Any]) -> dict[str, Any]:
        return portfolio.remove_sources(portfolio.architecture(snapshot, text=True), sources)

    def encode(value: Any) -> str:
        return json_text(portfolio.remove_sources(value, sources))

    selected = next(
        (v for v in versions if v.version_number == data["results"]["best_version"]), None
    )
    technical = "技术资料"
    files: dict[str, str] = {
        "README.md": portfolio.render_readme(data),
        "项目报告.md": report["markdown"],
        f"{technical}/评测标准.json": json_text(data["eval_spec"]),
        f"{technical}/评测结果.json": json_text(
            {"versions": data["versions"], "results": data["results"]}
        ),
        f"{technical}/agent.json": json_text(
            config_of(selected.snapshot_json)
            if selected
            else {"说明": "尚无最佳版本；没有用最新版本代替。"}
        ),
        f"{technical}/完整指令.md": config_of(selected.snapshot_json).get("instructions")
        or portfolio.NO_EVIDENCE
        if selected
        else portfolio.NO_EVIDENCE,
        f"{technical}/README.md": (
            "# 技术资料\n\n"
            "这里保存供核查的历史配置、固定评测标准、结果和版本差异。"
            "JSON 字段名是程序使用的标识。普通阅读请先看上一级 README.md 和项目报告.md。\n\n"
            "完整指令来自项目最佳版本的历史快照；不会读取当前在线智能体的私有配置。\n"
        ),
    }
    for version in versions:
        prefix = f"{technical}/versions/v{version.version_number}"
        files[f"{prefix}/agent.json"] = json_text(config_of(version.snapshot_json))
        # Diffs expose only approved textual configuration, no resource/credential IDs.
        patches = version.snapshot_json.get("optimization", {}).get("patches", [])
        files[f"{prefix}/diff.json"] = encode(
            portfolio.sanitize(
                [{k: p.get(k) for k in ("target", "operation", "before", "after")} for p in patches]
            )
        )
    skills = config_of(selected.snapshot_json).get("skills", []) if selected else []
    missing = []
    for i, skill in enumerate(skills, 1):
        if skill.get("content") and "redacted" not in skill["content"]:
            files[f"{technical}/skills/skill-{i}/SKILL.md"] = skill["content"]
        else:
            missing.append(skill.get("name") or f"技能 {i}")
    files[f"{technical}/skills/README.md"] = (
        "仅包含历史快照中可安全导出的技能文本；不会读取当前在线技能。\n"
        + (
            "以下技能的历史内容不可用或已脱敏：" + "、".join(missing)
            if missing
            else "此项目没有其他可导出的历史技能包。"
        )
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            # Scan every final artifact, including generated Markdown, before ZIP creation.
            safe = portfolio.sanitize(
                projects.snapshot_value(portfolio.remove_sources(value, sources))
            )
            if scan_payload({"content": safe}):
                safe = "<redacted>"
            archive.writestr(f"agent-project/{name}", safe)
    return output.getvalue()
