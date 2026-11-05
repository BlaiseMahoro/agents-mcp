from agents_core.mcp_server.server import build_server
from agents_core.store.settings import update_settings


async def tool_names():
    tools = await build_server().list_tools()
    return {t.name for t in tools}


async def test_all_tools_when_enabled():
    assert await tool_names() == {"research", "create_plan", "execute_plan", "run_pipeline", "list_agents", "get_plan", "list_plans"}


async def test_disabled_agent_tool_not_registered():
    update_settings({"enabled": {"execute": False, "research": False}})
    names = await tool_names()
    assert "execute_plan" not in names and "research" not in names
    assert "create_plan" in names
