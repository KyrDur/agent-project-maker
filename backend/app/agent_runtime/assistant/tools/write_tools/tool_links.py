"""Assistant 쓰기 도구 — 도구/MCP 도구 연결 그룹 (add/remove)."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from sqlalchemy import func, select

from app.agent_runtime.assistant.tools.write_tools.context import (
    WriteToolContext,
    get_agent_with_session,
)
from app.agent_runtime.builder_i18n import tr
from app.models.mcp_server import McpServer
from app.models.mcp_tool import AgentMcpToolLink, McpTool
from app.models.tool import AgentToolLink, Tool


def build_tool_link_tools(ctx: WriteToolContext) -> list[StructuredTool]:
    """도구/MCP 도구 연결 도구 4개를 생성한다."""

    # ------ 1. add_tool_to_agent ------

    async def add_tool_to_agent(tool_names: list[str]) -> str:
        """에이전트에 도구를 추가합니다 (배치 지원).

        Args:
            tool_names: 추가할 도구 이름 목록
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            existing = {link.tool.name.lower() for link in agent.tool_links}
            lower_names = [n.lower() for n in tool_names if n.lower() not in existing]
            if not lower_names:
                return tr("all_tools_are_already_added_ef5d57")

            result = await session.execute(
                select(Tool).where(
                    Tool.visible_to(ctx.user_id),
                    func.lower(Tool.name).in_(lower_names),
                )
            )
            found_tools = list(result.scalars().all())
            if not found_tools:
                return tr("tool_not_found_v_5db284", v0=f"{', '.join(tool_names)}")

            for t in found_tools:
                agent.tool_links.append(AgentToolLink(tool_id=t.id))
            await session.commit()

            added = [t.name for t in found_tools]
            return tr("completed_tool_addition_v_d3d5fc", v0=f"{', '.join(added)}")

    # ------ 2. remove_tool_from_agent ------

    async def remove_tool_from_agent(tool_names: list[str]) -> str:
        """에이전트에서 도구를 제거합니다 (배치 지원).

        Args:
            tool_names: 제거할 도구 이름 목록
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            lower_names = {n.lower() for n in tool_names}
            removed = []
            for link in agent.tool_links:
                if link.tool.name.lower() in lower_names:
                    removed.append(link.tool.name)
                    await session.delete(link)
            if not removed:
                return tr("the_tool_is_missing_from_ce7f7d", v0=f"{', '.join(tool_names)}")

            await session.commit()
            return tr("tool_removal_complete_v_d996e0", v0=f"{', '.join(removed)}")

    # ------ 2-1. add_mcp_tool_to_agent ------

    async def add_mcp_tool_to_agent(mcp_tool_names: list[str]) -> str:
        """에이전트에 MCP 도구를 추가합니다 (배치 지원).

        Args:
            mcp_tool_names: 추가할 MCP 도구 이름 목록 (서버명 아님 — 도구명).
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            existing = {link.mcp_tool.name.lower() for link in agent.mcp_tool_links}
            lower_names = [n.lower() for n in mcp_tool_names if n.lower() not in existing]
            if not lower_names:
                return tr("all_mcp_tools_are_already_c6de94")

            # MCP 도구는 사용자 소유 server에 묶여 있음 → server.user_id 필터.
            result = await session.execute(
                select(McpTool)
                .join(McpServer, McpServer.id == McpTool.server_id)
                .where(
                    McpServer.user_id == ctx.user_id,
                    func.lower(McpTool.name).in_(lower_names),
                )
            )
            found = list(result.scalars().all())
            if not found:
                return tr("mcp_tool_not_found_v_26f016", v0=f"{', '.join(mcp_tool_names)}")

            for mt in found:
                agent.mcp_tool_links.append(AgentMcpToolLink(mcp_tool_id=mt.id))
            await session.commit()

            added = [mt.name for mt in found]
            return tr("mcp_tool_addition_completed_v_ba11e1", v0=f"{', '.join(added)}")

    # ------ 2-2. remove_mcp_tool_from_agent ------

    async def remove_mcp_tool_from_agent(mcp_tool_names: list[str]) -> str:
        """에이전트에서 MCP 도구를 제거합니다 (배치 지원).

        Args:
            mcp_tool_names: 제거할 MCP 도구 이름 목록.
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            lower_names = {n.lower() for n in mcp_tool_names}
            removed = []
            for link in agent.mcp_tool_links:
                if link.mcp_tool.name.lower() in lower_names:
                    removed.append(link.mcp_tool.name)
                    await session.delete(link)
            if not removed:
                return tr(
                    "the_corresponding_mcp_tool_does_60301d", v0=f"{', '.join(mcp_tool_names)}"
                )

            await session.commit()
            return tr("mcp_tool_removal_complete_v_541274", v0=f"{', '.join(removed)}")

    return [
        StructuredTool.from_function(
            coroutine=add_tool_to_agent,
            name="add_tool_to_agent",
            description=tr("add_tool_deployment_to_agent_950498"),
        ),
        StructuredTool.from_function(
            coroutine=remove_tool_from_agent,
            name="remove_tool_from_agent",
            description=tr("remove_tool_deployment_from_agent_3821f7"),
        ),
        StructuredTool.from_function(
            coroutine=add_mcp_tool_to_agent,
            name="add_mcp_tool_to_agent",
            description=tr("add_mcp_tool_batch_to_52f23d"),
        ),
        StructuredTool.from_function(
            coroutine=remove_mcp_tool_from_agent,
            name="remove_mcp_tool_from_agent",
            description=tr("remove_mcp_tool_deployment_from_2231ed"),
        ),
    ]
