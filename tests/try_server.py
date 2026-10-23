"""Smoke test for the MCP server. Start the server first:  python server/main.py
Run from the project root:  python -m tests.try_server
It logs in as the owner (SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD from .env), then
books a test patient. Delete server/reception.db afterwards for a clean start."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import auth  # noqa: E402
from agent.tools import call_mcp_tool, connect  # noqa: E402

URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")


async def main():
    login = auth.login(os.environ["SUPER_ADMIN_EMAIL"], os.environ["SUPER_ADMIN_PASSWORD"])
    if not login.get("ok"):
        print("Login failed:", login.get("error"))
        return
    token = login["token"]

    async with connect(URL, token) as mcp:
        print("Tools:", [t.name for t in (await mcp.list_tools()).tools])
        print("\nDoctor 7:", await call_mcp_tool(mcp, "get_doctor", {"doctor": "7"}))

        print("\nSlots without details (must be refused):",
              await call_mcp_tool(mcp, "get_week_availability", {"patient_id": 99999, "doctor": "7"}))

        saved = json.loads(await call_mcp_tool(mcp, "save_patient_details", {
            "name": "Test Patient", "email": "test@example.com", "country": "India",
            "phone": "9841276053", "address": "Chennai", "reason": "Knee pain",
            "first_visit": True, "doctor": "7"}))
        print("\nSaved:", saved)
        pid = saved["patient_id"]

        week = json.loads(await call_mcp_tool(mcp, "get_week_availability",
                                              {"patient_id": pid, "doctor": "7"}))
        print("\nDays with slots:", [d["day"] for d in week["days"]])

        if week["days"]:
            first = week["days"][0]
            print("\nBooking:", await call_mcp_tool(mcp, "book_appointment", {
                "patient_id": pid, "doctor": "7", "day": first["day"], "at": first["times"][0]}))

        report = json.loads(await call_mcp_tool(mcp, "daily_report", {}))
        print("\nToday's report total patients:", report["total_patients"])


asyncio.run(main())