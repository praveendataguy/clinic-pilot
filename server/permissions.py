"""Who may do what. No imports, so the server, the agent and the web app can all use it."""

ROLE_LABELS = {
    "viewer": "Viewer",
    "editor": "Editor",
    "admin": "Admin",
    "super_admin": "Super admin",
}

# Roles the super admin can hand out. super_admin itself is never assigned.
ASSIGNABLE_ROLES = ("viewer", "editor", "admin")

ROLE_PERMS = {
    "viewer": {"read"},
    "editor": {"read", "write"},
    "admin": {"read", "write", "admin"},
    "super_admin": {"read", "write", "admin", "delete"},
}

# Every MCP tool and the permission it needs.
# read   = look things up
# write  = insert or update (booking, patient details, cancelling, messages)
# admin  = settings and exports
# delete = removing records (no such tool yet; only the super admin could use one)
# A tool missing from this list is allowed for the super admin only.
TOOL_PERMISSIONS = {
    "get_business_info": "read",
    "list_specialties": "read",
    "list_doctors": "read",
    "get_doctor": "read",
    "get_doctor_directions": "read",
    "get_week_availability": "read",
    "find_appointments": "read",
    "daily_report": "read",
    "doctor_report": "read",
    "list_waitlist_notifications": "read",
    "save_patient_details": "write",
    "book_appointment": "write",
    "join_waitlist": "write",
    "cancel_appointment": "write",
    "take_message": "write",
    "check_in_visitor": "write",
    "transfer_to_human": "write",
    "export_doctor_report": "admin",
    "set_doctor_room": "admin",
}


def allowed(role, tool):
    need = TOOL_PERMISSIONS.get(tool)
    if need is None:
        return role == "super_admin"
    return need in ROLE_PERMS.get(role, set())