"""Part 4 student implementation."""

from pathlib import Path
import yaml

from app.core import validate_request
from app.dispatcher import dispatch_request
from app.request_handler import validate_webex_envelope


def process_request(mentioned_people, attachment_path, bot_person_id):
    """
    Validate webex envelope and attached YAML file,
    then dispatch to router if valid.
    """
    envelope_err = validate_webex_envelope(
        mentioned_people, attachment_path, bot_person_id
    )
    if envelope_err is not None:
        return envelope_err

    try:
        with open(attachment_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return {"status": "error", "result": "invalid_yaml"}

    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    validation_result = validate_request(data)
    if validation_result.get("status") == "error":
        return validation_result

    return dispatch_request(data)
