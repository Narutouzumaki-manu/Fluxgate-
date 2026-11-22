"""OpenAI-shaped request/response models (Blueprint section 10.2)."""

from typing import Any, Literal

from pydantic import Field

from .base import FGModel, FGOpenAIModel


class ChatMessage(FGOpenAIModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class RetrievedChunk(FGModel):
    chunk_id: str = Field(max_length=128)
    text: str = Field(max_length=32_000)
    source: str | None = Field(default=None, max_length=512)  # e.g. filename#page


class FluxGateOptions(FGModel):
    """Optional extension (body field `fluxgate`). Never required.

    Stripped by the gateway before the provider call; retained in the *sanitized* request
    inside FluxGate so the cache can use `semantic_query`, `context_fingerprint`, `cache_scope`.
    """

    cache: Literal["auto", "bypass", "exact_only"] = "auto"
    semantic_query: str | None = Field(default=None, max_length=2_000)
    context_fingerprint: str | None = Field(default=None, max_length=128)
    cache_scope: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    retrieved_context: list[RetrievedChunk] | None = None
    guardrail_policy: str | None = Field(default=None, max_length=64)


class ChatCompletionRequest(FGOpenAIModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    n: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stop: str | list[str] | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    stream_options: dict[str, Any] | None = None
    user: str | None = None
    fluxgate: FluxGateOptions | None = None


class ChatCompletionUsage(FGOpenAIModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(FGOpenAIModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletionResponse(FGOpenAIModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None = None
    system_fingerprint: str | None = None


class ChatCompletionChunkDelta(FGOpenAIModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionChunkChoice(FGOpenAIModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(FGOpenAIModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    usage: ChatCompletionUsage | None = None
