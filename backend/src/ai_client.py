import hashlib
import json
import logging
import time

import anthropic
import redis

from .config import settings
from .prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT, COVER_LETTER_SYSTEM_PROMPT, COVER_LETTER_USER_PROMPT

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


def _cache_key(cv_text: str, job_description: str, model: str) -> str:
    content = f"{model}:{cv_text[:500]}:{job_description[:500]}"
    return f"analysis:{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def analyze_job(cv_text: str, job_description: str, model: str = "haiku") -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])

    # Check cache
    r = _get_redis()
    if r:
        key = _cache_key(cv_text, job_description, model)
        cached = r.get(key)
        if cached:
            logger.info("Cache HIT per analisi (model=%s)", model)
            result = json.loads(cached)
            result["from_cache"] = True
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

    # Parse JSON from response (handle markdown code blocks)
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse fallito per risposta AI: %s (primi 200 char: %s)", e, text[:200])
        raise

    result["model_used"] = model_id
    result["full_response"] = raw_text
    result["from_cache"] = False

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
        model_id, elapsed, usage.input_tokens, usage.output_tokens, total_cost,
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


def generate_cover_letter(cv_text: str, job_description: str, analysis_result: dict, language: str, model: str = "haiku") -> dict:
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
    gaps_text = ", ".join(
        g.get("gap", g) if isinstance(g, dict) else str(g) for g in gaps_list[:5]
    )

    logger.debug("Chiamata API Anthropic cover letter: model=%s, max_tokens=2048, lang=%s", model_id, language)
    t0 = time.monotonic()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=2048,
        system=COVER_LETTER_SYSTEM_PROMPT,
        messages=[{
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
        }],
    )

    elapsed = time.monotonic() - t0
    raw_text = message.content[0].text
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse fallito per cover letter: %s (primi 200 char: %s)", e, text[:200])
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
        model_id, language, elapsed, usage.input_tokens, usage.output_tokens, total_cost,
    )

    if r and cache_key:
        try:
            cache_data = {k: v for k, v in result.items() if k != "from_cache"}
            r.setex(cache_key, CACHE_TTL, json.dumps(cache_data, ensure_ascii=False))
            logger.debug("Cover letter salvata in cache (key=%s)", cache_key)
        except Exception as e:
            logger.warning("Cache write cover letter fallita: %s", e)

    return result
