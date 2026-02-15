"""Anthropic API client with JSON parsing, retry logic, and cost tracking.

Provides a singleton client and functions for all AI operations:
analysis, cover letter, follow-up email, LinkedIn message.
"""

import hashlib
import json
import re

import anthropic

from ..config import settings
from ..prompts import (
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

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
}

PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}

CACHE_TTL = 86400  # 24 hours

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Get or create the singleton Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def content_hash(cv_text: str, job_description: str) -> str:
    """SHA-256 hash of CV + job description for duplicate detection."""
    content = f"{cv_text}:{job_description}"
    return hashlib.sha256(content.encode()).hexdigest()


def _calculate_cost(usage: anthropic.types.Usage, model_id: str) -> float:
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def _clean_json_text(text: str) -> str:
    """Fix common LLM JSON output issues."""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'([}\]])\s*\n\s*(")', r"\1,\n\2", text)
    text = re.sub(r'"\s*\n\s*"(?=[^:]*":)', '",\n"', text)
    return text


def _extract_and_parse_json(raw_text: str) -> dict:
    """Extract JSON from AI response, with multiple fallback strategies."""
    text = raw_text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    # Attempt 1: parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: common fixes
    cleaned = _clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 3: extract outermost { ... }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        fragment = _clean_json_text(text[start : end + 1])
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    # Attempt 4: fix unescaped control characters
    if start != -1 and end != -1:
        fragment = text[start : end + 1]
        fragment = fragment.replace("\t", "\\t").replace("\f", "\\f")
        fragment = _clean_json_text(fragment)
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found in AI response", text, 0)


def _retry_json_fix(model_id: str, broken_json: str) -> dict | None:
    """Ask the AI to fix its own broken JSON output."""
    try:
        client = get_client()
        fix_msg = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=(
                "You fix malformed JSON. Respond ONLY with the corrected JSON, "
                "no text before or after. Don't change content, only fix JSON syntax."
            ),
            messages=[{"role": "user", "content": f"Fix this malformed JSON:\n\n{broken_json}"}],
        )
        fixed_text = fix_msg.content[0].text
        return _extract_and_parse_json(fixed_text)
    except Exception:
        return None


def _call_api(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
) -> tuple[dict, anthropic.types.Usage]:
    """Make an API call and parse the JSON response."""
    client = get_client()

    message = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text

    try:
        result = _extract_and_parse_json(raw_text)
    except json.JSONDecodeError:
        result = _retry_json_fix(model_id, raw_text)
        if result is None:
            raise

    return result, message.usage


def analyze_job(
    cv_text: str,
    job_description: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict:
    """Analyze CV-to-job compatibility."""
    model_id = MODELS.get(model, MODELS["haiku"])
    ch = content_hash(cv_text, job_description)
    cache_key = f"analysis:{model}:{ch[:16]}"

    # Check cache
    if cache:
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            cached["content_hash"] = ch
            return cached

    user_prompt = ANALYSIS_USER_PROMPT.format(cv_text=cv_text, job_description=job_description)
    result, usage = _call_api(ANALYSIS_SYSTEM_PROMPT, user_prompt, model_id, 4096)

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

    # Save to cache
    if cache:
        cache_data = {k: v for k, v in result.items() if k != "from_cache"}
        cache.set_json(cache_key, cache_data, CACHE_TTL)

    return result


def generate_cover_letter(
    cv_text: str,
    job_description: str,
    analysis_data: dict,
    language: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> dict:
    """Generate a cover letter based on CV, job description, and analysis."""
    model_id = MODELS.get(model, MODELS["haiku"])

    # Check cache
    if cache:
        cl_content = f"cl:{model}:{cv_text[:300]}:{job_description[:300]}:{language}"
        cache_key = f"coverletter:{hashlib.sha256(cl_content.encode()).hexdigest()[:16]}"
        cached = cache.get_json(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached
    else:
        cache_key = None

    strengths_text = ", ".join(
        s if isinstance(s, str) else s.get("skill", str(s))
        for s in analysis_data.get("strengths", [])[:5]
    )
    gaps_list = analysis_data.get("gaps", [])
    gaps_text = ", ".join(
        g.get("gap", g) if isinstance(g, dict) else str(g) for g in gaps_list[:5]
    )

    user_prompt = COVER_LETTER_USER_PROMPT.format(
        cv_text=cv_text,
        job_description=job_description,
        role=analysis_data.get("role", ""),
        company=analysis_data.get("company", ""),
        score=analysis_data.get("score", 0),
        strengths=strengths_text,
        gaps=gaps_text,
        language=language,
    )

    result, usage = _call_api(COVER_LETTER_SYSTEM_PROMPT, user_prompt, model_id, 2048)

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
) -> dict:
    """Generate a follow-up email after application."""
    model_id = MODELS.get(model, MODELS["haiku"])
    cv_summary = cv_text[:1500]

    user_prompt = FOLLOWUP_EMAIL_USER_PROMPT.format(
        cv_summary=cv_summary,
        role=role,
        company=company,
        days_since_application=days_since,
        language=language,
    )

    result, usage = _call_api(FOLLOWUP_EMAIL_SYSTEM_PROMPT, user_prompt, model_id, 1024)

    result["model_used"] = model_id
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)
    return result


def generate_linkedin_message(
    cv_text: str,
    role: str,
    company: str,
    contact_info: str,
    language: str,
    model: str = "haiku",
) -> dict:
    """Generate a LinkedIn connection message."""
    model_id = MODELS.get(model, MODELS["haiku"])
    cv_summary = cv_text[:1500]

    user_prompt = LINKEDIN_MESSAGE_USER_PROMPT.format(
        cv_summary=cv_summary,
        role=role,
        company=company,
        contact_info=contact_info or "Not available",
        language=language,
    )

    result, usage = _call_api(LINKEDIN_MESSAGE_SYSTEM_PROMPT, user_prompt, model_id, 1024)

    result["model_used"] = model_id
    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = _calculate_cost(usage, model_id)
    return result
