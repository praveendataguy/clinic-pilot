# Friction Log: building ClinicPilot (self-hosted MCP server + Alexa+ style web app)

Severity scale: **High** = blocked me for a long time, **Medium** = cost real time but had a clear workaround, **Low** = minor annoyance.

## 1. Confirming the MCP spec version (Medium)
- **Task:** Prove my server speaks MCP spec 2025-11-25, as the Alexa+ track requires.
- **Steps:** Installed the Python MCP SDK, started a FastMCP server over Streamable HTTP, and looked for where the negotiated version is shown.
- **Expected:** A clear place in the docs or SDK output stating the spec version.
- **Actual:** Nothing obvious. I had to inspect `mcp.types.LATEST_PROTOCOL_VERSION` and test a real client connection to see 2025-11-25 negotiated.
- **Workaround:** Pinned `mcp>=1.23,<2` and documented the check command in the README.
- **Suggestion:** Show the supported spec version in the starter docs, with a one-line command to verify it.

## 2. Testing against Alexa+ itself (Medium)
- **Task:** Check that my MCP tools behave correctly when called by an Alexa+ style agent.
- **Steps:** Looked for a way to point a local self-hosted MCP server at Alexa+ for testing.
- **Expected:** A local test harness or sandbox.
- **Actual:** I did not find one in the time available, so I built my own Streamlit chat client with a Gemini agent that calls the same MCP tools.
- **Workaround:** The simulated web app (optional part of the track).
- **Suggestion:** Provide a local Alexa+ test harness or emulator for MCP servers.

## 3. Long chats dropping the connection (High)
- **Task:** Complete a multi-step booking conversation through the MCP server.
- **Steps:** Booked an appointment over many turns using Streamable HTTP and uvicorn.
- **Expected:** The session stays connected.
- **Actual:** `RemoteProtocolError: server disconnected` partway through longer chats.
- **Workaround:** Set `timeout_keep_alive=300` in uvicorn.
- **Suggestion:** Document recommended keep-alive settings for Streamable HTTP servers.

## 4. Nested errors hiding the real cause (Medium)
- **Task:** Find out why a tool call failed.
- **Steps:** Triggered a failing call through the MCP client.
- **Expected:** A readable error message.
- **Actual:** A nested `ExceptionGroup` / TaskGroup error that hid the real cause (for example, a missing database table).
- **Workaround:** Wrote a `root_error()` helper that unwraps the group and shows the underlying error in the chat and logs.
- **Suggestion:** Surface the root cause by default in the client.

## 5. Tool errors easy to miss (Medium)
- **Task:** Know when a tool failed inside an otherwise normal-looking reply.
- **Steps:** A tool raised an error but the agent carried on and replied.
- **Expected:** An obvious signal of tool health.
- **Actual:** The failure was only visible inside the tool result text.
- **Workaround:** Built Observability Logs that flag tool errors, unanswered questions and escalations.
- **Suggestion:** Provide a standard way to report tool success or failure to the client.

## 6. Running the agent from the project root (Low)
- **Task:** Run `python agent/agent.py`.
- **Expected:** It runs.
- **Actual:** `ModuleNotFoundError`, because the folder is a package.
- **Workaround:** `python -m agent.agent` (also `python -m tests.try_server`).
- **Suggestion:** Show module-style run commands in examples.

## 7. LLM model availability (Medium)
- **Task:** Keep the agent responding during the demo.
- **Steps:** Called the Gemini API during peak hours.
- **Expected:** Stable model names and availability.
- **Actual:** A model was retired for new users (404) and another returned 503 under high demand.
- **Workaround:** Model name and a fallback model are set in `.env`; the agent retries with a short wait, then switches to the fallback.
- **Suggestion:** Warn clearly when a model is deprecated and give a stable alias.