from pathlib import Path
import yaml

ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

ALLOWED_METHODS = {
    "restconf",
    "netconf",
    "ansible",
    "netmiko-textfsm",
}

METHOD_ACTIONS = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md and specs/desired-state-spec-v1.md.
    """
    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    # 1. version: must be the YAML integer 1
    # In Python, bool is a subclass of int, so we check `type(v) is int`
    version = data.get("version")
    if "version" not in data or type(version) is not int or version != 1:
        return {"status": "error", "result": "invalid_version"}

    # 2. router: missing_router, then invalid_router
    if "router" not in data or data["router"] is None or data["router"] == "":
        return {"status": "error", "result": "missing_router"}
    if str(data["router"]) not in ALLOWED_ROUTERS:
        return {"status": "error", "result": "invalid_router"}

    # 3. method: missing_method, then invalid_method
    if "method" not in data or data["method"] is None or data["method"] == "":
        return {"status": "error", "result": "missing_method"}
    if data["method"] not in ALLOWED_METHODS:
        return {"status": "error", "result": "invalid_method"}

    # 4. action: missing_action, then invalid_action
    if "action" not in data or data["action"] is None or data["action"] == "":
        return {"status": "error", "result": "missing_action"}
    if data["action"] not in METHOD_ACTIONS.get(data["method"], set()):
        return {"status": "error", "result": "invalid_action"}

    # 5. desired, desired.interface, desired.interface.name
    if "desired" not in data or not isinstance(data["desired"], dict):
        return {"status": "error", "result": "missing_desired"}
    desired = data["desired"]

    if "interface" not in desired or not isinstance(desired["interface"], dict):
        return {"status": "error", "result": "missing_interface"}
    iface = desired["interface"]

    if "name" not in iface or iface["name"] is None or iface["name"] == "":
        return {"status": "error", "result": "missing_interface_name"}

    # 6. For plan and apply only:
    # missing_ipv4, missing_description, missing_admin_state, invalid_admin_state
    action = data["action"]
    if action in ("plan", "apply"):
        if "ipv4" not in iface or iface["ipv4"] is None or iface["ipv4"] == "":
            return {"status": "error", "result": "missing_ipv4"}
        if "description" not in iface or iface["description"] is None:
            return {"status": "error", "result": "missing_description"}
        if "admin_state" not in iface or iface["admin_state"] is None or iface["admin_state"] == "":
            return {"status": "error", "result": "missing_admin_state"}
        if iface["admin_state"] not in ("up", "down"):
            return {"status": "error", "result": "invalid_admin_state"}

    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return {"status": "error", "result": "invalid_yaml"}

    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    return validate_request(data)
