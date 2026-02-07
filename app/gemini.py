from __future__ import annotations

from typing import Iterable, List, Optional, Dict

import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig

from .config import get_settings


settings = get_settings()
vertexai.init(project=settings.project_id, location=settings.location)


def _messages_to_parts(messages: List[dict]) -> List[Part]:
    parts: List[Part] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        # Gemini SDK expects plain text; richer parts can be added later.
        parts.append(Part.from_text(f"{role}: {content}"))
    return parts


def generate_stream(
    messages: List[dict],
    model_id: str,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
):
    model = GenerativeModel(model_id)
    parts = _messages_to_parts(messages)
    gen_cfg: Dict = {}
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    if top_p is not None:
        gen_cfg["top_p"] = top_p
    if top_k is not None:
        gen_cfg["top_k"] = top_k
    cfg = GenerationConfig(**gen_cfg) if gen_cfg else None
    return model.generate_content(parts, stream=True, generation_config=cfg)
