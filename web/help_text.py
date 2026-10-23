DOCS_MD = """
## 1. What is this product?
**Sunrise Family Clinic AI Receptionist** is a virtual front-desk assistant used by clinic staff. A
receptionist logs in and chats with it to find a doctor, book an appointment, join a waiting list, cancel,
and get directions to the doctor's room. The clinic owner approves new staff accounts and chooses what each
person is allowed to do. Daily and per-doctor reports are available to staff.

It handles the routine work of a reception desk so that human staff can focus on patients who are in the
clinic and on cases that need a person.

## 2. Why was it developed?
- Front desks are busy at peak hours, and callers wait or give up.
- Booking by phone is slow: names, numbers and reasons are written down by hand and mistakes are common.
- Cancelled slots often stay empty because nobody tells the people waiting.
- Patients forget appointments, which wastes doctor time.
- Patients arriving for the first time do not know which floor or room to go to.

## 3. What can it do?
| Area | What it does |
|---|---|
| Doctors | Lists 55 doctors in 11 specialties. Pick by name or by list number. |
| Patient details | Collects name, email, country, phone, address, reason for visit and whether it is a first visit, and stores them **before** slots are shown. |
| Phone check | Checks the number against the patient's country (length, country code, mobile or landline) and rejects fake patterns such as 12345, 54321, 9999999999 or too many zeros. |
| Slots | Shows each doctor's free slots for the whole week. |
| Waiting list | If a doctor has no free slot, the patient can join a waiting list and is notified when a slot is cancelled. |
| Reminders | Emails the patient 1 hour before the appointment and asks them to reply **YES** or **CANCEL**. The answer is stored under the patient's details. A CANCEL reply frees the slot and notifies the waiting list. |
| Directions | After booking, tells the patient which floor and room to go to and ends with "Have a happy visit!". |
| Locate Doctor | A button that lists all doctors. Click a name to see the floor, room and directions. |
| Staff accounts | New staff create an account, the owner approves it and picks a role, and the new staff member is emailed. See section 4. |
| Reports (staff) | Daily report of patients per doctor, and a per-doctor report with each patient's name, country, phone and email, with optional CSV or XLSX export to Downloads. |
| Human help | Passes the conversation to a human when the patient asks or when it cannot help. |

## 4. Staff accounts and roles
**Getting access**
1. A new receptionist opens the app link and clicks **Create account**.
2. The clinic owner (super admin) gets an email and an alert in the app.
3. The owner opens **Access requests**, chooses a role and clicks **Approve** (or **Reject**).
4. The new receptionist gets an email saying the account is ready, then logs in with the email and password
   they chose.

**Roles**
| Role | What they can do |
|---|---|
| Viewer | Look things up only: doctors, slots, rooms, reports. Cannot book, save or change anything. |
| Editor | Everything a viewer can do, plus book, add patient details, join the waiting list, cancel, take messages. |
| Admin | Everything an editor can do, plus change doctor rooms and export reports. Cannot delete. |
| Super admin | Everything, including deleting records and approving accounts. Only the clinic owner. |

These limits are enforced by the server, not only by the screen. If someone asks the AI to do something their
role does not allow, it is refused and the AI explains why.

## 5. How was it built?
- **Python** for all code.
- **MCP server** (FastMCP, Streamable HTTP): holds the clinic's tools (booking, patients, reports) and the
  SQLite database. The assistant can only do what these tools allow.
- **Gemini** model with function calling: understands the patient's message and decides which tool to call.
- **Streamlit** web page: the chat window and the staff tools.
- **Email (SMTP/IMAP)**: a small background worker sends reminders and reads YES or CANCEL replies. The same
  mailer sends the account emails.
- **Accounts**: passwords are stored salted and hashed, logins create short-lived session tokens, and the MCP
  server checks the role of every tool call.
- **phonenumbers** library for country-aware phone checks, **openpyxl** for XLSX export.

Flow: Patient message -> Streamlit page -> Gemini agent -> MCP tool -> database -> answer back to the patient.

## 6. Rules for a better experience
**When helping a patient**
1. Say which doctor the patient wants, by **name** or by the **number** in the list.
2. Give the patient's details when asked: name, email, country, phone, address, reason for visit, and
   whether it is their first visit. Slots are shown only after this.
3. Give the patient's **country first**, then the phone number. Type digits only, for example `9841276053`.
4. Ask for **one exact time**, for example "Thursday 22 Oct at 10:00", not a range like "morning".
5. Use the patient's real email address. Their reminder and any waiting-list notice go there.
6. When the reminder email arrives, the patient replies with one word: **YES** to confirm or **CANCEL** to
   cancel.
7. Use **Locate Doctor** to show a patient how to reach a room: take the lift to the floor and follow the
   signboard with the doctor's name.
8. For emergencies, do not use the chat. Call your local emergency number.

**For staff**
1. Keep your password private and log out when you leave the desk. Report and room-change requests also need
   the **staff PIN**. Do not share it.
2. Ask for a doctor report by name and date, for example "report for Dr. Omar Haddad for 2026-10-22".
3. Say **yes** only if you want the CSV or XLSX export. If you say no, nothing is saved.
4. Keep the reminder worker running during clinic hours, or reminders will not be sent.

## 7. Business impact
These are the results the clinic should expect. They should be measured after the first weeks of use.
- **Less front-desk work:** routine booking, cancelling and "where is the doctor" questions are handled
  without staff.
- **Fewer no-shows:** reminder emails and easy cancelling help patients who would otherwise forget.
- **Fewer empty slots:** a cancelled slot is offered to the waiting list straight away.
- **Cleaner data:** details are validated (for example phone numbers) and stored in the same format every time.
- **Better visit experience:** patients are told exactly where to go, which reduces hallway questions and delays.
- **Clear reporting:** daily and per-doctor reports are available in seconds.
- **Always available:** patients can book outside opening hours.

Suggested measures: no-show rate before and after, average time to book, number of requests handled
without staff, and number of waiting-list patients who got a slot.

## 8. Current limits
- The assistant is not a doctor. It does not give medical advice or diagnoses.
- Reminder replies are read from one clinic mailbox while the worker is running.
- The staff PIN is a simple shared secret that sits on top of the staff login.
- The app and the server run on one computer. Putting it on the internet for the whole clinic is a separate
  step.
"""