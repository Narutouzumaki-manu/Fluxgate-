"""Base error types shared by all modules."""


class FluxGateError(Exception):
    """Root of all FluxGate-specific errors."""


class ConfigError(FluxGateError):
    """Invalid or missing configuration (settings, policy files)."""


class MigrationError(FluxGateError):
    """A database migration failed or was tampered with."""
