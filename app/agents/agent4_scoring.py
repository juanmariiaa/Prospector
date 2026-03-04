"""Agent 4: AI scoring of sales opportunity using Groq API."""
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SCORING_PROMPT = """\
You are an expert sales analyst specializing in web presence quality for local businesses.

Analyze the following business data and score its opportunity for selling web development services.

SCORING SCALE:
- 5 = Maximum opportunity (no website, or completely broken/unusable)
- 4 = High opportunity (very poor web quality, mobile unfriendly, very slow)
- 3 = Medium opportunity (mediocre site with clear improvement areas)
- 2 = Low opportunity (decent site, minor improvements possible)
- 1 = Minimal opportunity (professional modern site, little to improve)

BUSINESS DATA:
{business_data}

Respond ONLY with a valid JSON object, no markdown, no explanation:
{{"score": <integer 1-5>, "razon": "<concise Spanish explanation, max 150 chars>"}}
"""


async def score_business(business: dict[str, Any]) -> dict[str, Any]:
    """
    Score a business's sales opportunity using Groq.

    Args:
        business: full business dict with all collected data

    Returns:
        dict with keys: oportunidad_score (int 1-5), oportunidad_razon (str)
    """
    # Auto-score: no website = maximum opportunity
    if not business.get("tiene_web") or not business.get("website"):
        logger.info(
            f"No website for {business.get('nombre', 'unknown')}, auto-score 5"
        )
        return {
            "oportunidad_score": 5,
            "oportunidad_razon": "Sin presencia web — máxima oportunidad de venta.",
        }

    if not settings.groq_api_key:
        logger.warning("No GROQ_API_KEY set, returning default score 3")
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "No se pudo analizar (API key no configurada).",
        }

    # Build a clean summary for the prompt (avoid sending raw HTML)
    summary = {
        "nombre": business.get("nombre"),
        "categoria": business.get("categoria"),
        "website": business.get("website"),
        "rating_google": business.get("rating_google"),
        "num_reseñas": business.get("num_reseñas"),
        "web_score_tecnico": business.get("web_score"),
        "web_es_mobile": business.get("web_es_mobile"),
        "web_velocidad_ms": business.get("web_velocidad_ms"),
        "tiene_email": bool(business.get("email")),
        "redes_sociales": list((business.get("redes_sociales") or {}).keys()),
    }

    prompt = SCORING_PROMPT.format(business_data=json.dumps(summary, ensure_ascii=False, indent=2))

    raw = ""
    try:
        client = AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
        message = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.choices[0].message.content.strip()
        logger.debug(f"Groq response for {business.get('nombre')}: {raw}")

        # Parse JSON — strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        score = int(data["score"])
        if not 1 <= score <= 5:
            raise ValueError(f"Score out of range: {score}")

        return {
            "oportunidad_score": score,
            "oportunidad_razon": str(data["razon"])[:500],
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Groq JSON response: {e}. Raw: {raw!r}")
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "Error al parsear respuesta de IA.",
        }
    except Exception as e:
        logger.error(
            f"Groq API error for {business.get('nombre', 'unknown')}: {e}",
            exc_info=True,
        )
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "Error en análisis IA.",
        }
