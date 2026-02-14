import hashlib
import json
import logging
import re
import time

import anthropic
import redis

from .config import settings
from .prompts import (
    ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT,
    COVER_LETTER_SYSTEM_PROMPT, COVER_LETTER_USER_PROMPT,
    FOLLOWUP_EMAIL_SYSTEM_PROMPT, FOLLOWUP_EMAIL_USER_PROMPT,
    LINKEDIN_MESSAGE_SYSTEM_PROMPT, LINKEDIN_MESSAGE_USER_PROMPT,
)

logger = logging.getLogger(__name__)

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
}

# $/MTok pricing
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}

CACHE_TTL = 86400  # 24h

_redis = None


def _extract_and_parse_json(raw_text: str) -> dict:
    """Extract JSON from AI response, fixing common LLM output issues."""
    text = raw_text.strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    # First attempt: parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fix trailing commas before } or ] (most common LLM mistake)
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)

    # Remove single-line // comments
    cleaned = re.sub(r"//[^\n]*", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Last resort: find the outermost { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        fragment = text[start : end + 1]
        fragment = re.sub(r",\s*([}\]])", r"\1", fragment)
        fragment = re.sub(r"//[^\n]*", "", fragment)
        return json.loads(fragment)

    raise json.JSONDecodeError("Nessun JSON valido trovato nella risposta AI", text, 0)


def _get_redis():
    global _redis
    if _redis is None:
        try:
            _redis = redis.from_url(settings.redis_url, decode_responses=True)
            _redis.ping()
            logger.info("Redis connesso: %s", settings.redis_url)
        except Exception as e:
            logger.warning("Redis non disponibile (%s), cache disattivata", e)
            _redis = False
    return _redis if _redis else None


def _content_hash(cv_text: str, job_description: str) -> str:
    """SHA-256 hash of full CV + job description for duplicate detection."""
    content = f"{cv_text}:{job_description}"
    return hashlib.sha256(content.encode()).hexdigest()


def _cache_key(content_hash: str, model: str) -> str:
    return f"analysis:{model}:{content_hash[:16]}"


def analyze_job(cv_text: str, job_description: str, model: str = "haiku") -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])
    ch = _content_hash(cv_text, job_description)

    # Check cache
    r = _get_redis()
    if r:
        key = _cache_key(ch, model)
        cached = r.get(key)
        if cached:
            logger.info("Cache HIT per analisi (model=%s)", model)
            result = json.loads(cached)
            result["from_cache"] = True
            result["content_hash"] = ch
            return result
    else:
        logger.debug("Cache SKIP: Redis non disponibile")

    logger.debug("Chiamata API Anthropic: model=%s, max_tokens=4096", model_id)
    t0 = time.monotonic()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": ANALYSIS_USER_PROMPT.format(
                    cv_text=cv_text,
                    job_description=job_description,
                ),
            }
        ],
    )

    elapsed = time.monotonic() - t0
    raw_text = message.content[0].text

    try:
        result = _extract_and_parse_json(raw_text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse fallito per risposta AI: %s (primi 300 char: %s)", e, raw_text[:300])
        raise

    result["model_used"] = model_id
    result["full_response"] = raw_text
    result["from_cache"] = False
    result["content_hash"] = ch

    # Token usage and cost
    usage = message.usage
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost

    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = round(total_cost, 6)

    logger.info(
        "API analisi completata: model=%s, %.1fs, %d tok in + %d tok out, $%.6f",
        model_id,
        elapsed,
        usage.input_tokens,
        usage.output_tokens,
        total_cost,
    )

    # Save to cache
    if r:
        try:
            cache_data = {k: v for k, v in result.items() if k != "from_cache"}
            r.setex(key, CACHE_TTL, json.dumps(cache_data, ensure_ascii=False))
            logger.debug("Analisi salvata in cache (key=%s)", key)
        except Exception as e:
            logger.warning("Cache write fallita: %s", e)

    return result


def generate_cover_letter(
    cv_text: str, job_description: str, analysis_result: dict, language: str, model: str = "haiku"
) -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])

    # Check cache
    r = _get_redis()
    cache_key = None
    if r:
        content = f"cl:{model}:{cv_text[:300]}:{job_description[:300]}:{language}"
        cache_key = f"coverletter:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        cached = r.get(cache_key)
        if cached:
            logger.info("Cache HIT per cover letter (model=%s, lang=%s)", model, language)
            result = json.loads(cached)
            result["from_cache"] = True
            return result
    else:
        logger.debug("Cache SKIP cover letter: Redis non disponibile")

    strengths_text = ", ".join(analysis_result.get("strengths", [])[:5])
    gaps_list = analysis_result.get("gaps", [])
    gaps_text = ", ".join(g.get("gap", g) if isinstance(g, dict) else str(g) for g in gaps_list[:5])

    logger.debug("Chiamata API Anthropic cover letter: model=%s, max_tokens=2048, lang=%s", model_id, language)
    t0 = time.monotonic()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=2048,
        system=COVER_LETTER_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": COVER_LETTER_USER_PROMPT.format(
                    cv_text=cv_text,
                    job_description=job_description,
                    role=analysis_result.get("role", ""),
                    company=analysis_result.get("company", ""),
                    score=analysis_result.get("score", 0),
                    strengths=strengths_text,
                    gaps=gaps_text,
                    language=language,
                ),
            }
        ],
    )

    elapsed = time.monotonic() - t0
    raw_text = message.content[0].text

    try:
        result = _extract_and_parse_json(raw_text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse fallito per cover letter: %s (primi 300 char: %s)", e, raw_text[:300])
        raise

    result["model_used"] = model_id
    result["from_cache"] = False

    usage = message.usage
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost

    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = round(total_cost, 6)

    logger.info(
        "API cover letter completata: model=%s, lang=%s, %.1fs, %d tok in + %d tok out, $%.6f",
        model_id,
        language,
        elapsed,
        usage.input_tokens,
        usage.output_tokens,
        total_cost,
    )

    if r and cache_key:
        try:
            cache_data = {k: v for k, v in result.items() if k != "from_cache"}
            r.setex(cache_key, CACHE_TTL, json.dumps(cache_data, ensure_ascii=False))
            logger.debug("Cover letter salvata in cache (key=%s)", cache_key)
        except Exception as e:
            logger.warning("Cache write cover letter fallita: %s", e)

    return result


def generate_followup_email(
    cv_text: str, role: str, company: str, days_since: int, language: str, model: str = "haiku"
) -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])
    cv_summary = cv_text[:1500]

    logger.debug("Chiamata API follow-up email: model=%s, lang=%s", model_id, language)
    t0 = time.monotonic()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=1024,
        system=FOLLOWUP_EMAIL_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": FOLLOWUP_EMAIL_USER_PROMPT.format(
                cv_summary=cv_summary, role=role, company=company,
                days_since_application=days_since, language=language,
            ),
        }],
    )

    elapsed = time.monotonic() - t0
    raw_text = message.content[0].text
    result = _extract_and_parse_json(raw_text)
    result["model_used"] = model_id

    usage = message.usage
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    total_cost = (usage.input_tokens / 1_000_000) * pricing["input"] + (usage.output_tokens / 1_000_000) * pricing["output"]
    result["tokens"] = {"input": usage.input_tokens, "output": usage.output_tokens, "total": usage.input_tokens + usage.output_tokens}
    result["cost_usd"] = round(total_cost, 6)

    logger.info("API follow-up email: model=%s, %.1fs, $%.6f", model_id, elapsed, total_cost)
    return result


def generate_linkedin_message(
    cv_text: str, role: str, company: str, contact_info: str, language: str, model: str = "haiku"
) -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])
    cv_summary = cv_text[:1500]

    logger.debug("Chiamata API LinkedIn message: model=%s, lang=%s", model_id, language)
    t0 = time.monotonic()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=1024,
        system=LINKEDIN_MESSAGE_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": LINKEDIN_MESSAGE_USER_PROMPT.format(
                cv_summary=cv_summary, role=role, company=company,
                contact_info=contact_info or "Non disponibile", language=language,
            ),
        }],
    )

    elapsed = time.monotonic() - t0
    raw_text = message.content[0].text
    result = _extract_and_parse_json(raw_text)
    result["model_used"] = model_id

    usage = message.usage
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    total_cost = (usage.input_tokens / 1_000_000) * pricing["input"] + (usage.output_tokens / 1_000_000) * pricing["output"]
    result["tokens"] = {"input": usage.input_tokens, "output": usage.output_tokens, "total": usage.input_tokens + usage.output_tokens}
    result["cost_usd"] = round(total_cost, 6)

    logger.info("API LinkedIn message: model=%s, %.1fs, $%.6f", model_id, elapsed, total_cost)
    return result
