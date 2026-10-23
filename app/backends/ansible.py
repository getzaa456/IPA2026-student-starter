from ipaddress import IPv4Interface
import json
import os
from pathlib import Path
import subprocess


def _default_run_playbook(variables):
    repo_root = Path(__file__).resolve().parents[2]
    playbook = repo_root / "ansible" / "apply_interface.yml"
    inventory = repo_root / "ansible" / "inventory.ini"

    extra_vars = json.dumps(variables)
    env = os.environ.copy()

    cmd = [
        "ansible-playbook",
        "-i",
        str(inventory),
        str(playbook),
        "-e",
        extra_vars,
    ]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        output = proc.stdout + proc.stderr
        if "Authentication failure" in output or "Permission denied" in output:
            raise PermissionError("Ansible authentication failed")
        if "UNREACHABLE" in output or "timed out" in output:
            raise ConnectionError("Ansible connection failed")
        raise RuntimeError(f"Ansible failed: {output}")


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    runner = run_playbook or _default_run_playbook

    ipv4 = IPv4Interface(desired_interface["ipv4"])
    variables = {
        "router": router,
        "interface_name": desired_interface["name"],
        "description": desired_interface["description"],
        "ipv4_address": str(ipv4.ip),
        "netmask": str(ipv4.network.netmask),
        "shutdown": desired_interface.get("admin_state") == "down",
    }

    try:
        runner(variables)
        return {"status": "ok", "result": "applied"}
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}
