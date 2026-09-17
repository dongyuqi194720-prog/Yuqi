from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeveloperAction:
    action: str
    arguments: dict[str, str]


class ProtocolError(ValueError):
    pass


def parse_action(text: str) -> DeveloperAction:
    """Parse the small plain-text protocol emitted by GPT."""
    raw = text.strip()
    if not raw:
        raise ProtocolError("empty GPT response")

    lines = raw.splitlines()
    action = ""
    fields: dict[str, str] = {}
    current_key: str | None = None
    content_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("ACTION:"):
            action = stripped.split(":", 1)[1].strip().upper()
            current_key = None
            continue

        if stripped.startswith("PATH:"):
            fields["path"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("COMMAND:"):
            fields["command"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("TERMS:"):
            fields["terms"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("WINDOW_ID:"):
            fields["window_id"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("TEXT:"):
            fields["text"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("TIMEOUT:"):
            fields["timeout"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("INPUT_ANCHOR:"):
            fields["input_anchor"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if stripped.startswith("CONTENT:"):
            current_key = "content"
            content_lines = []
            fields["content"] = ""
            continue

        if stripped.startswith("REASON:"):
            fields["reason"] = stripped.split(":", 1)[1].strip()
            current_key = None
            continue

        if current_key == "content":
            content_lines.append(line)

    if current_key == "content":
        fields["content"] = "\n".join(content_lines).rstrip() + (
            "\n" if content_lines else ""
        )

    if not action:
        raise ProtocolError("missing ACTION")

    allowed = {
        "LIST_FILES",
        "READ_FILE",
        "WRITE_FILE",
        "DELETE_FILE",
        "RUN_COMMAND",
        "OBSERVE_GUI",
        "OBSERVE_DESKTOP",
        "FIND_WINDOW",
        "WAIT_FOR_WINDOW",
        "LAUNCH_APP",
        "ACTIVATE_WINDOW",
        "CLICK_TEXT",
        "TYPE_TEXT",
        "DONE",
    }
    if action not in allowed:
        raise ProtocolError(f"unknown ACTION: {action}")

    required = {
        "READ_FILE": ("path",),
        "WRITE_FILE": ("path", "content"),
        "DELETE_FILE": ("path",),
        "RUN_COMMAND": ("command",),
        "FIND_WINDOW": ("terms",),
        "WAIT_FOR_WINDOW": ("terms",),
        "LAUNCH_APP": ("terms",),
        "ACTIVATE_WINDOW": ("window_id",),
        "CLICK_TEXT": ("text",),
        "TYPE_TEXT": ("text",),
    }

    for key in required.get(action, ()):
        if key not in fields:
            raise ProtocolError(f"{action} requires {key}")

    return DeveloperAction(action=action, arguments=fields)
