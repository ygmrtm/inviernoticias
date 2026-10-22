import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from . import db

logger = logging.getLogger(__name__)

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

def get_genai_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno.")
    return genai.Client(api_key=api_key)

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
8. Contrast sources: use search grounding to verify the facts and suggest related real-news articles to contrast or check.

Provide the output in valid JSON format with exactly the following structure:
{{
  "isSatire": <true / false>,
  "truthScore": <number from 0 to 100>,
  "sarcasmScore": <number from 0 to 100>,
  "mexicoMagicoAward": <true / false>,
  "refran": "<Mexican refrán / saying>",
  "historicalQuote": "<Quote from historical figure or null>",
  "foreignerExplanation": "<Explanation for a foreigner>",
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

    client = get_genai_client()

    try:
        logger.info(f"Analyzing content using model='{active_model}' with Gemini Search Grounding: '{title}'")
        response = client.models.generate_content(
            model=active_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
    except Exception as search_err:
        logger.warning(f"Fallback to standard Gemini without search grounding on model '{active_model}': {search_err}")
        response = client.models.generate_content(
            model=active_model,
            contents=prompt
        )

    result_text = response.text or ""
    # Clean json formatting
    cleaned_text = re.sub(r"^\s*```(?:json)?\s*", "", result_text.strip(), flags=re.MULTILINE)
    cleaned_text = re.sub(r"\s*```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)

    try:
        res = json.loads(cleaned_text)
        res["modelUsed"] = active_model
        return res
    except json.JSONDecodeError as err:
        logger.error(f"Failed to parse JSON from Gemini: {err}\nRaw text: {result_text}")
        raise ValueError(f"Error al procesar la respuesta del modelo de IA: {err}")
