from shared.contracts.protocols import CacheEngine, GuardrailEngine, Router
from tests.fakes import FakeCacheEngine, FakeGuardrailEngine, FakeRouter


def test_fakes_satisfy_the_protocols() -> None:
    assert isinstance(FakeGuardrailEngine(), GuardrailEngine)
    assert isinstance(FakeCacheEngine(), CacheEngine)
    assert isinstance(FakeRouter(), Router)
