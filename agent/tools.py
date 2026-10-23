import sys
from contextlib import asynccontextmanager
from pathlib import Path

from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# permissions.py lives in server/. It has no imports, so it is safe to load from here.
sys.path.append(str(Path(__file__).resolve().parent.parent / "server"))
from permissions import allowed  # noqa: E402

# Tools the staff use through sidebar buttons or the PIN flow, hidden from the AI.
STAFF_ONLY_TOOLS = {"daily_report", "list_waitlist_notifications", "set_doctor_room"}


@asynccontextmanager
async def connect(url: str, token: str = ""):
    """Open a session with the MCP server. The login token travels in a header, so the
    server can check who is asking."""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def get_gemini_tools(client: ClientSession, role: str = "") -> types.Tool:
    """Turn the MCP server's tools into a tool list Gemini understands.
    With a role, tools that role may not use are left out, so the AI never offers them."""
    result = await client.list_tools()
    declarations = [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description or "",
            parameters_json_schema=tool.inputSchema,
        )
        for tool in result.tools
        if tool.name not in STAFF_ONLY_TOOLS and (not role or allowed(role, tool.name))
    ]
    return types.Tool(function_declarations=declarations)


async def call_mcp_tool(client: ClientSession, name: str, args: dict) -> str:
    """Run one tool on the MCP server and return its text answer."""
    result = await client.call_tool(name, args)
    text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
    return f"Error: {text}" if result.isError else text