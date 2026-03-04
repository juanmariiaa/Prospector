"""Agent 4: AI scoring of sales opportunity using Gemini API."""
import json
import logging
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.config import settings

logger = logging.getLogger(__name__)


def _build_prompt(business: dict[str, Any]) -> str:
    """Build a comprehensive structured prompt for Gemini from all available data."""

    web_analisis: dict[str, Any] | None = business.get("web_analisis")

    # ------------------------------------------------------------------ #
    # Section 1 — Negocio                                                 #
    # ------------------------------------------------------------------ #
    redes = list((business.get("redes_sociales") or {}).keys())
    redes_str = ", ".join(redes) if redes else "ninguna detectada"

    seccion_negocio = f"""\
=== SECCIÓN 1: NEGOCIO ===
- Nombre: {business.get("nombre") or "desconocido"}
- Categoría: {business.get("categoria") or "desconocida"}
- Rating Google: {business.get("rating_google") or "sin datos"}
- Número de reseñas: {business.get("num_reseñas") or 0}
- Tiene email: {"sí" if business.get("email") else "no"}
- Redes sociales detectadas: {redes_str}"""

    # ------------------------------------------------------------------ #
    # Section 6 — Rendimiento (always present, from PageSpeed + viewport) #
    # Placed here so it can be included even when web_analisis is None    #
    # ------------------------------------------------------------------ #
    web_score = business.get("web_score")
    fcp_ms = business.get("web_velocidad_ms")
    es_mobile = business.get("web_es_mobile")

    pagespeed_score_str = f"{web_score}/5 (1=excelente, 5=pésimo)" if web_score is not None else "sin datos"
    fcp_str = f"{fcp_ms} ms" if fcp_ms is not None else "sin datos"
    mobile_str = "sí" if es_mobile else ("no" if es_mobile is not None else "sin datos")

    seccion_rendimiento = f"""\
=== SECCIÓN 6: RENDIMIENTO ===
- PageSpeed score técnico: {pagespeed_score_str}
- Velocidad FCP: {fcp_str}
- Mobile-friendly (viewport): {mobile_str}"""

    # ------------------------------------------------------------------ #
    # Section 7 — Contenido de la web (up to 10 000 chars)               #
    # ------------------------------------------------------------------ #
    web_contenido_raw = business.get("web_contenido") or ""
    web_contenido_display = web_contenido_raw[:10_000] if web_contenido_raw else "(no se pudo obtener contenido de la web)"

    seccion_contenido_web = f"""\
=== SECCIÓN 7: CONTENIDO DE LA WEB ===
{web_contenido_display}"""

    # ------------------------------------------------------------------ #
    # Sections 2-5 — only when web_analisis is available                  #
    # ------------------------------------------------------------------ #
    if web_analisis is None:
        secciones_tecnicas = """\
=== ANÁLISIS TÉCNICO: no disponible (scraping fallido o sin web) ==="""
    else:
        tecnico: dict[str, Any] = web_analisis.get("tecnico") or {}
        modernidad: dict[str, Any] = web_analisis.get("modernidad") or {}
        seo: dict[str, Any] = web_analisis.get("seo") or {}
        contenido: dict[str, Any] = web_analisis.get("contenido") or {}

        # Section 2 — Análisis técnico
        cms = tecnico.get("cms_detectado") or "no detectado"
        cms_hint = tecnico.get("cms_version_hint")
        cms_str = f"{cms} ({cms_hint})" if cms_hint else cms
        https_str = "sí" if tecnico.get("https") else "no"
        server_str = tecnico.get("server") or tecnico.get("powered_by") or "sin datos"
        last_mod = tecnico.get("last_modified_year")
        last_mod_str = str(last_mod) if last_mod else "sin datos"

        seccion_tecnico = f"""\
=== SECCIÓN 2: ANÁLISIS TÉCNICO WEB ===
- CMS detectado: {cms_str}
- HTTPS: {https_str}
- Servidor/tecnología backend: {server_str}
- Año última modificación (header HTTP): {last_mod_str}"""

        # Section 3 — Modernidad y Marketing
        copyright_year = modernidad.get("copyright_year")
        if copyright_year is None:
            copyright_str = "no detectado"
        elif copyright_year < 2022:
            copyright_str = f"{copyright_year}  ⚠ WEB POTENCIALMENTE DESACTUALIZADA"
        else:
            copyright_str = str(copyright_year)

        ga_str = "sí" if modernidad.get("tiene_analytics") else "no"
        gtm_str = "sí" if modernidad.get("tiene_gtm") else "no"
        pixel_str = "sí" if modernidad.get("tiene_pixel_facebook") else "no"
        json_ld_str = "sí" if modernidad.get("tiene_json_ld") else "no"

        seccion_modernidad = f"""\
=== SECCIÓN 3: MODERNIDAD Y MARKETING ===
- Año copyright detectado: {copyright_str}
- Google Analytics: {ga_str}
- Google Tag Manager: {gtm_str}
- Facebook Pixel: {pixel_str}
- Datos estructurados JSON-LD: {json_ld_str}"""

        # Section 4 — SEO
        tiene_meta = seo.get("tiene_meta_description", False)
        meta_len = seo.get("meta_description_length", 0)
        meta_str = f"sí ({meta_len} caracteres)" if tiene_meta else "no"
        h1_count = seo.get("h1_count", 0)
        img_total = seo.get("imagenes_total", 0)
        img_alt = seo.get("imagenes_con_alt", 0)
        img_pct = int(round(seo.get("imagenes_alt_pct", 0.0) * 100))
        img_str = f"{img_alt} de {img_total} ({img_pct}%)"
        links_internos = seo.get("links_internos", 0)

        seccion_seo = f"""\
=== SECCIÓN 4: SEO ===
- Meta description: {meta_str}
- Número de H1: {h1_count}
- Imágenes con alt text: {img_str}
- Links internos: {links_internos}"""

        # Section 5 — Contenido
        form_str = "sí" if contenido.get("tiene_formulario_contacto") else "no"
        tel_str = "sí" if contenido.get("tiene_telefono_en_texto") else "no"
        dir_str = "sí" if contenido.get("tiene_direccion_en_texto") else "no"
        palabras = contenido.get("palabras_visibles", 0)

        seccion_contenido = f"""\
=== SECCIÓN 5: CONTENIDO ===
- Formulario de contacto: {form_str}
- Teléfono visible en web: {tel_str}
- Dirección visible en web: {dir_str}
- Palabras visibles: {palabras}"""

        secciones_tecnicas = "\n\n".join([
            seccion_tecnico,
            seccion_modernidad,
            seccion_seo,
            seccion_contenido,
        ])

    # ------------------------------------------------------------------ #
    # Assemble full prompt                                                 #
    # ------------------------------------------------------------------ #
    prompt = f"""\
Eres un analista experto en ventas de servicios de desarrollo web para negocios locales.

Analiza los siguientes datos del negocio y puntúa la oportunidad de venderle servicios web.

{seccion_negocio}

{secciones_tecnicas}

{seccion_rendimiento}

{seccion_contenido_web}

ESCALA DE PUNTUACIÓN (del 1 al 5):

1 = Web PROFESIONAL y MODERNA: Rápida (FCP < 2000ms), mobile-friendly, analytics configurado,
    copyright reciente (2022+), contenido de calidad, buen SEO, HTTPS, formulario de contacto.
    La web NO necesita mejora significativa.

2 = Web DECENTE pero MEJORABLE: Funciona bien pero tiene 1-2 problemas: sin analytics,
    velocidad media, pocas imágenes optimizadas, contenido escaso. Oportunidad de mejora menor.

3 = Web MEDIOCRE: Varios problemas visibles: sin mobile, lenta (FCP > 3000ms), sin analytics,
    copyright antiguo (2019-2021), contenido pobre o genérico, sin formularios.

4 = Web MUY POBRE: Mayormente rota o inutilizable: sin responsive, muy lenta (FCP > 5000ms),
    contenido mínimo o desactualizado (copyright < 2019), sin contacto, CMS muy antiguo.

5 = SIN WEB o COMPLETAMENTE ROTA: No carga, error 404/500, o tan degradada que no sirve.
    (Nota: score 5 sin web se asigna automáticamente antes de llamar a la IA)

IMPORTANTE: Usa scores 1 y 2 cuando la evidencia lo justifique. No defecto a 3.
Si la web es claramente moderna y profesional, puntúa 1 o 2.
Si la web es claramente mala, puntúa 4 o 5.
Reserva el 3 para casos genuinamente mediocres.

La razón debe referenciar hallazgos concretos, por ejemplo:
"Web antigua (copyright 2018), sin analytics, lenta (4200ms FCP)" o
"Web moderna con analytics, HTTPS, mobile-friendly y buen SEO".

Responde ÚNICAMENTE con un objeto JSON válido, sin markdown, sin explicación adicional:
{{"oportunidad_score": <entero 1-5>, "oportunidad_razon": "<explicación concisa en español, máx 200 caracteres>"}}
"""
    return prompt


async def score_business(business: dict[str, Any]) -> dict[str, Any]:
    """
    Score a business's sales opportunity using Gemini.

    Args:
        business: full business dict with all collected data, including
                  optional 'web_analisis' key populated by Agent 3.

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

    prompt = _build_prompt(business)

    raw = ""
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        logger.debug(
            f"Gemini request for {business.get('nombre')}: model=gemini-2.5-flash"
        )
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(temperature=0.2),
        )
        raw = response.text.strip()
        logger.debug(f"Gemini response for {business.get('nombre')}: {raw}")

        # Parse JSON — strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        score = int(data["oportunidad_score"])
        if not 1 <= score <= 5:
            raise ValueError(f"Score out of range: {score}")

        return {
            "oportunidad_score": score,
            "oportunidad_razon": str(data["oportunidad_razon"])[:500],
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
