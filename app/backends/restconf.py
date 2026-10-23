from ipaddress import IPv4Interface
import os
import requests
import urllib3

from app.backends.planning import plan_interface as planning_plan_interface

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _default_http_get(url):
    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")
    headers = {"Accept": "application/yang-data+json"}
    return requests.get(
        url,
        auth=(user, password),
        headers=headers,
        verify=False,
        timeout=10,
    )


def _default_http_put(url, json):
    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")
    headers = {
        "Content-Type": "application/yang-data+json",
        "Accept": "application/yang-data+json",
    }
    return requests.put(
        url,
        auth=(user, password),
        headers=headers,
        json=json,
        verify=False,
        timeout=10,
    )


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    getter = http_get or _default_http_get
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )

    try:
        response = getter(url)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except (ConnectionError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    if response.status_code == 404:
        return {"status": "ok", "result": "not_found", "interface": None}
    if response.status_code in (401, 403):
        return {"status": "error", "result": "authentication_failed"}
    if response.status_code >= 400:
        return {"status": "error", "result": "backend_failed"}

    try:
        data = response.json()
        if not data:
            return {"status": "ok", "result": "not_found", "interface": None}

        iface_data = data.get("ietf-interfaces:interface")
        if not iface_data:
            return {"status": "ok", "result": "not_found", "interface": None}

        name = iface_data.get("name")
        description = iface_data.get("description")
        enabled = iface_data.get("enabled", True)
        admin_state = "up" if enabled else "down"

        ipv4_section = iface_data.get("ietf-ip:ipv4", {})
        addresses = ipv4_section.get("address", [])
        if addresses:
            addr = addresses[0]
            ip = addr.get("ip")
            netmask = addr.get("netmask")
            prefix = addr.get("prefix-length")
            if prefix is not None:
                ipv4 = f"{ip}/{prefix}"
            elif netmask:
                ipv4 = str(IPv4Interface(f"{ip}/{netmask}"))
            else:
                ipv4 = ip
        else:
            ipv4 = None

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": name,
                "ipv4": ipv4,
                "description": description,
                "admin_state": admin_state,
            },
        }
    except Exception:
        return {"status": "error", "result": "backend_failed"}


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return planning_plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get=http_get),
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    putter = http_put or _default_http_put

    name = desired_interface["name"]
    number = int(name[len("Loopback"):])
    url = (
        f"https://{router}/restconf/data/"
        f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
    )

    ipv4 = IPv4Interface(desired_interface["ipv4"])
    payload = {
        "Cisco-IOS-XE-native:Loopback": {
            "name": number,
            "description": desired_interface["description"],
            "ip": {
                "address": {
                    "primary": {
                        "address": str(ipv4.ip),
                        "mask": str(ipv4.network.netmask),
                    }
                }
            },
        }
    }

    if desired_interface.get("admin_state") == "down":
        payload["Cisco-IOS-XE-native:Loopback"]["shutdown"] = [None]

    try:
        response = putter(url, json=payload)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except (ConnectionError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    if response.status_code in (200, 201, 204):
        return {"status": "ok", "result": "applied"}
    if response.status_code in (401, 403):
        return {"status": "error", "result": "authentication_failed"}

    return {"status": "error", "result": "backend_failed"}
