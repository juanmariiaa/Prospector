"""Agent 4: AI scoring of sales opportunity using Gemini API."""
import json
import logging
from typing import Any

from google import genai

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

BUSINESS INFO:
{business_info}

WEBPAGE CONTENT SCRAPED:
{web_contenido}

PAGESPEED METRICS:
{pagespeed_info}

Respond ONLY with a valid JSON object, no markdown, no explanation:
{{"score": <integer 1-5>, "razon": "<concise Spanish explanation, max 150 chars>"}}
"""


async def score_business(business: dict[str, Any]) -> dict[str, Any]:
    """
    Score a business's sales opportunity using Gemini.

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

    if not settings.gemini_api_key:
        logger.warning("No GEMINI_API_KEY set, returning default score 3")
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "No se pudo analizar (API key no configurada).",
        }

    business_info = json.dumps({
        "nombre": business.get("nombre"),
        "categoria": business.get("categoria"),
        "website": business.get("website"),
        "rating_google": business.get("rating_google"),
        "num_reseñas": business.get("num_reseñas"),
        "tiene_email": bool(business.get("email")),
        "redes_sociales": list((business.get("redes_sociales") or {}).keys()),
    }, ensure_ascii=False, indent=2)

    pagespeed_info = json.dumps({
        "web_score_tecnico": business.get("web_score"),
        "web_es_mobile": business.get("web_es_mobile"),
        "web_velocidad_ms": business.get("web_velocidad_ms"),
    }, ensure_ascii=False)

    web_contenido = business.get("web_contenido") or "(no se pudo obtener contenido de la web)"

    prompt = SCORING_PROMPT.format(
        business_info=business_info,
        web_contenido=web_contenido,
        pagespeed_info=pagespeed_info,
    )

    raw = ""
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        logger.debug(
            f"Gemini request for {business.get('nombre')}: model=gemini-2.0-flash-lite"
        )
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=prompt,
        )
        raw = response.text.strip()
        logger.debug(f"Gemini response for {business.get('nombre')}: {raw}")

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
        logger.error(f"Failed to parse Gemini JSON response: {e}. Raw: {raw!r}")
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "Error al parsear respuesta de IA.",
        }
    except Exception as e:
        logger.error(
            f"Gemini API error for {business.get('nombre', 'unknown')}: {e}",
            exc_info=True,
        )
        return {
            "oportunidad_score": 3,
            "oportunidad_razon": "Error en análisis IA.",
        }
