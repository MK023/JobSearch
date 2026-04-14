"""Anthropic API client with JSON parsing, retry logic, and cost tracking.

Provides a singleton client and functions for all AI operations:
analysis, cover letter, follow-up email, LinkedIn message.
"""

import hashlib
import json
import logging
import re
from typing import Any, cast

import anthropic

from ..config import settings
from ..prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SYSTEM_PROMPT,
    ANALYSIS_USER_PROMPT,
    COVER_LETTER_SYSTEM_PROMPT,
    COVER_LETTER_USER_PROMPT,
    FOLLOWUP_EMAIL_SYSTEM_PROMPT,
    FOLLOWUP_EMAIL_USER_PROMPT,
    LINKEDIN_MESSAGE_SYSTEM_PROMPT,
    LINKEDIN_MESSAGE_USER_PROMPT,
)
from .cache import CacheService
from .validation import validate_analysis, validate_cover_letter, validate_followup_email, validate_linkedin_message

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


def _clean_json_text(text: str) -> str:
    """Fix common LLM JSON output issues."""
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Remove single-line comments
    text = re.sub(r"//[^\n]*", "", text)
    # Add missing commas between adjacent objects/arrays
    text = re.sub(r'([}\]])\s*\n\s*(["{[\[])', r"\1,\n\2", text)
    # Fix broken string concatenation across lines
    text = re.sub(r'"\s*\n\s*"(?=[^:]*":)', '",\n"', text)
    # Replace NaN/Infinity (not valid JSON) with null
    text = re.sub(r"\bNaN\b", "null", text)
    text = re.sub(r"\bInfinity\b", "null", text)
    text = re.sub(r"\b-Infinity\b", "null", text)
    return text


def _fix_unescaped_newlines(text: str) -> str:
    """Fix unescaped newlines inside JSON string values.

    This is the #1 cause of JSON parse errors from LLMs - they produce
    actual newline characters inside string values instead of \\n.
    """
    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
        if ch == "\\":
            escape_next = True
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if in_string and ch == "\n":
            result.append("\\n")
            i += 1
            continue
        if in_string and ch == "\r":
            # Skip \r (handle \r\n as just \n)
            if i + 1 < len(text) and text[i + 1] == "\n":
                result.append("\\n")
                i += 2
            else:
                result.append("\\n")
                i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _fix_single_quotes(text: str) -> str:
    """Convert Python-style single-quoted JSON to double-quoted JSON.

    Handles: {'key': 'value', 'flag': True}  ->  {"key": "value", "flag": true}
    """
    # Only attempt if it looks like single-quoted JSON (starts with {' or [')
    stripped = text.strip()
    if not (stripped.startswith("{'") or stripped.startswith("['")):
        return text
    # Replace single quotes used as JSON delimiters (not inside strings)
    text = re.sub(r"(?<=[\[{,:])\s*'", ' "', text)
    text = re.sub(r"'\s*(?=[\]}:,])", '"', text)
    # Fix Python booleans/None
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    return text


def _strip_markdown_wrapper(text: str) -> str:
    """Remove markdown code block wrappers (```json ... ``` or ``` ... ```).

    Handles unclosed fences gracefully: if the response was truncated and the
    closing ``` is missing, still strip the opening fence so the caller can
    attempt JSON parse on the partial payload.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    # Remove opening line (```json or ```)
    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    # Remove closing ``` if present
    if "```" in text:
        text = text.rsplit("```", 1)[0]
    else:
        logger.warning("Markdown fence opened but not closed — response likely truncated")
    return text.strip()


def _extract_and_parse_json(raw_text: str) -> dict[str, Any]:
    """Extract JSON from AI response, with multiple fallback strategies.

    Strategy order (from cheapest to most aggressive):
    1. Parse as-is (after stripping markdown)
    2. Apply common syntax fixes (_clean_json_text)
    3. Extract outermost { ... } and retry with fixes
    4. Fix unescaped control characters (tabs, form feeds)
    5. Fix unescaped newlines inside string values
    6. Fix single quotes → double quotes (Python-style dicts)
    """
    text = _strip_markdown_wrapper(raw_text)

    # Attempt 1: parse as-is
    try:
        return cast(dict[str, Any], json.loads(text))
    except json.JSONDecodeError:
        pass

    # Attempt 2: common fixes (trailing commas, comments, NaN)
    cleaned = _clean_json_text(text)
    try:
        return cast(dict[str, Any], json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    # Attempt 3: extract outermost { ... } block
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        fragment = text[start : end + 1]
        cleaned_fragment = _clean_json_text(fragment)
        try:
            return cast(dict[str, Any], json.loads(cleaned_fragment))
        except json.JSONDecodeError:
            pass

        # Attempt 4: fix unescaped control characters
        ctrl_fixed = fragment.replace("\t", "\\t").replace("\f", "\\f")
        ctrl_fixed = _clean_json_text(ctrl_fixed)
        try:
            return cast(dict[str, Any], json.loads(ctrl_fixed))
        except json.JSONDecodeError:
            pass

        # Attempt 5: fix unescaped newlines inside string values
        nl_fixed = _fix_unescaped_newlines(fragment)
        nl_fixed = _clean_json_text(nl_fixed)
        try:
            return cast(dict[str, Any], json.loads(nl_fixed))
        except json.JSONDecodeError:
            pass

        # Attempt 6: combined - control chars + newlines
        combined = fragment.replace("\t", "\\t").replace("\f", "\\f")
        combined = _fix_unescaped_newlines(combined)
        combined = _clean_json_text(combined)
        try:
            return cast(dict[str, Any], json.loads(combined))
        except json.JSONDecodeError:
            pass

    # Attempt 7: single quotes → double quotes (Python-style)
    sq_fixed = _fix_single_quotes(text)
    if sq_fixed != text:
        try:
            return cast(dict[str, Any], json.loads(sq_fixed))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found in AI response", text[:200], 0)


def _retry_json_fix(model_id: str, broken_json: str) -> dict[str, Any] | None:
    """Ask the AI to fix its own broken JSON output (second-chance repair).

    Sends the malformed JSON back to the model with strict instructions
    to return only valid JSON. Uses a smaller max_tokens to keep costs down.
    """
    logger.warning("JSON parse failed, attempting AI-assisted repair (model=%s)", model_id)
    try:
        client = get_client()
        # Truncate to avoid sending huge broken payloads
        truncated = broken_json[:16000]
        fix_msg = client.messages.create(
            model=model_id,
            max_tokens=8192,
            system=(
                "You fix malformed JSON. Respond ONLY with the corrected JSON object, "
                "no text before or after, no markdown code blocks. "
                "Don't change content, only fix JSON syntax errors."
            ),
            messages=[{"role": "user", "content": f"Fix this malformed JSON:\n\n{truncated}"}],
        )
        repair_cost = _calculate_cost(fix_msg.usage, model_id)
        logger.info(
            "JSON repair API call: input=%d, output=%d, cost=$%.6f",
            fix_msg.usage.input_tokens,
            fix_msg.usage.output_tokens,
            repair_cost,
        )
        content_block = fix_msg.content[0]
        if not hasattr(content_block, "text"):
            return None
        fixed_text = content_block.text
        result = _extract_and_parse_json(fixed_text)
        logger.info("AI-assisted JSON repair succeeded")
        return result
    except Exception:
        logger.exception("AI-assisted JSON repair failed")
        return None


def _call_api(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
) -> tuple[dict[str, Any], anthropic.types.Usage]:
    """Make an API call and parse the JSON response.

    Parsing pipeline:
    1. Try _extract_and_parse_json (7 strategies)
    2. On failure, try _retry_json_fix (AI self-repair)
    3. On total failure, raise with context for debugging
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
    )

    content_block = message.content[0]
    if not hasattr(content_block, "text"):
        raise json.JSONDecodeError("No text in AI response", "", 0)
    raw_text = content_block.text

    try:
        result = _extract_and_parse_json(raw_text)
    except json.JSONDecodeError:
        logger.warning(
            "Primary JSON parse failed (model=%s, response_len=%d, first_100=%r)",
            model_id,
            len(raw_text),
            raw_text[:100],
        )
        fixed = _retry_json_fix(model_id, raw_text)
        if fixed is None:
            # Log the full raw response so we can post-mortem the parse
            # failure without re-running the call (and re-paying tokens).
            logger.error(
                "JSON parse fully failed model=%s len=%d raw_text=%r",
                model_id,
                len(raw_text),
                raw_text,
            )
            raise
        result = fixed

    return result, message.usage


def analyze_job(
    cv_text: str,
    job_description: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict[str, Any]:
    """Analyze CV-to-job compatibility."""
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
    result, usage = _call_api(ANALYSIS_SYSTEM_PROMPT, user_prompt, model_id, 8192)

    result = validate_analysis(result)

    result["model_used"] = model_id
    result["full_response"] = ""  # Don't cache full response in Redis
    result["from_cache"] = False
    result["content_hash"] = ch
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)

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
        cl_content = f"cl:{model}:{ch[:16]}:{language}"
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

    result, usage = _call_api(COVER_LETTER_SYSTEM_PROMPT, user_prompt, model_id, 2048)

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

    result, usage = _call_api(FOLLOWUP_EMAIL_SYSTEM_PROMPT, user_prompt, model_id, 1024)

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

    result, usage = _call_api(LINKEDIN_MESSAGE_SYSTEM_PROMPT, user_prompt, model_id, 1024)

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
