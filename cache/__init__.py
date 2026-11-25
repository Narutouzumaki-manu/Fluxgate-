"""Semantic cache for FluxGate (owner: Member 1).

Public surface: build_cache_engine(settings, db) -> CacheEngine.
"""

from cache.engine import build_cache_engine

__all__ = ["build_cache_engine"]
