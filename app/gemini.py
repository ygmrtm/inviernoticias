import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from . import db

logger = logging.getLogger(__name__)

# ==========================================
# CUSTOM EXCEPTIONS FOR QUOTA MANAGEMENT
# ==========================================

class GeminiQuotaExceededError(Exception):
    """Raised when a Gemini API key has exceeded quota limits (HTTP 429 / RESOURCE_EXHAUSTED)."""
    pass

class AllTokensQuotaExceededError(GeminiQuotaExceededError):
    """Raised when both primary and backup Gemini API keys have exceeded quota limits."""
    pass

# Curated list of suitable Gemini models for satire detection, cultural context, and search grounding
SUITABLE_MODELS = [
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "recommended": True,
        "tier": "Balance Óptimo (Velocidad y Precisión)",
        "description": "Modelo insignia de última generación. Alta velocidad y bajo costo, con comprensión nativa sobresaliente de modismos mexicanos y soporte de Google Search Grounding.",
        "supports_grounding": True,
        "strengths": "Ideal para el 95% de las tareas de ingesta diaria, detección rápida de sátira y contraste de noticias."
    },
    {
        "id": "gemini-2.5-pro",
        "name": "Gemini 2.5 Pro",
        "recommended": False,
        "tier": "Máximo Razonamiento y Análisis Editorial",
        "description": "Capacidad de razonamiento superior para casos ambiguos, sátira política sutil, ironía compleja y asociaciones históricas/literarias profundas.",
        "supports_grounding": True,
        "strengths": "Excelente para artículos difíciles, ambigüedad política y validación profunda."
    },
    {
        "id": "gemini-2.0-flash",
        "name": "Gemini 2.0 Flash",
        "recommended": False,
        "tier": "Rápido y Multimodal Estable",
        "description": "Modelo flash de alta confiabilidad con baja latencia y soporte completo de herramientas de búsqueda.",
        "supports_grounding": True,
        "strengths": "Procesamiento consistente con excelente rendimiento en español."
    },
    {
        "id": "gemini-2.0-flash-lite",
        "name": "Gemini 2.0 Flash-Lite",
        "recommended": False,
        "tier": "Ultra Ligero y Económico",
        "description": "La opción más eficiente en costos y latencia, diseñada para procesamiento masivo de feeds con alto volumen.",
        "supports_grounding": True,
        "strengths": "Filtrado masivo a costo mínimo cuando el volumen de noticias por hora es muy alto."
    },
    {
        "id": "gemini-1.5-flash",
        "name": "Gemini 1.5 Flash (Legacy)",
        "recommended": False,
        "tier": "Legado Estable",
        "description": "Versión previa estable con ventana de contexto de 1 millón de tokens.",
        "supports_grounding": True,
        "strengths": "Compatibilidad retrospectiva."
    },
    {
        "id": "gemini-1.5-pro",
        "name": "Gemini 1.5 Pro (Legacy)",
        "recommended": False,
        "tier": "Legado Avanzado",
        "description": "Modelo de razonamiento de primera generación con ventana de contexto de hasta 2 millones de tokens.",
        "supports_grounding": True,
        "strengths": "Análisis extenso y razonamiento complejo."
    }
]

DEFAULT_FALLBACK_MODEL = "gemini-2.5-flash"

def get_selected_model() -> str:
    """
    Returns the currently active default model:
    1. From SQLite settings table ('default_model')
    2. From environment variable DEFAULT_GEMINI_MODEL
    3. Fallback to DEFAULT_FALLBACK_MODEL ('gemini-2.5-flash')
    """
    try:
        configured = db.get_setting("default_model")
        if configured:
            return configured
    except Exception as e:
        logger.warning(f"Could not read default_model from db settings: {e}")

    return os.getenv("DEFAULT_GEMINI_MODEL", DEFAULT_FALLBACK_MODEL)

def set_default_model(model_id: str) -> str:
    """
    Persists the new default model in SQLite settings.
    """
    valid_ids = [m["id"] for m in SUITABLE_MODELS]
    if model_id not in valid_ids:
        raise ValueError(f"Modelo no válido: '{model_id}'. Opciones válidas: {valid_ids}")

    db.set_setting("default_model", model_id)
    logger.info(f"Default AI Model updated to: '{model_id}'")
    return model_id

def get_available_models() -> List[Dict[str, Any]]:
    """
    Returns the list of suitable models, flagging the one currently selected as default.
    """
    current_default = get_selected_model()
    result = []
    for m in SUITABLE_MODELS:
        item = dict(m)
        item["is_current_default"] = (m["id"] == current_default)
        result.append(item)
    return result

# ==========================================
# TOKEN MANAGEMENT & QUOTA FALLBACK
# ==========================================

def get_primary_api_key() -> Optional[str]:
    try:
        configured = db.get_setting("gemini_api_key")
        if configured:
            return configured.strip()
    except Exception:
        pass
    return (os.getenv("GEMINI_API_KEY") or "").strip() or None

def get_backup_api_key() -> Optional[str]:
    try:
        configured = db.get_setting("gemini_backup_api_key")
        if configured:
            return configured.strip()
    except Exception:
        pass
    return (
        os.getenv("GEMINI_BACKUP_API_KEY") 
        or os.getenv("GEMINI_API_KEY_BACKUP") 
        or ""
    ).strip() or None

def set_tokens(primary_key: Optional[str] = None, backup_key: Optional[str] = None):
    if primary_key is not None and primary_key.strip():
        db.set_setting("gemini_api_key", primary_key.strip())
        db.set_setting("gemini_primary_quota_exceeded", "false")
        logger.info("Primary GEMINI_API_KEY updated in database settings.")
    if backup_key is not None:
        db.set_setting("gemini_backup_api_key", backup_key.strip())
        db.set_setting("gemini_backup_quota_exceeded", "false")
        logger.info("Backup GEMINI_BACKUP_API_KEY updated in database settings.")

def reset_quota_status():
    db.set_setting("gemini_primary_quota_exceeded", "false")
    db.set_setting("gemini_backup_quota_exceeded", "false")
    db.set_setting("gemini_active_token_type", "primary")
    logger.info("Quota status reset: both tokens marked available, active set to primary.")

def mask_key(key: Optional[str]) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:6]}...{key[-4:]}"

def get_tokens_status() -> Dict[str, Any]:
    primary = get_primary_api_key()
    backup = get_backup_api_key()
    
    p_exceeded = db.get_setting("gemini_primary_quota_exceeded", "false") == "true"
    b_exceeded = db.get_setting("gemini_backup_quota_exceeded", "false") == "true"

    if p_exceeded and backup and not b_exceeded:
        active = "backup"
    elif not p_exceeded and primary:
        active = "primary"
    else:
        active = db.get_setting("gemini_active_token_type", "primary")

    return {
        "primary_configured": bool(primary),
        "primary_masked": mask_key(primary),
        "backup_configured": bool(backup),
        "backup_masked": mask_key(backup),
        "active_token_type": active,
        "primary_quota_exceeded": p_exceeded,
        "backup_quota_exceeded": b_exceeded,
        "all_quotas_exceeded": bool(p_exceeded and (b_exceeded or not backup))
    }

def is_quota_exceeded_error(err: Exception) -> bool:
    err_str = str(err).lower()
    err_code = getattr(err, "code", None) or getattr(err, "status_code", None)
    if err_code in (429, "429"):
        return True
    if (
        "429" in err_str 
        or "resource_exhausted" in err_str 
        or "quota exceeded" in err_str 
        or "rate limit" in err_str
    ):
        return True
    return False

def get_genai_client(api_key: Optional[str] = None) -> genai.Client:
    key = api_key or get_primary_api_key() or get_backup_api_key()
    if not key:
        raise ValueError("GEMINI_API_KEY no está configurada en settings ni en variables de entorno.")
    return genai.Client(api_key=key)

def analyze_content(title: str, content: str, model: Optional[str] = None) -> Dict[str, Any]:
    active_model = model or get_selected_model()

    prompt = f"""
You are an expert fact-checker, bias analyst, and cultural editor specializing in Mexican news, slang, and satire.
Analyze the following article title and description content. 

You must evaluate:
1. Whether it is satire/humorous/fictional (e.g., El Deforma style) which qualifies as "Mock-ticia" (isSatire: true), or if it is a real/actual news piece ("Real-ticia", isSatire: false).
2. The percentage of truth (truthScore: 0 to 100) and sarcasm (sarcasmScore: 0 to 100).
3. Whether the situation is surreal, absurd, or bizarre enough to qualify for the "México Mágico" badge (mexicoMagicoAward: true/false). This badge is called "Mexico Mágico se la deja ir a la IA".
4. A fitting Mexican proverb/saying ("refrán") related to the topic or situation.
5. A relevant quote from a prominent historical or important figure in Mexican history (e.g., Benito Juárez, Octavio Paz, Cantinflas, Sor Juana, Jose Vasconcelos, etc.) ONLY if it fits, otherwise null.
6. A breakdown explanation for a foreigner ("foreignerExplanation") so they can understand the joke, cultural context, or slang without needing to be Mexican.
7. Any specific reference to Mexican culture, society, slang, or current events.
8. Provide a news summary "newsSummary" about the real news.
9. Contrast sources: use search grounding to verify the facts and suggest related real-news articles to contrast or check.

Provide the output in valid JSON format with exactly the following structure:
{{
  "isSatire": <true / false>,
  "truthScore": <number from 0 to 100>,
  "sarcasmScore": <number from 0 to 100>,
  "mexicoMagicoAward": <true / false>,
  "refran": "<Mexican refrán / saying>",
  "historicalQuote": "<Quote from historical figure or null>",
  "foreignerExplanation": "<Explanation for a foreigner>",
  "newsSummary": "<News summary>",
  "mexicanCultureReferences": "<Specific cultural references found>",
  "analysisSummary": "<A short, clear paragraph explaining your overall findings>",
  "relatedSources": [
    "<Source/article URL or Title 1>",
    "<Source/article URL or Title 2>"
  ]
}}

Ensure the response is ONLY valid JSON in Spanish, do not include markdown code blocks like ```json or ```. 

Article Title:
"{title or 'Texto directo'}"

Article Description/Content:
"{content or ''}"
    """

    primary_key = get_primary_api_key()
    backup_key = get_backup_api_key()

    if not primary_key and not backup_key:
        raise ValueError("No hay ninguna clave GEMINI_API_KEY configurada.")

    primary_exceeded = db.get_setting("gemini_primary_quota_exceeded", "false") == "true"
    backup_exceeded = db.get_setting("gemini_backup_quota_exceeded", "false") == "true"

    tokens_to_try = []
    if primary_key and not primary_exceeded:
        tokens_to_try.append(("primary", primary_key))
    if backup_key and not backup_exceeded:
        tokens_to_try.append(("backup", backup_key))
    if not tokens_to_try:
        # If both flagged exceeded, retry both in case quota has reset
        if primary_key:
            tokens_to_try.append(("primary", primary_key))
        if backup_key:
            tokens_to_try.append(("backup", backup_key))

    response = None
    token_used_type = None

    for token_type, key in tokens_to_try:
        try:
            logger.info(f"Analyzing content using {token_type.upper()} Gemini token on model='{active_model}': '{title}'")
            client = genai.Client(api_key=key)

            try:
                response = client.models.generate_content(
                    model=active_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[{"google_search": {}}]
                    )
                )
            except Exception as search_err:
                if is_quota_exceeded_error(search_err):
                    raise search_err
                logger.warning(f"Fallback to standard Gemini without search grounding on model '{active_model}': {search_err}")
                response = client.models.generate_content(
                    model=active_model,
                    contents=prompt
                )

            token_used_type = token_type
            if token_type == "primary":
                db.set_setting("gemini_primary_quota_exceeded", "false")
                db.set_setting("gemini_active_token_type", "primary")
            else:
                db.set_setting("gemini_backup_quota_exceeded", "false")
                db.set_setting("gemini_active_token_type", "backup")
            break

        except Exception as err:
            if is_quota_exceeded_error(err):
                logger.warning(f"[Gemini Quota Exceeded] {token_type.upper()} token quota exceeded: {err}")
                if token_type == "primary":
                    db.set_setting("gemini_primary_quota_exceeded", "true")
                    if backup_key:
                        logger.info("Switching to BACKUP Gemini token for fallback...")
                        db.set_setting("gemini_active_token_type", "backup")
                    else:
                        logger.warning("No backup token configured to fallback to.")
                else:
                    db.set_setting("gemini_backup_quota_exceeded", "true")
                continue
            else:
                raise err

    if response is None:
        db.set_setting("gemini_primary_quota_exceeded", "true")
        if backup_key:
            db.set_setting("gemini_backup_quota_exceeded", "true")
        logger.error("[Gemini Quota Exceeded] All available tokens (primary and backup) have exceeded their quota!")
        raise AllTokensQuotaExceededError(
            "La cuota de la API de Gemini se ha agotado en las cuentas configuradas (principal y respaldo). "
            "La solicitud debe ser diferida o enviada a DLX."
        )

    result_text = response.text or ""
    cleaned_text = re.sub(r"^\s*```(?:json)?\s*", "", result_text.strip(), flags=re.MULTILINE)
    cleaned_text = re.sub(r"\s*```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)

    try:
        res = json.loads(cleaned_text)
        res["modelUsed"] = active_model
        res["tokenUsed"] = token_used_type
        return res
    except json.JSONDecodeError as err:
        logger.error(f"Failed to parse JSON from Gemini: {err}\nRaw text: {result_text}")
        raise ValueError(f"Error al procesar la respuesta del modelo de IA: {err}")
