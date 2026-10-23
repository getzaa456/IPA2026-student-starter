import os


def _normalize_name(name):
    if not name:
        return ""
    name_str = str(name).strip()
    lower = name_str.lower()
    if lower.startswith("loopback"):
        return f"loopback{lower[8:]}"
    if lower.startswith("lo"):
        return f"loopback{lower[2:]}"
    return lower


def _default_netmiko_get(router, interface_name):
    from netmiko import ConnectHandler

    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")

    device = {
        "device_type": "cisco_ios",
        "host": router,
        "username": user,
        "password": password,
        "timeout": 10,
    }
    with ConnectHandler(**device) as net_connect:
        try:
            ip_info = net_connect.send_command(
                f"show ip interface {interface_name}",
                use_textfsm=True,
            )
        except Exception:
            ip_info = []

        try:
            descriptions = net_connect.send_command(
                "show interfaces description",
                use_textfsm=True,
            )
        except Exception:
            descriptions = []

        if isinstance(ip_info, str):
            ip_info = []
        if isinstance(descriptions, str):
            descriptions = []
        return ip_info, descriptions


def _default_netmiko_delete(router, interface_name):
    state = get_interface_state(router, interface_name)
    if state.get("status") == "ok" and state.get("result") == "not_found":
        return "not_found"
    if state.get("status") == "error":
        err_res = state.get("result")
        if err_res == "authentication_failed":
            raise PermissionError("Authentication failed")
        if err_res == "connection_failed":
            raise ConnectionError("Connection failed")
        raise RuntimeError(f"Backend failed: {err_res}")

    from netmiko import ConnectHandler

    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")

    device = {
        "device_type": "cisco_ios",
        "host": router,
        "username": user,
        "password": password,
        "timeout": 10,
    }
    with ConnectHandler(**device) as net_connect:
        net_connect.send_config_set([f"no interface {interface_name}"])

    state_after = get_interface_state(router, interface_name)
    if state_after.get("status") == "ok" and state_after.get("result") == "not_found":
        return "deleted"
    raise RuntimeError(f"Interface {interface_name} still exists after deletion")


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    getter = netmiko_get or _default_netmiko_get
    try:
        ip_info, descriptions = getter(router, interface_name)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception as exc:
        exc_name = type(exc).__name__
        if "Authentication" in exc_name:
            return {"status": "error", "result": "authentication_failed"}
        if "Timeout" in exc_name or "Connection" in exc_name:
            return {"status": "error", "result": "connection_failed"}
        return {"status": "error", "result": "backend_failed"}

    norm_target = _normalize_name(interface_name)
    found_ip = None
    for item in ip_info:
        if _normalize_name(item.get("interface")) == norm_target:
            found_ip = item
            break

    if not found_ip:
        return {"status": "ok", "result": "not_found", "interface": None}

    link_status = str(found_ip.get("link_status", "")).lower()
    admin_state = "down" if "administratively down" in link_status else "up"

    ip_addrs = found_ip.get("ip_address", [])
    prefixes = found_ip.get("prefix_length", [])
    if ip_addrs and prefixes:
        ipv4 = f"{ip_addrs[0]}/{prefixes[0]}"
    else:
        ipv4 = None

    description = None
    for desc_item in descriptions:
        port = desc_item.get("port") or desc_item.get("interface")
        if _normalize_name(port) == norm_target:
            description = desc_item.get("description")
            break

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": interface_name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": admin_state,
        },
    }


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    deleter = netmiko_delete or _default_netmiko_delete
    try:
        del_result = deleter(router, interface_name)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception as exc:
        exc_name = type(exc).__name__
        if "Authentication" in exc_name:
            return {"status": "error", "result": "authentication_failed"}
        if "Timeout" in exc_name or "Connection" in exc_name:
            return {"status": "error", "result": "connection_failed"}
        return {"status": "error", "result": "backend_failed"}

    if del_result == "not_found":
        return {"status": "ok", "result": "not_found", "interface": None}
    if del_result == "deleted":
        return {"status": "ok", "result": "deleted"}

    return {"status": "error", "result": "backend_failed"}
