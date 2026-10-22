import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, Request, Form, Query, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import dotenv

from . import db
from . import rss
from . import gemini
from . import notion

dotenv.load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inviernoticias")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database tables on startup
    db.init_db()
    logger.info("Base de datos SQLite inicializada exitosamente.")
    yield

app = FastAPI(
    title="Inviernoticias API",
    description="Detector de Sátira, Sesgo y Noticias Falsas en México con IA",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ==========================================
# PYDANTIC SCHEMAS FOR REST API
# ==========================================
class FeedCreate(BaseModel):
    name: str
    url: str

class SyncPayload(BaseModel):
    feedId: Optional[int] = None
    limit: Optional[int] = 50
    dateRangeStart: Optional[str] = None
    dateRangeEnd: Optional[str] = None

class DirectAnalyzePayload(BaseModel):
    text: str
    title: Optional[str] = None

# ==========================================
# SERVER-SIDE RENDERED (SSR) HTML VIEWS
# (Zero JavaScript, 100% HTML5 & Pure CSS)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def view_articles(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    feed_id: Optional[int] = None,
    has_analysis: Optional[str] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None
):
    analysis_filter = None
    if has_analysis == "true":
        analysis_filter = True
    elif has_analysis == "false":
        analysis_filter = False

    articles = db.get_articles(limit=limit, offset=offset, feed_id=feed_id, has_analysis=analysis_filter)
    feeds = db.get_feeds()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "articles": articles,
            "feeds": feeds,
            "active_tab": "articles",
            "current_feed_id": feed_id,
            "current_has_analysis": has_analysis,
            "offset": offset,
            "limit": limit,
            "message": msg,
            "error": err
        }
    )

@app.get("/feeds", response_class=HTMLResponse)
async def view_feeds(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    feeds = db.get_feeds()
    return templates.TemplateResponse(
        request=request,
        name="feeds.html",
        context={
            "feeds": feeds,
            "active_tab": "feeds",
            "message": msg,
            "error": err
        }
    )

@app.get("/direct", response_class=HTMLResponse)
async def view_direct(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    return templates.TemplateResponse(
        request=request,
        name="direct.html",
        context={
            "active_tab": "direct",
            "result": None,
            "submitted_title": "",
            "submitted_text": "",
            "message": msg,
            "error": err
        }
    )

@app.post("/direct", response_class=HTMLResponse)
async def handle_direct_analysis_form(
    request: Request,
    title: Optional[str] = Form(None),
    text: str = Form(...)
):
    try:
        result = gemini.analyze_content(title=title or "Texto directo", content=text)
        return templates.TemplateResponse(
            request=request,
            name="direct.html",
            context={
                "active_tab": "direct",
                "result": result,
                "submitted_title": title,
                "submitted_text": text,
                "message": "Análisis completado exitosamente con Gemini 2.5 Flash."
            }
        )
    except Exception as e:
        logger.error(f"Error in direct analysis form: {e}")
        return templates.TemplateResponse(
            request=request,
            name="direct.html",
            context={
                "active_tab": "direct",
                "result": None,
                "submitted_title": title,
                "submitted_text": text,
                "error": f"Error al analizar texto: {e}"
            }
        )

@app.get("/articles/{article_id}", response_class=HTMLResponse)
async def view_article_detail(request: Request, article_id: int, msg: Optional[str] = None, err: Optional[str] = None):
    article = db.get_article_by_id(article_id)
    if not article:
        return RedirectResponse(url="/?err=Artículo+no+encontrado", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="article_detail.html",
        context={
            "article": article,
            "active_tab": "articles",
            "message": msg,
            "error": err
        }
    )

# ==========================================
# FORM ACTION CONTROLLERS (REDIRECTS)
# ==========================================

@app.post("/action/sync")
async def action_sync(
    feed_id: Optional[str] = Form(None),
    limit: Optional[int] = Form(50)
):
    fid = int(feed_id) if feed_id and feed_id.isdigit() else None
    try:
        sync_result = rss.sync_feed_articles(feed_id=fid, limit=limit or 50)
        msg = f"{sync_result['message']}"
        return RedirectResponse(url=f"/?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error syncing feeds: {e}")
        return RedirectResponse(url=f"/?err=Error+al+sincronizar:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/analyze/{article_id}")
async def action_analyze_article(article_id: int):
    article = db.get_article_by_id(article_id)
    if not article:
        return RedirectResponse(url="/?err=Artículo+no+encontrado", status_code=status.HTTP_303_SEE_OTHER)

    try:
        result = gemini.analyze_content(title=article["title"], content=article["content"] or "")
        db.update_article_analysis(article_id, result)
        return RedirectResponse(url=f"/articles/{article_id}?msg=Artículo+analizado+con+éxito", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error analyzing article {article_id}: {e}")
        return RedirectResponse(url=f"/articles/{article_id}?err=Error+en+el+análisis:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/notion/{article_id}")
async def action_notion_sync(article_id: int):
    article = db.get_article_by_id(article_id)
    if not article or not article.get("analysis_obj"):
        return RedirectResponse(url=f"/articles/{article_id}?err=El+artículo+debe+ser+analizado+primero", status_code=status.HTTP_303_SEE_OTHER)

    try:
        page_id = notion.publish_to_notion(article, article["analysis_obj"])
        db.update_article_notion_page(article_id, page_id)
        return RedirectResponse(url=f"/articles/{article_id}?msg=Publicado+en+Notion+con+éxito", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error exporting to Notion: {e}")
        return RedirectResponse(url=f"/articles/{article_id}?err=Error+al+publicar+en+Notion:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/feeds/add")
async def action_feed_add(name: str = Form(...), url: str = Form(...)):
    try:
        db.add_feed(url.strip(), name.strip())
        return RedirectResponse(url="/feeds?msg=Fuente+RSS+registrada+con+éxito", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return RedirectResponse(url=f"/feeds?err=Error+al+guardar+fuente:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/feeds/delete/{feed_id}")
async def action_feed_delete(feed_id: int):
    try:
        db.delete_feed(feed_id)
        return RedirectResponse(url="/feeds?msg=Fuente+eliminada+con+éxito", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return RedirectResponse(url=f"/feeds?err=Error+al+eliminar+fuente:+{e}", status_code=status.HTTP_303_SEE_OTHER)

# ==========================================
# REST API ENDPOINTS (100% POSTMAN COMPATIBLE)
# ==========================================

@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "service": "Inviernoticias API (Python/FastAPI)",
        "framework": "FastAPI + Jinja2 SSR",
        "javascript_free": True
    }

@app.get("/api/feeds")
async def api_get_feeds():
    return db.get_feeds()

@app.post("/api/feeds", status_code=status.HTTP_201_CREATED)
async def api_add_feed(payload: FeedCreate):
    try:
        db.add_feed(payload.url.strip(), payload.name.strip())
        return {"message": "Feed added successfully."}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=400, detail="Feed URL already exists.")
        raise HTTPException(status_code=500, detail=f"Failed to add feed: {e}")

@app.delete("/api/feeds/{feed_id}")
async def api_delete_feed(feed_id: int):
    success = db.delete_feed(feed_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feed not found or already deleted.")
    return {"message": "Feed deleted successfully."}

@app.get("/api/articles")
async def api_get_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    feedId: Optional[int] = Query(None),
    hasAnalysis: Optional[str] = Query(None)
):
    analysis_filter = None
    if hasAnalysis == "true":
        analysis_filter = True
    elif hasAnalysis == "false":
        analysis_filter = False

    articles = db.get_articles(limit=limit, offset=offset, feed_id=feedId, has_analysis=analysis_filter)
    return articles

@app.get("/api/articles/{article_id}")
async def api_get_article(article_id: int):
    article = db.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")
    return article

@app.post("/api/feeds/sync")
async def api_sync_feeds(payload: Optional[SyncPayload] = None):
    fid = payload.feedId if payload else None
    limit = payload.limit if payload and payload.limit else 50
    d_start = payload.dateRangeStart if payload else None
    d_end = payload.dateRangeEnd if payload else None

    try:
        result = rss.sync_feed_articles(
            feed_id=fid,
            limit=limit,
            date_range_start=d_start,
            date_range_end=d_end
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync feeds: {e}")

@app.post("/api/analyze")
async def api_analyze_direct(payload: DirectAnalyzePayload):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="News text is required.")

    try:
        result = gemini.analyze_content(title=payload.title or "Texto directo", content=payload.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during direct text analysis: {e}")

@app.post("/api/articles/{article_id}/analyze")
async def api_analyze_article(article_id: int):
    article = db.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")

    try:
        result = gemini.analyze_content(title=article["title"], content=article["content"] or "")
        db.update_article_analysis(article_id, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during analysis: {e}")

@app.api_route("/api/articles/{article_id}/notion", methods=["GET", "POST"])
async def api_sync_notion(article_id: int):
    article = db.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")

    if not article.get("analysis_obj"):
        raise HTTPException(status_code=400, detail="Article has not been analyzed yet. Run analysis first.")

    try:
        page_id = notion.publish_to_notion(article, article["analysis_obj"])
        db.update_article_notion_page(article_id, page_id)
        return {
            "message": "Articulo publicado en Notion con éxito.",
            "notionPageId": page_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync to Notion: {e}")
