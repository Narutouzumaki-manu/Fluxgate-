"""Base classes for all FluxGate contract models."""

from pydantic import BaseModel, ConfigDict


class FGModel(BaseModel):
    """FluxGate-internal contract model: unknown fields are rejected."""

    # protected_namespaces=() lets us use field names such as `model_served` / `model_id`
    # without Pydantic's "model_" namespace warning (older Pydantic 2.x versions).
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class FGOpenAIModel(BaseModel):
    """OpenAI-shaped model: unknown fields pass through so SDK/provider extras survive."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())
