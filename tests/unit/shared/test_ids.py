from shared.ids import new_request_id, new_ulid

_CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_ulid_shape() -> None:
    value = new_ulid()
    assert len(value) == 26
    assert set(value) <= _CROCKFORD


def test_request_id_prefix_and_uniqueness() -> None:
    ids = {new_request_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(i.startswith("req_") and len(i) == 30 for i in ids)
