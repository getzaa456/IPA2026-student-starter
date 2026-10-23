from ipaddress import IPv4Interface
import os
import xml.etree.ElementTree as ET

from app.backends.planning import plan_interface as planning_plan_interface

NETCONF_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"
IETF_IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"


def _default_netconf_get_config(router, filter_xml):
    from ncclient import manager

    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")

    with manager.connect(
        host=router,
        port=830,
        username=user,
        password=password,
        hostkey_verify=False,
        device_params={"name": "iosxe"},
        timeout=10,
    ) as m:
        return m.get_config(source="running", filter=("subtree", filter_xml)).data_xml


def _default_netconf_edit_config(router, config_xml):
    from ncclient import manager

    user = os.environ.get("ROUTER_USER", "")
    password = os.environ.get("ROUTER_PASS", "")

    with manager.connect(
        host=router,
        port=830,
        username=user,
        password=password,
        hostkey_verify=False,
        device_params={"name": "iosxe"},
        timeout=10,
    ) as m:
        m.edit_config(target="running", config=config_xml)


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    getter = netconf_get_config or _default_netconf_get_config
    filter_xml = (
        f'<interfaces xmlns="{IETF_IF_NS}">'
        f"<interface><name>{interface_name}</name></interface>"
        f"</interfaces>"
    )

    try:
        xml_text = getter(router, filter_xml)
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception as exc:
        exc_name = type(exc).__name__
        if "Authentication" in exc_name:
            return {"status": "error", "result": "authentication_failed"}
        if "SSH" in exc_name or "Connection" in exc_name or "Timeout" in exc_name:
            return {"status": "error", "result": "connection_failed"}
        return {"status": "error", "result": "backend_failed"}

    try:
        root = ET.fromstring(xml_text)
        found_iface = None
        for iface in root.iter():
            if iface.tag.endswith("interface"):
                for child in iface:
                    if child.tag.endswith("name") and child.text == interface_name:
                        found_iface = iface
                        break
            if found_iface is not None:
                break

        if found_iface is None:
            return {"status": "ok", "result": "not_found", "interface": None}

        name = interface_name
        description = None
        enabled = True
        ipv4_str = None

        for child in found_iface:
            tag = child.tag
            if tag.endswith("description"):
                description = child.text
            elif tag.endswith("enabled"):
                enabled = child.text.strip().lower() == "true"
            elif tag.endswith("ipv4"):
                for ip_elem in child.iter():
                    if ip_elem.tag.endswith("address"):
                        ip_val = None
                        netmask_val = None
                        for addr_child in ip_elem:
                            if addr_child.tag.endswith("ip"):
                                ip_val = addr_child.text
                            elif addr_child.tag.endswith("netmask"):
                                netmask_val = addr_child.text
                        if ip_val and netmask_val:
                            ipv4_str = str(IPv4Interface(f"{ip_val}/{netmask_val}"))
                            break

        admin_state = "up" if enabled else "down"

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": name,
                "ipv4": ipv4_str,
                "description": description,
                "admin_state": admin_state,
            },
        }
    except Exception:
        return {"status": "error", "result": "backend_failed"}


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return planning_plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config=netconf_get_config),
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    editor = netconf_edit_config or _default_netconf_edit_config

    number = desired_interface["name"][len("Loopback"):].strip()
    ipv4 = IPv4Interface(desired_interface["ipv4"])
    address = str(ipv4.ip)
    mask = str(ipv4.network.netmask)
    description = desired_interface["description"]

    shutdown_xml = "\n            <shutdown/>" if desired_interface.get("admin_state") == "down" else ""

    config_xml = f"""<config xmlns="{NETCONF_NS}" xmlns:nc="{NETCONF_NS}">
  <native xmlns="{NATIVE_NS}">
    <interface>
      <Loopback nc:operation="replace">
        <name>{number}</name>
        <description>{description}</description>
        <ip>
          <address>
            <primary>
              <address>{address}</address>
              <mask>{mask}</mask>
            </primary>
          </address>
        </ip>{shutdown_xml}
      </Loopback>
    </interface>
  </native>
</config>"""

    try:
        editor(router, config_xml)
        return {"status": "ok", "result": "applied"}
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception as exc:
        exc_name = type(exc).__name__
        if "Authentication" in exc_name:
            return {"status": "error", "result": "authentication_failed"}
        if "SSH" in exc_name or "Connection" in exc_name or "Timeout" in exc_name:
            return {"status": "error", "result": "connection_failed"}
        return {"status": "error", "result": "backend_failed"}
