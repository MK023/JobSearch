"""Anthropic API client using tool-use for schema-guaranteed JSON output.

All AI operations (analysis, cover letter, followup email, LinkedIn message)
use the Anthropic `tool_use` API with `tool_choice={"type": "tool", "name": ...}`
to force the model to emit a validated JSON payload matching a JSON Schema
derived from the corresponding Pydantic model.

This replaces the previous text-based pipeline (7 fragile JSON parsing
strategies + AI self-repair on parse failure) with a single, schema-driven call.
"""

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast

import anthropic
from pydantic import BaseModel

from ..config import settings
from ..preferences import get_preference
from ..prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SYSTEM_PROMPT,
    ANALYSIS_USER_PROMPT,
    COVER_LETTER_PROMPT_VERSION,
    COVER_LETTER_SYSTEM_PROMPT,
    COVER_LETTER_USER_PROMPT,
    FOLLOWUP_EMAIL_SYSTEM_PROMPT,
    FOLLOWUP_EMAIL_USER_PROMPT,
    LINKEDIN_MESSAGE_SYSTEM_PROMPT,
    LINKEDIN_MESSAGE_USER_PROMPT,
)
from .cache import CacheService
from .validation import (
    AnalysisAIResponse,
    CoverLetterAIResponse,
    FollowupEmailAIResponse,
    LinkedInMessageAIResponse,
    validate_analysis,
    validate_cover_letter,
    validate_followup_email,
    validate_linkedin_message,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session  # noqa: F401 — used in forward-ref type hint

logger = logging.getLogger(__name__)

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
}

PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

CACHE_TTL = 86400  # 24 hours

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Get or create the singleton Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=120.0,
            max_retries=3,
        )
    return _client


def content_hash(cv_text: str, job_description: str) -> str:
    """SHA-256 hash of CV + job description for duplicate detection."""
    content = f"{cv_text}:{job_description}"
    return hashlib.sha256(content.encode()).hexdigest()


def _calculate_cost(usage: anthropic.types.Usage, model_id: str) -> float:
    """Calculate USD cost from token usage and model pricing.

    Accounts for prompt caching: cache reads are 90% cheaper,
    cache writes cost 25% more than base input price.
    """
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    base_input_rate = pricing["input"]

    # Cached tokens from usage (0 if not present).
    # Use isinstance check because MagicMock auto-generates attributes
    # instead of returning the getattr default.
    _cr = getattr(usage, "cache_read_input_tokens", 0)
    cache_read = _cr if isinstance(_cr, int) else 0
    _cc = getattr(usage, "cache_creation_input_tokens", 0)
    cache_create = _cc if isinstance(_cc, int) else 0

    # Non-cached input tokens (input_tokens includes all input)
    regular_input = usage.input_tokens - cache_read - cache_create

    input_cost = (regular_input / 1_000_000) * base_input_rate
    cache_read_cost = (cache_read / 1_000_000) * base_input_rate * 0.1
    cache_create_cost = (cache_create / 1_000_000) * base_input_rate * 1.25
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]

    if cache_read > 0:
        logger.debug(
            "Prompt cache hit: %d tokens read from cache (saved ~%.6f USD)",
            cache_read,
            (cache_read / 1_000_000) * base_input_rate * 0.9,
        )

    return round(input_cost + cache_read_cost + cache_create_cost + output_cost, 6)


# ── Tool-use plumbing ──────────────────────────────────────────────────


def _schema_from_model(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Produce a JSON Schema from a Pydantic model suitable for Anthropic tool input_schema.

    Pydantic's ``model_json_schema()`` returns a JSON-Schema-compatible dict.
    We strip the top-level ``title`` (Anthropic doesn't need it) and leave the rest
    (including any ``$defs`` references) untouched.
    """
    schema = model_cls.model_json_schema()
    schema.pop("title", None)
    return schema


# Pre-compute schemas at import time — they never change at runtime.
_ANALYSIS_SCHEMA = _schema_from_model(AnalysisAIResponse)
_COVER_LETTER_SCHEMA = _schema_from_model(CoverLetterAIResponse)
_FOLLOWUP_SCHEMA = _schema_from_model(FollowupEmailAIResponse)
_LINKEDIN_SCHEMA = _schema_from_model(LinkedInMessageAIResponse)


def _call_api_with_tool(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
) -> tuple[dict[str, Any], anthropic.types.Usage]:
    """Call Claude forcing a single tool invocation — schema-validated JSON output.

    Returns (parsed_input, usage). The parsed_input is the dict Claude passed
    to the forced tool; Anthropic's SDK already parses it from JSON, so there's
    zero local parsing. If no ``tool_use`` block is returned (should never
    happen with forced tool_choice), raises RuntimeError.
    """
    client = get_client()
    message = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": input_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    for block in message.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        tool_input = getattr(block, "input", None)
        # SDK parses tool input from JSON to dict automatically.
        if isinstance(tool_input, dict):
            return cast(dict[str, Any], tool_input), message.usage

    raise RuntimeError(
        f"Expected tool_use block for {tool_name!r} but got content types: "
        f"{[getattr(b, 'type', '?') for b in message.content]}"
    )


# ── Public AI operations ───────────────────────────────────────────────


def analyze_job(
    cv_text: str,
    job_description: str,
    model: str = "haiku",
    cache: CacheService | None = None,
    db: "Session | None" = None,
) -> dict[str, Any]:
    """Analyze CV-to-job compatibility.

    When the persisted preference `ai_sonnet_fallback_on_low_confidence` is
    True and the first pass on Haiku returns confidence=="bassa", a second
    pass is automatically run on Sonnet and replaces the result. Costs/tokens
    are summed across both passes; result["fallback_used"]=True flags the
    override.

    `db` is optional — if omitted (e.g. from a cached/background context with
    no session), the fallback is disabled (safe default, no crash).
    """
    model_id = MODELS.get(model, MODELS["haiku"])
    ch = content_hash(cv_text, job_description)
    cache_key = f"analysis:{ANALYSIS_PROMPT_VERSION}:{model}:{ch[:16]}"

    if cache:
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            cached["content_hash"] = ch
            return cached

    user_prompt = ANALYSIS_USER_PROMPT.format(cv_text=cv_text[:12000], job_description=job_description)
    result, usage = _call_api_with_tool(
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        model_id,
        8192,
        tool_name="submit_analysis",
        tool_description="Emit the complete CV-vs-job analysis payload.",
        input_schema=_ANALYSIS_SCHEMA,
    )

    result = validate_analysis(result)

    tokens_in = usage.input_tokens
    tokens_out = usage.output_tokens
    cost = _calculate_cost(usage, model_id)
    used_model_id = model_id
    fallback_used = False

    # Optional fallback: low confidence on a non-Sonnet model triggers a Sonnet retry.
    fallback_enabled = False
    if db is not None:
        fallback_enabled = bool(get_preference(db, "ai_sonnet_fallback_on_low_confidence", default=False))
    sonnet_id = MODELS["sonnet"]
    if fallback_enabled and result.get("confidence") == "bassa" and model_id != sonnet_id:
        logger.info(
            "Low-confidence analysis on %s, retrying on Sonnet (reason: %s)",
            model_id,
            result.get("confidence_reason", ""),
        )
        sonnet_result, sonnet_usage = _call_api_with_tool(
            ANALYSIS_SYSTEM_PROMPT,
            user_prompt,
            sonnet_id,
            8192,
            tool_name="submit_analysis",
            tool_description="Emit the complete CV-vs-job analysis payload.",
            input_schema=_ANALYSIS_SCHEMA,
        )
        sonnet_result = validate_analysis(sonnet_result)
        # Sonnet result wins; tokens/cost are cumulative across both passes.
        result = sonnet_result
        tokens_in += sonnet_usage.input_tokens
        tokens_out += sonnet_usage.output_tokens
        cost += _calculate_cost(sonnet_usage, sonnet_id)
        used_model_id = sonnet_id
        fallback_used = True

    result["model_used"] = used_model_id
    result["fallback_used"] = fallback_used
    result["full_response"] = ""  # Don't cache full response in Redis
    result["from_cache"] = False
    result["content_hash"] = ch
    result["tokens"] = {
        "input": tokens_in,
        "output": tokens_out,
        "total": tokens_in + tokens_out,
    }
    result["cost_usd"] = cost

    if cache:
        cache_data = {k: v for k, v in result.items() if k != "from_cache"}
        cache.set_json(cache_key, cache_data, CACHE_TTL)

    return result


def generate_cover_letter(
    cv_text: str,
    job_description: str,
    analysis_data: dict[str, Any],
    language: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict[str, Any]:
    """Generate a cover letter based on CV, job description, and analysis."""
    model_id = MODELS.get(model, MODELS["haiku"])

    if cache:
        ch = content_hash(cv_text, job_description)
        cl_content = f"cl:{COVER_LETTER_PROMPT_VERSION}:{model}:{ch[:16]}:{language}"
        cache_key = f"coverletter:{hashlib.sha256(cl_content.encode()).hexdigest()[:16]}"
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached
    else:
        cache_key = None

    strengths_text = ", ".join(
        s if isinstance(s, str) else s.get("skill", str(s)) for s in analysis_data.get("strengths", [])[:5]
    )
    gaps_list = analysis_data.get("gaps", [])
    gaps_text = ", ".join(g.get("gap", g) if isinstance(g, dict) else str(g) for g in gaps_list[:5])

    user_prompt = COVER_LETTER_USER_PROMPT.format(
        cv_text=cv_text[:8000],
        job_description=job_description,
        role=analysis_data.get("role", ""),
        company=analysis_data.get("company", ""),
        score=analysis_data.get("score", 0),
        strengths=strengths_text,
        gaps=gaps_text,
        language=language,
    )

    result, usage = _call_api_with_tool(
        COVER_LETTER_SYSTEM_PROMPT,
        user_prompt,
        model_id,
        2048,
        tool_name="submit_cover_letter",
        tool_description="Emit the cover letter and subject line options.",
        input_schema=_COVER_LETTER_SCHEMA,
    )

    result = validate_cover_letter(result)

    result["model_used"] = model_id
    result["from_cache"] = False
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)

    if cache and cache_key:
        cache_data = {k: v for k, v in result.items() if k != "from_cache"}
        cache.set_json(cache_key, cache_data, CACHE_TTL)

    return result


def generate_followup_email(
    cv_text: str,
    role: str,
    company: str,
    days_since: int,
    language: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict[str, Any]:
    """Generate a follow-up email after application."""
    model_id = MODELS.get(model, MODELS["haiku"])

    if cache:
        raw = f"followup:{model}:{role}:{company}:{days_since}:{language}"
        cache_key = f"followup:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached
    else:
        cache_key = None

    cv_summary = cv_text[:1500]

    user_prompt = FOLLOWUP_EMAIL_USER_PROMPT.format(
        cv_summary=cv_summary,
        role=role,
        company=company,
        days_since_application=days_since,
        language=language,
    )

    result, usage = _call_api_with_tool(
        FOLLOWUP_EMAIL_SYSTEM_PROMPT,
        user_prompt,
        model_id,
        1024,
        tool_name="submit_followup_email",
        tool_description="Emit the follow-up email subject, body, and tone notes.",
        input_schema=_FOLLOWUP_SCHEMA,
    )

    result = validate_followup_email(result)

    result["model_used"] = model_id
    result["from_cache"] = False
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)

    if cache and cache_key:
        cache_data = {k: v for k, v in result.items() if k != "from_cache"}
        cache.set_json(cache_key, cache_data, CACHE_TTL)

    return result


def generate_linkedin_message(
    cv_text: str,
    role: str,
    company: str,
    contact_info: str,
    language: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict[str, Any]:
    """Generate a LinkedIn connection message."""
    model_id = MODELS.get(model, MODELS["haiku"])

    if cache:
        raw = f"linkedin:{model}:{role}:{company}:{contact_info}:{language}"
        cache_key = f"linkedin:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached
    else:
        cache_key = None

    cv_summary = cv_text[:1500]

    user_prompt = LINKEDIN_MESSAGE_USER_PROMPT.format(
        cv_summary=cv_summary,
        role=role,
        company=company,
        contact_info=contact_info or "Not available",
        language=language,
    )

    result, usage = _call_api_with_tool(
        LINKEDIN_MESSAGE_SYSTEM_PROMPT,
        user_prompt,
        model_id,
        1024,
        tool_name="submit_linkedin_message",
        tool_description="Emit the LinkedIn message, connection note, and approach tip.",
        input_schema=_LINKEDIN_SCHEMA,
    )

    result = validate_linkedin_message(result)

    result["model_used"] = model_id
    result["from_cache"] = False
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)

    if cache and cache_key:
        cache_data = {k: v for k, v in result.items() if k != "from_cache"}
        cache.set_json(cache_key, cache_data, CACHE_TTL)

    return result
