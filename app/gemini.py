import os
import re
import json
import logging
from typing import Dict, Any, Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def get_genai_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno.")
    return genai.Client(api_key=api_key)

def analyze_content(title: str, content: str) -> Dict[str, Any]:
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
        logger.info(f"Analyzing content with Gemini Search Grounding: '{title}'")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
    except Exception as search_err:
        logger.warning(f"Fallback to standard Gemini without search grounding: {search_err}")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

    result_text = response.text or ""
    # Clean json formatting
    cleaned_text = re.sub(r"^\s*```(?:json)?\s*", "", result_text.strip(), flags=re.MULTILINE)
    cleaned_text = re.sub(r"\s*```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError as err:
        logger.error(f"Failed to parse JSON from Gemini: {err}\nRaw text: {result_text}")
        raise ValueError(f"Error al procesar la respuesta del modelo de IA: {err}")
