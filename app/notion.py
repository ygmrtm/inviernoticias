import os
import re
import requests
import logging
from typing import Dict, Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1/pages"

def clean_database_id(raw_id: str) -> str:
    """Cleans and standardizes Notion database ID to a standard 32-character UUID."""
    if not raw_id:
        return ""
    cleaned = raw_id.strip()
    # If a Notion URL was provided, extract the path segment
    if "notion.so" in cleaned:
        cleaned = cleaned.split("?")[0].rstrip("/").split("/")[-1]
    
    # Strip any existing dashes or quotes
    hex_only = cleaned.replace("-", "").replace('"', '').replace("'", "")
    
    if len(hex_only) != 32:
        raise ValueError(
            f"NOTION_DATABASE_ID inválido: '{raw_id}'. "
            f"El ID debe tener exactamente 32 caracteres hexadecimales (tiene {len(hex_only)}). "
            "Verifica tu archivo .env ya que puede faltar algún dígito al copiarlo."
        )
    
    # Return formatted UUID: 8-4-4-4-12
    return f"{hex_only[:8]}-{hex_only[8:12]}-{hex_only[12:16]}-{hex_only[16:20]}-{hex_only[20:]}"

def publish_to_notion(article: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    load_dotenv(override=True)
    token = os.getenv("NOTION_TOKEN")
    raw_database_id = os.getenv("NOTION_DATABASE_ID")

    if not token or not raw_database_id:
        raise ValueError("Notion configuration is missing. Please set NOTION_TOKEN and NOTION_DATABASE_ID in your environment.")

    database_id = clean_database_id(raw_database_id)

    title = article.get("title") or "Noticia sin título"
    link = article.get("link") or "http://localhost"
    pub_date = article.get("pub_date")

    is_satire = analysis.get("isSatire", False)
    truth_score = analysis.get("truthScore", 0)
    sarcasm_score = analysis.get("sarcasmScore", 0)
    mexico_magico = analysis.get("mexicoMagicoAward", False)
    refran = analysis.get("refran", "N/A")
    summary = analysis.get("analysisSummary", "")
    foreigner_exp = analysis.get("foreignerExplanation", "")
    news_summary = analysis.get("newsSummary", "")
    cultural_ref = analysis.get("mexicanCultureReferences", "")
    hist_quote = analysis.get("historicalQuote", "")
    related_sources = analysis.get("relatedSources", [])

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    properties: Dict[str, Any] = {
        "Name": {
            "title": [{"text": {"content": title[:2000]}}]
        },
        "URL": {
            "url": link[:2000] if link else "http://localhost"
        },
        "Type": {
            "select": {"name": "Mock-ticia" if is_satire else "Real-ticia"}
        },
        "Truth %": {
            "number": round(float(truth_score) / 100.0, 2)
        },
        "Sarcasm %": {
            "number": round(float(sarcasm_score) / 100.0, 2)
        },
        "México Mágico": {
            "checkbox": bool(mexico_magico)
        },
        "Refrán": {
            "rich_text": [{"text": {"content": (refran or "N/A")[:2000]}}]
        }
    }

    if pub_date:
        properties["Published Date"] = {
            "date": {"start": pub_date}
        }

    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Resumen de la Noticia"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": (news_summary or "Sin resumen disponible.")[:2000]}}]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Resumen del Análisis"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": (summary or "Sin resumen disponible.")[:2000]}}]
            }
        },        
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Explicación para Extranjeros"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": (foreigner_exp or "N/A")[:2000]}}]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Referencias Culturales y Citas Históricas"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"Referencias: {cultural_ref or 'Ninguna'}\n\nCita Histórica: {hist_quote or 'Ninguna'}"[:2000]
                        }
                    }
                ]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Fuentes y Búsqueda Relacionada"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "\n".join(related_sources) if isinstance(related_sources, list) else str(related_sources or "N/A")[:2000]
                        }
                    }
                ]
            }
        }
    ]

    payload = {
        "parent": {"database_id": database_id},
        "icon" : { "emoji" : "📰" if is_satire else "🗞️" },
        "properties": properties,
        "children": children
    }

    response = requests.post(NOTION_API_URL, headers=headers, json=payload, timeout=15)
    if response.status_code >= 400:
        logger.error(f"Notion API error: {response.status_code} - {response.text}")
        raise ValueError(f"Error de Notion API: {response.text}")

    data = response.json()
    return data.get("id", "")
