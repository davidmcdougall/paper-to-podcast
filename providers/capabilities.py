"""Structural interfaces for the two supported capabilities."""
from pathlib import Path
from typing import Any, Protocol


class TextProvider(Protocol):
    input_unit: str
    input_limit: int
    prompt_character_limit: int

    def count_tokens(self, **request: Any) -> Any: ...
    def complete(self, **request: Any) -> Any: ...
    def list_models(self) -> list[str]: ...
    def retrieve_model(self, model: str) -> Any: ...


class SpeechProvider(Protocol):
    input_unit: str
    input_limits: dict[str, int]
    audio_formats: tuple[str, ...]

    def list_voices(self) -> list[Any]: ...
    def synthesize(self, script: str, voice_id: str, model_id: str, directory: Path) -> Path: ...
