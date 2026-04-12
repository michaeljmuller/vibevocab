"""
LLM abstraction for vocabulary card assistance.

Supported providers (set via LLM_PROVIDER env var):
  openai-compatible — OpenAI or any OpenAI-compatible endpoint (Groq, Together, Ollama, …)
  anthropic         — Anthropic Claude

Relevant env vars:
  LLM_PROVIDER              openai-compatible | anthropic  (default: openai-compatible)
  LLM_API_KEY               API key for the provider       (not required for local Ollama)
  LLM_MODEL                 model name                     (default: gpt-4o-mini)
  LLM_BASE_URL              override base URL              (e.g. http://ollama:11434/v1)
  SUGGESTION_COUNT          number of suggestions          (default: 3)
  LLM_SUGGESTION_PROMPT     path to prompt template for sentence suggestions
  LLM_TRANSLATION_PROMPT    path to prompt template for example translation
"""

import os
from string import Template
from pydantic import BaseModel


class SentencePair(BaseModel):
    source: str
    target: str


class _Suggestions(BaseModel):
    pairs: list[SentencePair]


class TranslationResult(BaseModel):
    translation: str | None
    problem:     str | None


def _make_client():
    """Return (provider_name, instructor_client)."""
    import instructor

    provider = os.environ.get('LLM_PROVIDER', 'openai-compatible').lower()
    api_key  = os.environ.get('LLM_API_KEY', '')
    base_url = os.environ.get('LLM_BASE_URL') or None

    if provider == 'anthropic':
        from anthropic import Anthropic
        return provider, instructor.from_anthropic(Anthropic(api_key=api_key))

    # openai-compatible: OpenAI or any OpenAI-compatible endpoint
    from openai import OpenAI
    kwargs = {'api_key': api_key or 'dummy'}
    if base_url:
        kwargs['base_url'] = base_url
    return provider, instructor.from_openai(OpenAI(**kwargs))


def suggest_sentence_pairs(
    source_expression: str,
    target_expression: str,
    part_of_speech: str | None,
    notes: str | None,
    source_language: str,
    target_language: str,
    count: int,
) -> list[SentencePair]:
    """Return `count` sentence pairs (source + target) illustrating the expression."""
    provider, client = _make_client()
    model    = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
    prompt_file = os.environ.get('LLM_SUGGESTION_PROMPT')
    if not prompt_file:
        raise RuntimeError('LLM_SUGGESTION_PROMPT is not set')
    template = Template(open(prompt_file).read())

    pos_hint   = f' ({part_of_speech})' if part_of_speech else ''
    notes_hint = f'\n\nNotes: {notes}' if notes else ''
    prompt     = template.substitute(
        count=count,
        source_language=source_language,
        target_language=target_language,
        source_expression=source_expression,
        target_expression=target_expression,
        pos_hint=pos_hint,
        notes_hint=notes_hint,
    )

    shared = dict(
        model=model,
        response_model=_Suggestions,
        messages=[{'role': 'user', 'content': prompt}],
    )

    if provider == 'anthropic':
        result = client.messages.create(max_tokens=1024, **shared)
    else:
        result = client.chat.completions.create(**shared)

    return result.pairs


def translate_example(
    source_expression: str,
    target_expression: str,
    source_example: str,
    part_of_speech: str | None,
    notes: str | None,
    source_language: str,
    target_language: str,
) -> TranslationResult:
    """Translate `source_example` into `target_language`, or flag a problem."""
    provider, client = _make_client()
    model       = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
    prompt_file = os.environ.get('LLM_TRANSLATION_PROMPT')
    if not prompt_file:
        raise RuntimeError('LLM_TRANSLATION_PROMPT is not set')
    template = Template(open(prompt_file).read())

    pos_hint   = f' ({part_of_speech})' if part_of_speech else ''
    notes_hint = f'\n\nNotes: {notes}' if notes else ''
    prompt     = template.substitute(
        source_expression=source_expression,
        target_expression=target_expression,
        source_example=source_example,
        source_language=source_language,
        target_language=target_language,
        pos_hint=pos_hint,
        notes_hint=notes_hint,
    )

    shared = dict(
        model=model,
        response_model=TranslationResult,
        messages=[{'role': 'user', 'content': prompt}],
    )

    if provider == 'anthropic':
        result = client.messages.create(max_tokens=1024, **shared)
    else:
        result = client.chat.completions.create(**shared)

    return result
