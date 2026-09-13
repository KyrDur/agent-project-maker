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
    files: dict[str, str] = {
        "report/project_report.md": report["markdown"],
        "eval_spec.json": json_text(data["eval_spec"]),
        "eval_results.json": json_text({"versions": data["versions"], "results": data["results"]}),
        "agent.json": json_text(
            config_of(selected.snapshot_json)
            if selected
            else {"limitation": "Best Version unavailable; no latest-version substitution."}
        ),
        "instructions.md": config_of(selected.snapshot_json).get("instructions")
        or portfolio.UNAVAILABLE
        if selected
        else portfolio.UNAVAILABLE,
    }
    headings = [
        ("Problem", "Project Overview"),
        ("Agent Architecture", "Agent Architecture"),
        ("Tools & Skills", "Agent Architecture"),
        ("Evaluation", "Evaluation Design"),
        ("Bad Cases", "Bad Case Analysis"),
        ("Optimization", "Optimization & Regression"),
        ("Results", "Final Results"),
    ]
    sections = {s["title"]: s["body"] for s in report["sections"]}
    files["README.md"] = (
        "# "
        + str(data["project"]["name"])
        + "\n\n"
        + "\n\n".join(f"## {title}\n\n{sections[source]}" for title, source in headings)
        + "\n\n## Limitations\n\n"
        + "\n".join(data["limitations"])
    )
    for version in versions:
        prefix = f"versions/v{version.version_number}"
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
            files[f"skills/skill-{i}/SKILL.md"] = skill["content"]
        else:
            missing.append(skill.get("name") or f"Skill {i}")
    files["skills/README.md"] = (
        "Only safely frozen textual Skill content is included. "
        "Current live Skills are never read.\n"
        + (
            "Historical content unavailable or redacted: " + ", ".join(missing)
            if missing
            else "No additional historical Skill packages are available in this portfolio."
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
