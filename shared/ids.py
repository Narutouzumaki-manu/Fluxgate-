"""ID helpers. ULIDs are sortable by creation time and safe to log."""

from ulid import ULID


def new_ulid() -> str:
    return str(ULID())


def new_request_id() -> str:
    """'req_' + ULID, e.g. req_01J8Z..."""
    return f"req_{new_ulid()}"
