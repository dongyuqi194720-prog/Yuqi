"""Independent GUI safety state for one-shot ChatGPT send authorization."""

from threading import Lock


_lock = Lock()
_send_authorized = False
_authorized_marker = None


def authorize_send(marker):
    """Authorize exactly one send with the complete marker."""
    marker = str(marker)
    if not marker:
        raise ValueError("empty send marker")

    global _send_authorized
    global _authorized_marker

    with _lock:
        _authorized_marker = marker
        _send_authorized = True


def consume_send_authorization(marker):
    """Consume the one-shot authorization only if the marker matches."""
    marker = str(marker)

    global _send_authorized
    global _authorized_marker

    with _lock:
        if not _send_authorized:
            return False

        if _authorized_marker != marker:
            return False

        _send_authorized = False
        _authorized_marker = None
        return True


def clear_send_authorization():
    """Fail-closed reset."""
    global _send_authorized
    global _authorized_marker

    with _lock:
        _send_authorized = False
        _authorized_marker = None


def is_send_authorized(marker):
    """Read-only check; does not consume authorization."""
    marker = str(marker)

    with _lock:
        return (
            _send_authorized
            and _authorized_marker == marker
        )
