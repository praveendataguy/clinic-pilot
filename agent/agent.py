import asyncio
import getpass
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import types

from agent.tools import call_mcp_tool, connect, get_gemini_tools

load_dotenv()

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MAX_TOOL_ROUNDS = 5

RECEPTIONIST_PROMPT = """
You are the front-desk receptionist for Sunrise Family Clinic. Be warm, brief and clear. Ask one or two questions at a time.
The web page has already shown a welcome note and the numbered list of all doctors, and asked which physician the caller would like to visit.

Booking flow (follow it in this order):
1. The caller chooses a doctor by name or by number from the list. Call get_doctor with exactly what they typed (a number like "7" or a name). Say the doctor's full name and specialty back to confirm. If they only name a specialty (ortho, cardio, gyneco, physio, general...), call list_doctors and ask them to choose.
2. BEFORE telling any slots, collect ALL of: full name, email, phone number, address, reason for visit, and whether this is their first visit to this doctor. Ask for whatever is missing and never skip an item. Then call save_patient_details.
3. Call get_week_availability with the patient_id and the doctor. Tell the caller the open times for the whole week, day by day, shortening consecutive times into ranges (for example Mon 22 Oct: 09:00 to 12:00 and 14:00 to 17:30).
4. When the caller picks a time, call book_appointment and read back the confirmation number.
5. If no_slots_this_week is true, say there is no availability this week and offer the waiting list. If they agree, call join_waitlist and tell them we will contact them by email and phone if a slot opens after a cancellation.

Other rules:
- Always use the tools. Never invent doctors, hours, availability or bookings.
- To cancel, ask for the phone number, call find_appointments, confirm which one, then call cancel_appointment.
- Convert words like "tomorrow" to YYYY-MM-DD using the current date given below.
- When you give times, copy them exactly as the tools return them (24-hour, like 09:00 or 18:00).
- If the caller asks for a human, a person or a manager, call transfer_to_human immediately. For emergencies, complaints or billing disputes, do the same.
- If a caller asks for medical advice, say you can't give it and offer an appointment or a human.
- Always ask which country the patient is in before taking the phone number. Never assume a country.
- If save_patient_details or take_message returns a phone error, read that error to the caller and ask for the number again. Do not continue until a valid number is accepted.
- Doctor reports (staff only): if asked for a doctor's report ("report for Dr. Omar Haddad", "how many patients did Dr. Kapoor see today"), first ask for the staff PIN if it hasn't been given. Then call doctor_report (day defaults to today). Say how many patients the doctor covered and show a markdown table with the columns Time, Patient name, Country, Phone, Email. Never show patient details if the PIN is wrong, and never repeat the PIN back.
- After showing a report, ask: "Do you need to export this report as .csv or .xlsx?" If the answer is yes, call export_doctor_report with the same doctor, day and PIN and the format they chose, then tell them the file was saved to their Downloads folder. If the answer is no, say OK and do nothing else.
- When you show availability as a range (for example 09:00 to 17:30), say the slots are every 30 minutes, and ask the caller for ONE exact start time such as 10:00 or 14:30. If they reply with a range or a vague time ("morning", "afternoon"), ask them to pick a specific time. Do not try to book until you have one exact date and time.
- If book_appointment or any other tool returns an error, read the error to the caller in plain words and ask them to try again. Never call transfer_to_human because a booking failed or a caller gave an unclear answer. Only call it when they ask for a person or have an emergency, complaint or billing dispute.
After a booking is confirmed, always tell the patient how to reach the doctor's room using the directions
in the booking confirmation (or call get_doctor_directions), and end with "Have a happy visit!".
If the patient asks where a doctor is, call get_doctor_directions.
- If a tool answer starts with "Permission denied", tell the receptionist plainly that their account is not allowed to do that and that the clinic owner can change their role. Do not try again, do not look for a workaround, and never call transfer_to_human because of it.
"""


class SessionExpired(Exception):
    """The login token was refused by the server (expired, logged out or switched off)."""


def _is_login_error(exc) -> bool:
    """True if an error (or any error inside an ExceptionGroup) is an HTTP 401 from the server."""
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_login_error(e) for e in exc.exceptions)
    return getattr(getattr(exc, "response", None), "status_code", None) == 401


GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")


def _is_busy_error(exc) -> bool:
    """Google says the model is overloaded (503) or we are sending too fast (429)."""
    code = getattr(exc, "code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return code in (429, 500, 502, 503, 504)


class MedicineAgent:
    """Keeps the conversation history and talks to Gemini plus the MCP server."""

    def __init__(self, token: str = "", role: str = "", user_name: str = ""):
        self.token = token          # login token, sent to the MCP server with every request
        self.role = role            # decides which tools the AI is offered
        self.user_name = user_name
        self.gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.history: list[types.Content] = []

    async def ask(self, user_text: str) -> tuple[str, list[str]]:
        """Send one user message. Returns the reply and the tool calls made (for the UI).
        Raises SessionExpired when the server says the login is no longer valid."""
        start = len(self.history)
        try:
            return await self._ask(user_text)
        except BaseException as e:
            if _is_login_error(e):
                del self.history[start:]
                raise SessionExpired() from None
            raise

    async def _generate(self, config):
        """Call Gemini. If Google is busy, wait and retry, then try the backup model."""
        models = [GEMINI_MODEL] * 3 + ([GEMINI_FALLBACK_MODEL] * 2 if GEMINI_FALLBACK_MODEL != GEMINI_MODEL else [])
        last = None
        for attempt, model in enumerate(models):
            try:
                return await self.gemini.aio.models.generate_content(
                    model=model, contents=self.history, config=config)
            except Exception as e:                      # noqa: BLE001
                if not _is_busy_error(e):
                    if last is not None:                # the backup model failed too: report the original problem
                        raise last
                    raise
                last = e
                await asyncio.sleep(min(2 * (attempt + 1), 6))
        raise last

    async def _ask(self, user_text: str) -> tuple[str, list[str]]:
        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
        tool_log = []
        now = datetime.now().strftime("%A, %Y-%m-%d %H:%M")
        who = f"\nLogged-in staff member: {self.user_name} (role: {self.role})." if self.user_name else ""
        system_prompt = f"{RECEPTIONIST_PROMPT}{who}\nCurrent date and time: {now}."

        async with connect(MCP_SERVER_URL, self.token) as mcp:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[await get_gemini_tools(mcp, self.role)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

            for _ in range(MAX_TOOL_ROUNDS):
                response = await self._generate(config)
                self.history.append(response.candidates[0].content)

                if not response.function_calls:
                    return response.text or "Sorry, I didn't catch that.", tool_log

                results = []
                for call in response.function_calls:
                    args = dict(call.args or {})
                    output = await call_mcp_tool(mcp, call.name, args)
                    tool_log.append(f"{call.name}({args}) -> {output}")
                    results.append(types.Part.from_function_response(name=call.name, response={"result": output}))
                self.history.append(types.Content(role="user", parts=results))

        return "Sorry, that took too many steps. Please try asking in a simpler way.", tool_log


async def main():
    """Chat with the agent in the terminal. Type 'quit' to stop."""
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
    import auth
    auth.init_auth()
    login = auth.login(input("Email: "), getpass.getpass("Password: "))
    if not login["ok"]:
        print(login["error"])
        return
    user = login["user"]
    agent = MedicineAgent(token=login["token"], role=user["role"], user_name=user["name"])
    print(f"Sunrise Clinic Receptionist - logged in as {user['name']} ({user['role']}). Type 'quit' to stop.")
    while True:
        user_text = input("\nYou: ").strip()
        if user_text.lower() in {"quit", "exit"}:
            break
        if not user_text:
            continue
        try:
            reply, tool_log = await agent.ask(user_text)
        except SessionExpired:
            print("Your login has expired. Please start again.")
            return
        for line in tool_log:
            print(f"  [tool] {line}")
        print(f"Receptionist: {reply}")


if __name__ == "__main__":
    asyncio.run(main())