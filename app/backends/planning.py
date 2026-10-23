from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    status_response = get_interface_state(router, desired_interface["name"])
    if status_response.get("status") == "error":
        return status_response

    result_type = status_response.get("result")
    if result_type == "found":
        current_interface = status_response.get("interface")
    else:
        current_interface = None

    return build_plan(desired_interface, current_interface)
