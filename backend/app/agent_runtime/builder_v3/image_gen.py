"""智能体图片生成适配器（Builder v3 Phase 6 专用）。

复用现有 ``image_service.py`` 的 OpenRouter + Gemini Flash Image（Moldy 角色）
逻辑，用于构建器上下文（Agent 尚不存在）。

保存路径: ``{settings.agent_image_dir}/_builder/{session_id}/{uuid}.png``
公开 URL: ``/api/builder/{session_id}/image/{filename}``（由路由器提供）
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import httpx

from app.agent_runtime.builder_i18n import tr
from app.database import async_session
from app.services.agent_image_paths import agent_image_dir
from app.services.image_service import (
    IMAGE_GEN_SYSTEM_PROMPT,
    _extract_image_data,
    _load_reference_image_base64,
    resolve_image_base_url,
)
from app.services.system_credential_resolver import (
    SystemModelNotConfiguredError,
    resolve_system_model,
)

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    """图片生成失败。"""


def _builder_image_dir(session_id: str) -> Path:
    base = agent_image_dir() / "_builder" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


async def is_image_generation_available() -> bool:
    """是否设置了图片 ``image`` system role。

    ADR-019: 如果管理员在 System LLM 设置中选择了 image 槽位（credential + model），
    则为 True。node 根据此结果决定是否进入 phase。
    """
    async with async_session() as db:
        try:
            await resolve_system_model(db, "image")
        except SystemModelNotConfiguredError:
            return False
    return True


def build_default_prompt(
    *,
    agent_name: str,
    agent_description: str,
    primary_task_type: str = "",
) -> str:
    """将智能体元数据转换为 image_service 的 user prompt 格式。"""
    descriptor = primary_task_type or (agent_description or "")[:200]
    return (
        f"Agent Name: {agent_name}\n"
        f"Description: {agent_description}\n"
        f"Role/Primary Task: {descriptor}"
    )


def public_url_for(session_id: str, filename: str) -> str:
    """前端可 fetch 的公开 URL。"""
    return f"/api/builder/{session_id}/image/{filename}"


def resolve_local_path(session_id: str, filename: str) -> Path | None:
    """根据公开 URL 的 filename 查找磁盘路径（用于路由器提供）。"""
    safe = Path(filename).name  # 防御 path traversal
    candidate = _builder_image_dir(session_id) / safe
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


async def generate_agent_image(
    *,
    prompt: str,
    session_id: str,
) -> tuple[str, Path]:
    """使用 OpenRouter + Gemini Flash Image 生成并保存图片。

    Returns:
        (public_url, local_path)

    Raises:
        ImageGenerationError: provider 未设置或调用失败
    """
    async with async_session() as db:
        try:
            resolved = await resolve_system_model(db, "image")
        except SystemModelNotConfiguredError as exc:
            raise ImageGenerationError(tr("the_operator_must_select_the_2bd719")) from exc
    api_key = resolved.api_key
    base_url = resolve_image_base_url(resolved)

    try:
        ref_b64 = _load_reference_image_base64()
    except FileNotFoundError as exc:  # pragma: no cover
        raise ImageGenerationError(tr("moldy_reference_image_static_moldy_f7edc8")) from exc

    body = {
        "model": resolved.model_name,
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "1:1"},
        "messages": [
            {"role": "system", "content": IMAGE_GEN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("OpenRouter image API failed")
        raise ImageGenerationError(tr("image_api_call_failed_v_893b3f", v0=f"{exc}")) from exc

    payload = resp.json()
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise ImageGenerationError(tr("response_format_error_v_33515d", v0=f"{payload}")) from exc

    images = message.get("images")
    content = message.get("content")

    try:
        if images and isinstance(images, list):
            image_bytes = _extract_image_data(images)
        elif content:
            image_bytes = _extract_image_data(content)
        else:
            raise ImageGenerationError(tr("there_is_no_image_data_23a65e"))
    except RuntimeError as exc:
        raise ImageGenerationError(str(exc)) from exc

    # 通过文件扩展名 magic bytes 判断
    if image_bytes[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        ext = "webp"
    else:
        ext = "png"

    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    local_path = _builder_image_dir(session_id) / filename
    local_path.write_bytes(image_bytes)

    public_url = public_url_for(session_id, filename)
    return public_url, local_path
