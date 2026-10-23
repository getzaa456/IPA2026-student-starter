"""Part 4 student implementation."""

from app.backends import ansible, netconf, netmiko_textfsm, restconf


def dispatch_request(data):
    """
    Dispatch a validated request to the appropriate backend.
    """
    method = str(data["method"]).strip().lower()
    action = str(data["action"]).strip().lower()
    router = str(data["router"]).strip()
    interface = data["desired"]["interface"]

    if method == "restconf":
        if action == "status":
            return restconf.get_interface_state(router, interface["name"])
        if action == "plan":
            return restconf.plan_interface(router, interface)
        if action == "apply":
            return restconf.apply_interface(router, interface)

    elif method == "netconf":
        if action == "status":
            return netconf.get_interface_state(router, interface["name"])
        if action == "plan":
            return netconf.plan_interface(router, interface)
        if action == "apply":
            return netconf.apply_interface(router, interface)

    elif method == "ansible":
        if action == "apply":
            return ansible.apply_interface(router, interface)

    elif method == "netmiko-textfsm":
        if action == "status":
            return netmiko_textfsm.get_interface_state(router, interface["name"])
        if action == "delete":
            return netmiko_textfsm.delete_interface(router, interface["name"])

    return {"status": "error", "result": "invalid_action"}
