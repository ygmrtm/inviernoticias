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
# TOKEN MANAGEMENT & QUOTA ROTATION (LIST OF KEYS)
# ==========================================

def mask_key(key: Optional[str]) -> str:
    if not key:
        return ""
    k = key.strip()
    if len(k) <= 8:
        return "****"
    return f"{k[:6]}...{k[-4:]}"

def get_api_keys() -> List[str]:
    """
    Returns the ordered list of Gemini API keys:
    1. From SQLite setting 'gemini_api_keys' (JSON array)
    2. Fallback to env var GEMINI_API_KEYS (comma or newline separated, or JSON array)
    3. Fallback to legacy env vars (GEMINI_API_KEY, GEMINI_BACKUP_API_KEY)
    4. Fallback to legacy SQLite settings ('gemini_api_key', 'gemini_backup_api_key')
    """
    raw_keys: List[str] = []

    # 1. Check SQLite JSON setting
    try:
        stored = db.get_setting("gemini_api_keys")
        if stored:
            parsed = json.loads(stored)
            if isinstance(parsed, list):
                raw_keys.extend([str(k).strip() for k in parsed if str(k).strip()])
    except Exception as e:
        logger.warning(f"Error reading gemini_api_keys from database: {e}")

    # 2. Check GEMINI_API_KEYS environment variable if DB setting was empty
    if not raw_keys:
        env_keys = os.getenv("GEMINI_API_KEYS", "").strip()
        if env_keys:
            if env_keys.startswith("[") and env_keys.endswith("]"):
                try:
                    parsed_env = json.loads(env_keys)
                    if isinstance(parsed_env, list):
                        raw_keys.extend([str(k).strip() for k in parsed_env if str(k).strip()])
                except Exception:
                    pass
            if not raw_keys:
                parts = re.split(r'[\r\n,;]+', env_keys)
                raw_keys.extend([p.strip() for p in parts if p.strip()])

    # 3. Check legacy env vars
    if not raw_keys:
        primary_env = (os.getenv("GEMINI_API_KEY") or "").strip()
        backup_env = (
            os.getenv("GEMINI_BACKUP_API_KEY") 
            or os.getenv("GEMINI_API_KEY_BACKUP") 
            or ""
        ).strip()
        if primary_env:
            raw_keys.append(primary_env)
        if backup_env:
            raw_keys.append(backup_env)

    # 4. Check legacy SQLite settings
    if not raw_keys:
        try:
            legacy_p = db.get_setting("gemini_api_key")
            legacy_b = db.get_setting("gemini_backup_api_key")
            if legacy_p and legacy_p.strip():
                raw_keys.append(legacy_p.strip())
            if legacy_b and legacy_b.strip():
                raw_keys.append(legacy_b.strip())
        except Exception:
            pass

    # Deduplicate while preserving ordering
    seen = set()
    cleaned_keys = []
    for k in raw_keys:
        if k and k not in seen:
            seen.add(k)
            cleaned_keys.append(k)

    return cleaned_keys

def set_api_keys(keys: List[str]):
    """
    Persists the ordered list of Gemini API keys in SQLite settings.
    Also syncs legacy settings for backward compatibility.
    """
    seen = set()
    cleaned = []
    for k in keys:
        clean = (k or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            cleaned.append(clean)

    db.set_setting("gemini_api_keys", json.dumps(cleaned))

    # Sync legacy settings
    if cleaned:
        db.set_setting("gemini_api_key", cleaned[0])
        if len(cleaned) > 1:
            db.set_setting("gemini_backup_api_key", cleaned[1])
        else:
            db.set_setting("gemini_backup_api_key", "")
    else:
        db.set_setting("gemini_api_key", "")
        db.set_setting("gemini_backup_api_key", "")

    # Clean exhausted keys to only include keys that still exist
    exhausted = get_exhausted_keys()
    new_exhausted = [k for k in exhausted if k in cleaned]
    db.set_setting("gemini_exhausted_keys", json.dumps(new_exhausted))

    # Validate active key index
    active_idx = get_active_key_index()
    if active_idx >= len(cleaned) and cleaned:
        set_active_key_index(0)

    logger.info(f"Updated Gemini API keys list: {len(cleaned)} keys configured.")

def add_api_key(key: str) -> bool:
    """
    Appends a new key to the list of API keys if not already present.
    """
    clean = (key or "").strip()
    if not clean:
        return False
    keys = get_api_keys()
    if clean in keys:
        return False
    keys.append(clean)
    set_api_keys(keys)
    return True

def remove_api_key(index: int) -> bool:
    """
    Removes the API key at the specified 0-based index.
    """
    keys = get_api_keys()
    if 0 <= index < len(keys):
        keys.pop(index)
        set_api_keys(keys)
        return True
    return False

def get_exhausted_keys() -> List[str]:
    """
    Returns list of API key strings currently flagged as having exceeded quota (429).
    """
    try:
        val = db.get_setting("gemini_exhausted_keys")
        if val:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(k) for k in parsed]
    except Exception:
        pass
    return []

def mark_key_exhausted(key: str):
    """
    Flags an API key as quota exhausted.
    """
    clean = (key or "").strip()
    if not clean:
        return
    exhausted = get_exhausted_keys()
    if clean not in exhausted:
        exhausted.append(clean)
        db.set_setting("gemini_exhausted_keys", json.dumps(exhausted))

    # Legacy flags sync
    keys = get_api_keys()
    if keys and clean == keys[0]:
        db.set_setting("gemini_primary_quota_exceeded", "true")
    if len(keys) > 1 and clean == keys[1]:
        db.set_setting("gemini_backup_quota_exceeded", "true")

def mark_key_available(key: str):
    """
    Clears the quota exhausted flag for an API key.
    """
    clean = (key or "").strip()
    if not clean:
        return
    exhausted = get_exhausted_keys()
    if clean in exhausted:
        exhausted = [k for k in exhausted if k != clean]
        db.set_setting("gemini_exhausted_keys", json.dumps(exhausted))

    # Legacy flags sync
    keys = get_api_keys()
    if keys and clean == keys[0]:
        db.set_setting("gemini_primary_quota_exceeded", "false")
    if len(keys) > 1 and clean == keys[1]:
        db.set_setting("gemini_backup_quota_exceeded", "false")

def get_active_key_index() -> int:
    """
    Returns the index of the currently active API key.
    """
    try:
        val = db.get_setting("gemini_active_key_index", "0")
        return int(val)
    except Exception:
        return 0

def set_active_key_index(index: int):
    """
    Sets the active API key index.
    """
    db.set_setting("gemini_active_key_index", str(index))
    # Sync legacy setting
    if index == 0:
        db.set_setting("gemini_active_token_type", "primary")
    elif index == 1:
        db.set_setting("gemini_active_token_type", "backup")
    else:
        db.set_setting("gemini_active_token_type", f"key_{index + 1}")

def get_primary_api_key() -> Optional[str]:
    keys = get_api_keys()
    return keys[0] if keys else None

def get_backup_api_key() -> Optional[str]:
    keys = get_api_keys()
    return keys[1] if len(keys) > 1 else None

def set_tokens(primary_key: Optional[str] = None, backup_key: Optional[str] = None):
    """
    Backward-compatible method to set primary and backup tokens.
    """
    keys = get_api_keys()
    pk = primary_key.strip() if primary_key and primary_key.strip() else None
    bk = backup_key.strip() if backup_key and backup_key.strip() else None

    if pk:
        if keys:
            keys[0] = pk
        else:
            keys.append(pk)
    if bk:
        if len(keys) > 1:
            keys[1] = bk
        elif len(keys) == 1:
            keys.append(bk)
        else:
            keys.extend(["", bk])

    set_api_keys([k for k in keys if k])

def reset_quota_status():
    """
    Resets quota-exhausted status for all keys and points active index back to the first key.
    """
    db.set_setting("gemini_exhausted_keys", "[]")
    set_active_key_index(0)
    db.set_setting("gemini_primary_quota_exceeded", "false")
    db.set_setting("gemini_backup_quota_exceeded", "false")
    db.set_setting("gemini_active_token_type", "primary")
    logger.info("Quota status reset: all API keys marked available, active key set to index 0.")

def get_tokens_status() -> Dict[str, Any]:
    keys = get_api_keys()
    exhausted = get_exhausted_keys()
    active_idx = get_active_key_index()
    if active_idx >= len(keys) and keys:
        active_idx = 0

    keys_status = []
    for i, k in enumerate(keys):
        is_exceeded = k in exhausted
        is_active = (i == active_idx and not is_exceeded)
        keys_status.append({
            "index": i,
            "key_number": i + 1,
            "masked": mask_key(k),
            "is_active": is_active,
            "quota_exceeded": is_exceeded
        })

    primary = keys[0] if len(keys) > 0 else None
    backup = keys[1] if len(keys) > 1 else None

    primary_exceeded = (primary in exhausted) if primary else False
    backup_exceeded = (backup in exhausted) if backup else False

    all_exceeded = len(keys) > 0 and all(k in exhausted for k in keys)

    if active_idx == 0:
        active_type = "primary"
    elif active_idx == 1:
        active_type = "backup"
    else:
        active_type = f"key_{active_idx + 1}"

    return {
        "keys": keys_status,
        "api_keys_list": keys_status,
        "keys_list": keys_status,
        "total_keys": len(keys),
        "active_index": active_idx,
        "active_key_masked": mask_key(keys[active_idx]) if keys and active_idx < len(keys) else "",
        "all_quotas_exceeded": all_exceeded,
        # Backward compatibility for Postman tests:
        "primary_configured": bool(primary),
        "primary_masked": mask_key(primary),
        "backup_configured": bool(backup),
        "backup_masked": mask_key(backup),
        "active_token_type": active_type,
        "primary_quota_exceeded": primary_exceeded,
        "backup_quota_exceeded": backup_exceeded,
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
    key = api_key
    if not key:
        keys = get_api_keys()
        exhausted = get_exhausted_keys()
        active_idx = get_active_key_index()
        if keys:
            if active_idx < len(keys) and keys[active_idx] not in exhausted:
                key = keys[active_idx]
            else:
                for k in keys:
                    if k not in exhausted:
                        key = k
                        break
                if not key:
                    key = keys[0]
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

    keys = get_api_keys()
    if not keys:
        raise ValueError("No hay ninguna clave GEMINI_API_KEY configurada en settings ni en variables de entorno.")

    exhausted = get_exhausted_keys()
    active_idx = get_active_key_index()
    if active_idx >= len(keys):
        active_idx = 0

    # Determine order of keys to try starting from active_idx:
    # First priority: keys that are not yet flagged as quota-exhausted
    indices_to_try = [
        (active_idx + i) % len(keys)
        for i in range(len(keys))
        if keys[(active_idx + i) % len(keys)] not in exhausted
    ]

    # If all configured keys are marked exhausted, try all in rotation in case quotas refreshed
    if not indices_to_try:
        indices_to_try = [(active_idx + i) % len(keys) for i in range(len(keys))]

    response = None
    token_used_index = None

    for idx in indices_to_try:
        key = keys[idx]
        key_label = f"Key #{idx + 1} ({mask_key(key)})"
        try:
            logger.info(f"Analyzing content using {key_label} on model='{active_model}': '{title}'")
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

            token_used_index = idx
            mark_key_available(key)
            set_active_key_index(idx)
            break

        except Exception as err:
            if is_quota_exceeded_error(err):
                logger.warning(f"[Gemini Quota Exceeded] {key_label} quota exceeded: {err}")
                mark_key_exhausted(key)
                next_idx = (idx + 1) % len(keys)
                set_active_key_index(next_idx)
                logger.info(f"Switching to next API key in rotation: Key #{next_idx + 1} ({mask_key(keys[next_idx])})...")
                continue
            else:
                raise err

    if response is None:
        for k in keys:
            mark_key_exhausted(k)
        logger.error(f"[Gemini Quota Exceeded] All {len(keys)} configured API keys have exceeded their quota!")
        raise AllTokensQuotaExceededError(
            f"La cuota de la API de Gemini se ha agotado en todas las claves configuradas ({len(keys)} claves). "
            "La solicitud debe ser diferida o enviada a DLX."
        )

    result_text = response.text or ""
    cleaned_text = re.sub(r"^\s*```(?:json)?\s*", "", result_text.strip(), flags=re.MULTILINE)
    cleaned_text = re.sub(r"\s*```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)

    try:
        res = json.loads(cleaned_text)
        res["modelUsed"] = active_model
        res["tokenUsed"] = f"key_{token_used_index + 1}"
        res["tokenIndex"] = token_used_index
        return res
    except json.JSONDecodeError as err:
        logger.error(f"Failed to parse JSON from Gemini: {err}\nRaw text: {result_text}")
        raise ValueError(f"Error al procesar la respuesta del modelo de IA: {err}")
