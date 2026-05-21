"""NL → harness-adapter.yaml translator.

Dispatches a structured prompt to an LLM engine and validates the
YAML response against :class:`AdapterConfig`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from harness.adapters.schema import AdapterConfig
from harness.engines.concrete import get_engine
from harness.engines.dispatcher import dispatch_packet
from harness.errors import DispatchExhausted, SchemaViolation

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "templates" / "_nl_to_yaml_prompt.md"


def _load_prompt_template() -> str:
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _map_engine(engine: str) -> str:
    """Map CLI engine label to canonical backend name."""
    mapping = {
        "swarm/kimi": "kimi",
        "swarm/kimi-api": "kimi",
    }
    if engine in mapping:
        return mapping[engine]
    if engine in ("deepseek", "kimi", "anthropic"):
        return engine
    raise ValueError(f"Unsupported engine: {engine}")


def _extract_adapter_yaml(text: str) -> str:
    """Extract YAML between ``<<<ADAPTER`` and ``ADAPTER>>>`` markers."""
    start = text.find("<<<ADAPTER")
    if start == -1:
        raise ValueError("Missing <<<ADAPTER marker")
    end = text.find("ADAPTER>>>", start)
    if end == -1:
        raise ValueError("Missing ADAPTER>>> marker")
    # Advance past the marker line
    first_nl = text.find("\n", start)
    if first_nl == -1 or first_nl >= end:
        raise ValueError("No YAML content between markers")
    return text[first_nl + 1 : end].strip()


def _build_prompt(description: str) -> str:
    template = _load_prompt_template()
    return f"{template}\n\n## Project Description\n\n{description}"


def _dispatch_via_packet(project: str, prompt: str, engine_name: str) -> str:
    """Write *prompt* to a temp file and dispatch via :func:`dispatch_packet`."""
    fd, path = tempfile.mkstemp(suffix=".md", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        result = dispatch_packet(
            project=project,
            packet_path=path,
            force_engine=engine_name,
        )
        if result.success:
            return result.text
        if result.error and result.error.startswith("adapter_load_failed"):
            # Bootstrap case: project has no adapter yet.
            return _dispatch_direct(prompt, engine_name)
        raise DispatchExhausted(
            f"Engine '{engine_name}' dispatch failed: {result.error}"
        )
    finally:
        os.unlink(path)


def _dispatch_direct(prompt: str, engine_name: str) -> str:
    """Direct engine dispatch (fallback when no project adapter exists)."""
    try:
        engine = get_engine(engine_name)
    except RuntimeError as exc:
        raise DispatchExhausted(
            f"Engine '{engine_name}' unavailable: {exc}"
        ) from exc
    response = engine.dispatch(prompt, "", {})
    if not response.success:
        raise DispatchExhausted(
            f"Engine '{engine_name}' dispatch failed: {response.error}"
        )
    return response.text


def generate_adapter_from_nl(
    project: str,
    description: str,
    engine: str = "swarm/kimi",
    max_retries: int = 1,
) -> AdapterConfig:
    """Generate an :class:`AdapterConfig` from a natural-language description.

    The function dispatches a structured prompt (based on
    ``_nl_to_yaml_prompt.md``) to the chosen engine. The engine must return
    YAML wrapped in ``<<<ADAPTER`` / ``ADAPTER>>>`` markers.

    If schema validation fails, the function retries up to *max_retries*
    times, feeding the validation error back into the prompt.

    Args:
        project: Project name (injected into the generated config as ``name``).
        description: Natural-language project description.
        engine: Engine selector. ``swarm/kimi`` maps to the Kimi backend.
        max_retries: Number of retry attempts on validation failure.

    Returns:
        Validated :class:`AdapterConfig`.

    Raises:
        ValueError: If *engine* is not supported.
        DispatchExhausted: If the engine fails to produce a response.
        SchemaViolation: If the response cannot be validated after all retries.
    """
    engine_name = _map_engine(engine)
    prompt = _build_prompt(description)

    last_error = ""
    for attempt in range(max_retries + 1):
        current_prompt = prompt
        if last_error:
            current_prompt += (
                f"\n\n## Previous Attempt Error\n\n"
                f"The previous draft failed validation with:\n\n"
                f"{last_error}\n\n"
                f"Please fix the errors and re-emit the YAML."
            )

        try:
            text = _dispatch_via_packet(project, current_prompt, engine_name)
            yaml_text = _extract_adapter_yaml(text)
        except ValueError as exc:
            last_error = f"Marker extraction failed: {exc}"
            continue

        try:
            data = yaml.safe_load(yaml_text)
            if data is None:
                raise ValueError("YAML is empty")
            cfg = AdapterConfig.model_validate(data)
            return cfg
        except Exception as exc:
            last_error = f"Validation failed: {exc}"
            continue

    raise SchemaViolation(
        f"Adapter validation failed after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )
