import asyncio
import html
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from google.genai import types
import streamlit as st

# Let "streamlit run web/app.py" find the agent package in the project root, and let
# server/auth.py and server/permissions.py find their neighbours by plain name.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "server"))

from agent.agent import MCP_SERVER_URL, MedicineAgent, SessionExpired  # noqa: E402
from agent.tools import call_mcp_tool, connect  # noqa: E402
from server.doctors import DOCTORS, SPECIALTIES  # noqa: E402
import auth  # noqa: E402
from permissions import ASSIGNABLE_ROLES, ROLE_LABELS, allowed  # noqa: E402

import chatstore  # noqa: E402  (web/chatstore.py: chat history + observability log)

try:
    from help_text import DOCS_MD
except ImportError:
    DOCS_MD = "The documentation file is missing. Save web/help_text.py next to app.py."

st.set_page_config(page_title="Sunrise Clinic Receptionist", page_icon="🏥", layout="wide")

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root {--teal:#0d9488; --teal-d:#0f766e; --blue:#0369a1; --ink:#0f2a3a; --muted:#5b7384; --bg:#f3f8fa; --card:#ffffff;
       --line:#dbe7ec; --mint:#e6f6f3;}
.stApp, .stApp p, .stApp li, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp summary,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {font-family: 'Inter', system-ui, sans-serif;}
[data-testid="stIconMaterial"], .material-symbols-rounded {font-family: 'Material Symbols Rounded' !important;}
.stApp {background: radial-gradient(900px 420px at 100% -5%, rgba(13,148,136,.10), transparent 60%),
        radial-gradient(700px 400px at -5% 100%, rgba(3,105,161,.08), transparent 60%), var(--bg); color: var(--ink);}
.block-container {padding-top: 2.4rem; padding-bottom: 5rem; max-width: 1020px;}
[data-testid="stAppDeployButton"], .stDeployButton, [data-testid="stDecoration"] {display: none;}
[data-testid="stHeader"] {background: transparent;}

/* ---- sidebar ---- */
[data-testid="stSidebar"] {min-width: 350px; max-width: 350px; background: #ffffff; border-right: 1px solid var(--line);
    box-shadow: 4px 0 24px rgba(15,42,58,.05);}
[data-testid="stSidebarHeader"] {height: 1.6rem; padding: .2rem .8rem; margin: 0;}
[data-testid="stSidebarUserContent"] {padding: 0 1rem .8rem; min-height: calc(100vh - 2.2rem); display: flex; flex-direction: column;}
[data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"] {flex: 1;}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap: .4rem;}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {gap: .4rem;}
[data-testid="stSidebar"] hr {margin: .35rem 0; border-color: var(--line);}
[data-testid="stSidebar"] [data-testid="stMarkdown"], [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] [data-testid="stElementContainer"] {margin-bottom: 0 !important; margin-top: 0 !important;}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {margin: 0; font-size: .85rem;}
[data-testid="stSidebar"] .stButton button {background: #f8fbfc; border: 1px solid var(--line); color: var(--ink);
    border-radius: 10px; min-height: 2.25rem; padding: .15rem .4rem; gap: .3rem; font-weight: 500; transition: all .18s ease;}
[data-testid="stSidebar"] .stButton button p {font-size: .82rem; white-space: nowrap;}
[data-testid="stSidebar"] .stButton button:hover {border-color: var(--teal); color: var(--teal-d); background: var(--mint);
    box-shadow: 0 4px 14px rgba(13,148,136,.18); transform: translateY(-1px);}
.st-key-new_chat button {background: linear-gradient(135deg, #0d9488, #0369a1) !important; border: none !important;
    box-shadow: 0 4px 16px rgba(13,148,136,.35);}
.st-key-new_chat button p, .st-key-new_chat button span {color: #fff !important; font-weight: 600;}
.st-key-new_chat button:hover {filter: brightness(1.08); box-shadow: 0 6px 20px rgba(3,105,161,.4) !important;}
.st-key-bottom_bar {margin-top: auto; padding-top: .6rem; border-top: 1px solid var(--line);}
.st-key-bottom_bar [data-testid="stVerticalBlock"] {gap: .4rem;}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-chat_list) {border: none; background: transparent; padding: 0;}
.st-key-chat_list .stButton button {justify-content: flex-start; min-height: 2rem; background: transparent; border-color: transparent; font-weight: 400;}
.st-key-chat_list .stButton button p {overflow: hidden; text-overflow: ellipsis; max-width: 250px;}
.st-key-chat_list .stButton button > div {justify-content: flex-start !important; width: 100%; text-align: left;}
.st-key-chat_list .stButton button p {text-align: left;}
.st-key-chat_list .stButton button:hover {background: var(--mint);}
.sb-empty {color: var(--muted); font-size: .8rem; padding: .2rem .3rem;}
[data-testid="stSidebar"] [data-testid="stExpander"] {border: 1px solid var(--line); border-radius: 10px; background: #fafdfd;}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {padding: .35rem .6rem;}
[data-testid="stSidebar"] [data-testid="stDateInput"] input {padding: .35rem .6rem;}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {padding: .1rem 0; border-color: var(--line); background: #fafdfd; border-radius: 12px;}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {gap: .3rem; padding: .1rem .2rem;}

.sb-card {display: flex; align-items: center; gap: .7rem; padding: .55rem .7rem; border-radius: 14px;
    background: linear-gradient(135deg, #e6f6f3, #e8f2fa); border: 1px solid #c7e6e1;}
.sb-avatar {width: 2.3rem; height: 2.3rem; border-radius: 50%; flex: none; display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: .85rem; color: #fff; background: linear-gradient(135deg, #0d9488, #0369a1);
    box-shadow: 0 0 0 3px #fff, 0 2px 10px rgba(13,148,136,.4);}
.sb-info {min-width: 0;}
.sb-name {font-weight: 650; font-size: .95rem; line-height: 1.15; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.sb-role {display: inline-block; margin-top: .2rem; padding: .05rem .55rem; border-radius: 999px; font-size: .66rem; font-weight: 700;
    color: #fff; letter-spacing: .05em; text-transform: uppercase;}
.sb-title {font-weight: 700; font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: var(--teal-d); margin-top: .1rem;}
.sb-count {background: #e11d48; color: #fff; border-radius: 999px; padding: 0 .45rem; font-size: .68rem; margin-left: .4rem;}

/* ---- hero ---- */
.hero {position: relative; overflow: hidden; border-radius: 20px; padding: 1.3rem 1.6rem; margin-bottom: 1rem; color: var(--ink);
    background: linear-gradient(120deg, #ffffff 0%, #e9f7f4 55%, #dcedf8 100%); border: 1px solid #cfe5e6;
    box-shadow: 0 10px 34px rgba(13,148,136,.14);}
.hero::before {content: "+"; position: absolute; right: 1.4rem; top: -1.6rem; font-size: 11rem; font-weight: 300; line-height: 1;
    color: rgba(13,148,136,.10);}
.hero::after {content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: linear-gradient(180deg, #0d9488, #0369a1);}
.hero > * {position: relative; z-index: 1;}
.hero-top {display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;}
.hero-title {font-size: 1.8rem; font-weight: 800; line-height: 1.15; letter-spacing: -.02em; color: #0b3b4a;}
.hero-sub {color: var(--muted); margin-top: .3rem; font-size: 1rem;}
.live {font-weight: 600; font-size: .75rem; color: #047857; padding: .25rem .75rem; border-radius: 999px;
    border: 1px solid #a7e3c9; background: #ecfdf5; white-space: nowrap;}
.live i {display: inline-block; width: .5rem; height: .5rem; border-radius: 50%; background: #10b981; margin-right: .45rem;
    box-shadow: 0 0 0 0 rgba(16,185,129,.6); animation: pulse 1.8s infinite;}
@keyframes pulse {70% {box-shadow: 0 0 0 .55rem rgba(16,185,129,0);} 100% {box-shadow: 0 0 0 0 rgba(16,185,129,0);}}
.chips {margin-top: .85rem; display: flex; gap: .45rem; flex-wrap: wrap;}
.chips span {font-weight: 500; font-size: .76rem; color: #0f5560; background: rgba(255,255,255,.85); border: 1px solid #bfe0df;
    border-radius: 999px; padding: .18rem .75rem;}
.chips span b {color: var(--teal-d); font-weight: 700;}

/* ---- main area ---- */
[data-testid="stChatMessage"] {background: var(--card); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 2px 12px rgba(15,42,58,.05);}
[data-testid="stExpander"] {border-color: var(--line); border-radius: 12px; background: #fff;}
[data-testid="stExpander"] summary:hover {color: var(--teal-d);}
[data-testid="stChatInput"] {border: 1.5px solid #b9dcd8; border-radius: 16px; background: #fff; box-shadow: 0 4px 20px rgba(13,148,136,.10);}
[data-testid="stChatInput"]:focus-within {border-color: var(--teal); box-shadow: 0 0 0 3px rgba(13,148,136,.18);}
[data-testid="stAlert"] {border-radius: 12px;}
.stTabs [data-baseweb="tab"] {font-weight: 600;}
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)

ROLE_COLORS = {"super_admin": "#0f766e", "admin": "#0369a1", "editor": "#0891b2", "viewer": "#64748b"}


def ui_button(label, icon=None, **kw):
    """st.button with an icon; older Streamlit versions just get the plain button."""
    if icon:
        try:
            return st.button(label, icon=icon, **kw)
        except TypeError:
            pass
    return st.button(label, **kw)


def ui_columns(spec):
    try:
        return st.columns(spec, vertical_alignment="center")
    except TypeError:
        return st.columns(spec)


def hero():
    st.markdown(
        '<div class="hero"><div class="hero-top"><div><div class="hero-title">🏥 Sunrise Clinic AI Receptionist</div>'
        '<div class="hero-sub">Book or cancel an appointment, leave a message, or ask for a human.</div></div>'
        '<div class="live"><i></i>CLINIC OPEN</div></div>'
        f'<div class="chips"><span><b>{len(DOCTORS)}</b> doctors</span><span><b>{len(SPECIALTIES)}</b> specialties</span>'
        '<span>AI-assisted booking</span><span>Secure staff access</span><span>Room directions</span></div></div>',
        unsafe_allow_html=True)


@st.cache_resource
def _setup():
    auth.init_auth()      # creates the tables and the super admin (once)
    return True


_setup()

# The Documentation window (falls back to a plain section on very old Streamlit versions).
def _docs_body():
    st.markdown(DOCS_MD)


show_docs = None
if hasattr(st, "dialog"):
    try:
        show_docs = st.dialog("Documentation", width="large")(_docs_body)
    except TypeError:
        show_docs = st.dialog("Documentation")(_docs_body)


def _locate_body():
    """List every doctor. Clicking a name shows how to reach their room."""
    st.caption("Tap a doctor's name to see how to reach their room.")
    box = st.container()
    for specialty in SPECIALTIES:
        docs = [d for d in DOCTORS if d["specialty"] == specialty]
        with st.expander(f"{specialty} ({len(docs)})"):
            for d in docs:
                if st.button(f"{d['id']}. {d['name']}", key=f"loc_{d['id']}", use_container_width=True):
                    st.session_state["located"] = d["id"]
    picked = st.session_state.get("located")
    doc = next((x for x in DOCTORS if x["id"] == picked), None) if picked else None
    if doc:
        with box:
            try:
                text = asyncio.run(call_staff_tool("get_doctor_directions", {"doctor": str(doc["id"])}))
            except Exception as e:
                text = f"Error: {e}"
            if text.startswith("Error:"):
                st.error(f"Could not get directions. {text}")
            else:
                st.success(f"**{doc['name']}** · {doc['specialty']}\n\n{text}")


show_locate = None
if hasattr(st, "dialog"):
    try:
        show_locate = st.dialog("Locate a doctor", width="large")(_locate_body)
    except TypeError:
        show_locate = st.dialog("Locate a doctor")(_locate_body)


def clear_session(notice=""):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    if notice:
        st.session_state["notice"] = notice


def show_login():
    hero()
    if st.session_state.get("notice"):
        st.info(st.session_state.pop("notice"))
    tab_in, tab_up = st.tabs(["Log in", "Create account"])
    with tab_in:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            pw = st.text_input("Password", type="password", key="login_password")
            go = st.form_submit_button("Log in")
        if go:
            r = auth.login(email, pw)
            if r["ok"]:
                st.session_state["user"] = {"token": r["token"], **r["user"]}
                st.rerun()
            else:
                st.error(r["error"])
    with tab_up:
        st.write("New to the clinic? Create an account. The clinic owner will approve it and "
                 "choose your role, and you will get an email when it is ready.")
        with st.form("signup_form"):
            name = st.text_input("Full name", key="signup_name")
            email2 = st.text_input("Email", key="signup_email")
            pw1 = st.text_input("Password (8+ characters, letters and numbers)", type="password", key="signup_password")
            pw2 = st.text_input("Repeat password", type="password", key="signup_password2")
            go2 = st.form_submit_button("Create account")
        if go2:
            if pw1 != pw2:
                st.error("The two passwords do not match.")
            else:
                r = auth.signup(name, email2, pw1)
                (st.success if r["ok"] else st.error)(r["message"])


# ---- Must be logged in ----
user = st.session_state.get("user")
if user:
    fresh = auth.verify_token(user["token"])      # re-checked on every click; the role comes from the database
    if fresh is None:
        clear_session("Your session has ended. Please log in again.")
        user = None
    else:
        user = {"token": user["token"], **fresh}
if not user:
    show_login()
    st.stop()

role = user["role"]
is_super = role == "super_admin"
can_write = allowed(role, "book_appointment")
pending = auth.pending_requests(user["token"]) if is_super else []

hero()

flash = st.session_state.pop("flash", None)
if flash:
    (st.success if flash["ok"] else st.error)(flash["message"])
if pending:
    st.warning(f"{len(pending)} account request(s) waiting for your approval. "
               f"Open **Access requests** in the sidebar.")
if not can_write:
    st.info(f"You are signed in as a {ROLE_LABELS.get(role, role)}. You can look things up, "
            f"but booking and changes are switched off for your account.")

if "history" not in st.session_state:
    st.session_state.history = []   # Gemini conversation
if "chat" not in st.session_state:
    st.session_state.chat = []      # (role, text, tool_log) for display
if "conv_id" not in st.session_state:
    st.session_state.conv_id = chatstore.new_id()


def root_error(exc):
    """The real reason inside nested ExceptionGroups (the MCP client wraps errors in TaskGroups)."""
    seen = 0
    while getattr(exc, "exceptions", None) and seen < 10:
        exc = exc.exceptions[0]
        seen += 1
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    text = f"{type(exc).__name__}: {exc}"
    return f"{text} (HTTP {code})" if code else text


def start_new_chat():
    st.session_state.history = []
    st.session_state.chat = []
    st.session_state.conv_id = chatstore.new_id()


def open_chat(conv_id):
    """Re-open one of this user's earlier conversations (the AI continues from the text of it)."""
    msgs = chatstore.load_conversation(conv_id, user["email"])
    if not msgs:
        return
    st.session_state.chat = msgs
    st.session_state.history = [
        types.Content(role="user" if r == "user" else "model", parts=[types.Part.from_text(text=t)])
        for r, t, _ in msgs if t
    ]
    st.session_state.conv_id = conv_id


def _obs_body():
    """Observability Logs: replies that failed or did not help, for the product owner."""
    info = chatstore.stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    by = info["by_flag"]
    c1.metric("Replies", info["total"])
    c2.metric("Errors", by.get("error", 0))
    c3.metric("Tool errors", by.get("tool_error", 0))
    c4.metric("Unanswered", by.get("unanswered", 0))
    c5.metric("Escalated", by.get("escalated", 0))
    st.caption("Shows chats where the assistant failed, was refused by a tool, did not have the information, "
               "or had to hand over to a human. Use it to find what to improve next.")
    pick = st.radio("Show", ["All", "Errors", "Tool errors", "Unanswered", "Escalated"], horizontal=True,
                    label_visibility="collapsed")
    flag = {"All": "", "Errors": "error", "Tool errors": "tool_error", "Unanswered": "unanswered",
            "Escalated": "escalated"}[pick]
    show_done = st.checkbox("Include resolved", value=False)
    rows = chatstore.flagged(flag, include_resolved=show_done)
    if not rows:
        st.success("Nothing to review here. Every reply looks fine.")
        return
    df = pd.DataFrame([{"time": r["ts"], "type": chatstore.FLAG_LABELS[r["flag"]], "user": r["user_name"],
                        "question": r["question"], "reply": r["reply"], "reason": r["reason"],
                        "resolved": bool(r["resolved"])} for r in rows])
    st.download_button("Download CSV", df.to_csv(index=False), file_name="observability_logs.csv", mime="text/csv")
    for r in rows:
        icon = chatstore.FLAG_ICONS[r["flag"]]
        title = " ".join((r["question"] or "").split())[:70]
        with st.expander(f"{icon} {r['ts']} · {chatstore.FLAG_LABELS[r['flag']]} · {title}"):
            st.markdown(f"**Asked by:** {r['user_name']}  \n**Why flagged:** {r['reason']}")
            st.markdown("**Question**")
            st.write(r["question"])
            st.markdown("**Assistant reply**")
            st.write(r["reply"])
            if r["tools"]:
                st.markdown("**Tools used**")
                for line in r["tools"]:
                    st.code(line[:600])
            if r["resolved"]:
                if st.button("Re-open", key=f"obs_open_{r['id']}"):
                    chatstore.resolve(r["id"], False)
                    st.rerun()
            elif st.button("Mark as resolved", key=f"obs_done_{r['id']}"):
                chatstore.resolve(r["id"], True)
                st.rerun()


show_obs = None
if hasattr(st, "dialog"):
    try:
        show_obs = st.dialog("Observability Logs", width="large")(_obs_body)
    except TypeError:
        show_obs = st.dialog("Observability Logs")(_obs_body)


async def call_staff_tool(name, args):
    async with connect(MCP_SERVER_URL, user["token"]) as mcp:
        return await call_mcp_tool(mcp, name, args)


with st.sidebar:
    initials = "".join(w[0] for w in user["name"].split()[:2]).upper() or "?"
    card = (f'<div class="sb-card"><div class="sb-avatar">{html.escape(initials)}</div><div class="sb-info">'
            f'<div class="sb-name">{html.escape(user["name"])}</div>'
            f'<span class="sb-role" style="background:{ROLE_COLORS.get(role, "#64748b")}">'
            f'{html.escape(ROLE_LABELS.get(role, role))}</span></div></div>')
    st.markdown(card, unsafe_allow_html=True)
    r1, r2 = st.columns([3, 2])
    with r1:
        if ui_button("New chat", ":material/add_comment:", key="new_chat", use_container_width=True):
            start_new_chat()
            st.rerun()
    with r2:
        if ui_button("Log out", ":material/logout:", key="logout", use_container_width=True):
            auth.logout(user["token"])
            clear_session("You have been logged out.")
            st.rerun()
    if ui_button("Locate Doctor", ":material/location_on:", key="locate_button", use_container_width=True):
        st.session_state.pop("located", None)
        if show_locate:
            show_locate()
        else:
            st.session_state["locate_open"] = True

    # ---- Access requests (super admin only) ----
    if is_super:
        st.divider()
        badge = f'<span class="sb-count">{len(pending)}</span>' if pending else ""
        st.markdown(f'<div class="sb-title">🛡️ Access requests{badge}</div>', unsafe_allow_html=True)
        if not pending:
            st.caption("No requests waiting.")
        for p in pending:
            with st.container(border=True):
                st.markdown(f"**{html.escape(p['name'])}** · {html.escape(p['email'])}")
                pick = st.selectbox("Role", list(ASSIGNABLE_ROLES), index=0, label_visibility="collapsed",
                                    format_func=lambda r: ROLE_LABELS[r], key=f"role_{p['id']}")
                c1, c2 = st.columns(2)
                with c1:
                    if ui_button("Approve", ":material/check_circle:", key=f"approve_{p['id']}", use_container_width=True):
                        st.session_state["flash"] = auth.approve(user["token"], p["id"], pick)
                        st.rerun()
                with c2:
                    if ui_button("Reject", ":material/cancel:", key=f"reject_{p['id']}", use_container_width=True):
                        st.session_state["flash"] = auth.reject(user["token"], p["id"])
                        st.rerun()
        with st.expander("👥 All users"):
            people = auth.list_users(user["token"])
            if people:
                st.dataframe(pd.DataFrame(people), hide_index=True)

    st.divider()
    st.markdown('<div class="sb-title">📊 Staff tools</div>', unsafe_allow_html=True)
    report_day = st.date_input("Report date", value=date.today(), label_visibility="collapsed")
    t1, t2 = st.columns(2)
    with t1:
        if ui_button("Daily report", ":material/bar_chart:", key="daily_report_btn", use_container_width=True):
            try:
                raw = asyncio.run(call_staff_tool("daily_report", {"day": report_day.isoformat()}))
                st.session_state.report = json.loads(raw)
            except Exception as e:
                st.error(f"Could not build the report: {e}")
    with t2:
        if ui_button("Waitlist", ":material/notifications:", key="waitlist_btn", use_container_width=True):
            try:
                raw = asyncio.run(call_staff_tool("list_waitlist_notifications", {}))
                st.session_state.notes = json.loads(raw)
            except Exception as e:
                st.error(f"Could not load notifications: {e}")

    st.divider()
    st.markdown('<div class="sb-title">💬 Recent chats</div>', unsafe_allow_html=True)
    try:
        chat_box = st.container(height=165, key="chat_list")
    except TypeError:
        chat_box = st.container()
    with chat_box:
        convs = chatstore.list_conversations(user["email"])
        if not convs:
            st.markdown('<div class="sb-empty">Your conversations will appear here.</div>', unsafe_allow_html=True)
        for cv in convs:
            mark = "● " if cv["id"] == st.session_state.conv_id else ""
            if ui_button(mark + cv["title"], ":material/chat_bubble_outline:", key=f"conv_{cv['id']}",
                         use_container_width=True, help=cv["updated_at"]):
                open_chat(cv["id"])
                st.rerun()

    try:
        bottom = st.container(key="bottom_bar")
    except TypeError:
        bottom = st.container()
    with bottom:
        if is_super:
            if ui_button("Observability Logs", ":material/monitor_heart:", key="obs_button", use_container_width=True):
                if show_obs:
                    show_obs()
                else:
                    st.session_state["obs_open"] = True
        if ui_button("Documentation", ":material/menu_book:", key="docs_button", use_container_width=True):
            if show_docs:
                show_docs()
            else:
                st.session_state["docs_open"] = True

if st.session_state.get("obs_open"):        # only used when the pop-up window is unavailable
    with st.expander("Observability Logs", expanded=True):
        _obs_body()
        if st.button("Close", key="obs_close"):
            st.session_state["obs_open"] = False
            st.rerun()

if st.session_state.get("docs_open"):       # only used when the Documentation window is unavailable
    with st.expander("Documentation", expanded=True):
        st.markdown(DOCS_MD)
        if st.button("Close documentation"):
            st.session_state["docs_open"] = False
            st.rerun()

if st.session_state.get("locate_open"):     # only used when the pop-up window is unavailable
    with st.expander("Locate a doctor", expanded=True):
        _locate_body()
        if st.button("Close", key="locate_close"):
            st.session_state["locate_open"] = False
            st.rerun()

# ---- Welcome note and numbered doctor list ----
with st.chat_message("assistant"):
    st.write(
        "Welcome to Sunrise Family Clinic! I'm your AI receptionist. "
        "I can book or cancel appointments, answer questions, take messages, "
        "or connect you with our staff."
    )
    st.markdown(f"**Our {len(DOCTORS)} doctors across {len(SPECIALTIES)} specialties:**")
    grid = st.columns(3)
    for i, specialty in enumerate(SPECIALTIES):
        docs = [d for d in DOCTORS if d["specialty"] == specialty]
        with grid[i % 3]:
            with st.expander(f"{specialty} ({len(docs)})"):
                st.markdown("\n".join(
                    f"- **{d['id']}.** {d['name']} · {d['experience_years']} yrs experience" for d in docs
                ))
    st.write("**Which physician would you like to visit?** Type a name or the number from the list.")

# ---- Staff results ----
report = st.session_state.get("report")
if report:
    with st.expander(f"Daily report for {report['day']} · {report['total_patients']} patients", expanded=True):
        df = pd.DataFrame(report["report"])
        st.dataframe(df, hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False),
                           file_name=f"report_{report['day']}.csv", mime="text/csv")

notes = st.session_state.get("notes")
if notes is not None:
    with st.expander("Waitlist notifications", expanded=True):
        if notes["notifications"]:
            for n in notes["notifications"]:
                st.write(f"{n['created_at']} → {n['email']}: {n['message']}")
        else:
            st.write("None yet.")

# ---- Chat ----
for chat_role, text, tools in st.session_state.chat:
    with st.chat_message(chat_role):
        st.write(text)
        if tools:
            with st.expander("Tools used"):
                for line in tools:
                    st.code(line)

prompt = st.chat_input("Type a doctor's name or number, or ask anything")
if prompt:
    st.session_state.chat.append(("user", prompt, []))
    with st.chat_message("user"):
        st.write(prompt)

    agent = MedicineAgent(token=user["token"], role=role, user_name=user["name"])
    agent.history = st.session_state.history

    turn_error = None
    with st.chat_message("assistant"):
        with st.spinner("One moment..."):
            try:
                reply, tool_log = asyncio.run(agent.ask(prompt))
            except SessionExpired:
                clear_session("Your session has ended. Please log in again.")
                st.rerun()
            except Exception as e:
                agent.history = []   # reset so a half-finished turn can't break the next one
                turn_error = root_error(e)
                reply, tool_log = f"Sorry, something went wrong: {turn_error}", []
        st.write(reply)
        if tool_log:
            with st.expander("Tools used"):
                for line in tool_log:
                    st.code(line)

    st.session_state.history = agent.history
    st.session_state.chat.append(("assistant", reply, tool_log))
    chatstore.save_turn(st.session_state.conv_id, user, prompt, reply, tool_log, turn_error)
    st.rerun()
