import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, Request, Form, Query, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import dotenv

from . import db
from . import rss
from . import gemini
from . import notion
from . import rabbitmq
from . import worker
from . import cron
from . import scheduler

dotenv.load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inviernoticias")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize SQLite database
    db.init_db()
    logger.info("Base de datos SQLite inicializada exitosamente.")

    # 2. Setup RabbitMQ topology if available
    enable_rabbitmq = os.getenv("ENABLE_RABBITMQ", "true").lower() in ("true", "1", "yes")
    if enable_rabbitmq:
        try:
            rabbitmq.setup_rabbitmq()
        except Exception as e:
            logger.warning(f"RabbitMQ no disponible al inicio ({e}). Las conexiones se reintentarán al publicar/consumir.")

    # 3. Start Background Consumer Workers
    enable_workers = os.getenv("ENABLE_WORKERS", "true").lower() in ("true", "1", "yes")
    if enable_workers:
        try:
            worker.worker_service.start_all()
        except Exception as e:
            logger.warning(f"No se pudieron iniciar los workers de RabbitMQ: {e}")

    # 4. Start APScheduler (loads saved configuration from DB or starts default)
    enable_cron = os.getenv("ENABLE_CRON", "true").lower() in ("true", "1", "yes")
    if enable_cron:
        try:
            scheduler.load_and_start_from_db()
        except Exception as e:
            logger.warning(f"No se pudo iniciar el scheduler de cron: {e}")

    yield

    # Graceful shutdown
    worker.worker_service.stop_all()
    scheduler.stop_scheduler()

APP_VERSION = os.getenv("APP_VERSION", "2.1.0")
APP_RELEASE = os.getenv("APP_RELEASE", "2026.10.29")

app = FastAPI(
    title="Inviernoticias API",
    description="Detector de Sátira, Sesgo y Noticias Falsas en México con IA",
    version=APP_VERSION,
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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_ico = BASE_DIR / "static" / "favicon.ico"
    if favicon_ico.exists():
        return FileResponse(str(favicon_ico), media_type="image/x-icon")
    return FileResponse(str(BASE_DIR / "static" / "favicon.svg"), media_type="image/svg+xml")

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

class CronTriggerPayload(BaseModel):
    feedId: Optional[int] = None
    hours: Optional[int] = 24

class ModelSelectPayload(BaseModel):
    model: str

class SchedulerStartPayload(BaseModel):
    startTime: Optional[str] = None
    intervalHours: Optional[int] = 24
    hour: Optional[int] = None
    minute: Optional[int] = None
    startImmediately: Optional[bool] = False

class SqlExecutePayload(BaseModel):
    query: str

class TokenUpdatePayload(BaseModel):
    primaryKey: Optional[str] = None
    backupKey: Optional[str] = None

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

@app.get("/settings", response_class=HTMLResponse)
async def view_settings(
    request: Request,
    sql: Optional[str] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None
):
    models = gemini.get_available_models()
    scheduler_status = scheduler.get_scheduler_status()
    tokens_status = gemini.get_tokens_status()
    feeds = db.get_feeds()
    
    sql_result = None
    if sql and sql.strip():
        sql_result = db.execute_sql_query(sql.strip())

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_tab": "settings",
            "models": models,
            "scheduler_status": scheduler_status,
            "tokens_status": tokens_status,
            "sql_result": sql_result,
            "last_sql": sql or "SELECT id, title, link, created_at FROM articles LIMIT 5;",
            "feeds": feeds,
            "message": msg,
            "error": err
        }
    )

# ==========================================
# FORM ACTION CONTROLLERS (REDIRECTS)
# ==========================================

@app.post("/action/cron/trigger")
async def action_cron_trigger(feed_id: Optional[str] = Form(None)):
    fid = int(feed_id) if feed_id and feed_id.isdigit() else None
    try:
        summary = cron.run_24h_cron_sync_and_analyze(feed_id=fid, hours_back=24)
        msg = f"CronJob 24h ejecutado: {summary.get('synced_count', 0)} importados, {summary.get('dispatched_count', 0)} enviados a RabbitMQ."
        return RedirectResponse(url=f"/?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error triggering 24h cronjob: {e}")
        return RedirectResponse(url=f"/?err=Error+en+CronJob:+{e}", status_code=status.HTTP_303_SEE_OTHER)

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

@app.post("/action/settings/model")
async def action_settings_model(model: str = Form(...)):
    try:
        gemini.set_default_model(model.strip())
        return RedirectResponse(
            url=f"/settings?msg=Modelo+predeterminado+actualizado+a+{model.strip()}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error updating default model: {e}")
        return RedirectResponse(
            url=f"/settings?err=Error+al+actualizar+modelo:+{e}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@app.post("/action/settings/scheduler")
async def action_settings_scheduler(
    start_time: Optional[str] = Form(None),
    interval_hours: Optional[int] = Form(24),
    hour: Optional[str] = Form(None),
    minute: Optional[str] = Form(None),
    start_immediately: Optional[str] = Form(None)
):
    try:
        h = int(hour) if hour and hour.strip().isdigit() else None
        m = int(minute) if minute and minute.strip().isdigit() else None
        imm = True if start_immediately in ("true", "1", "on", "yes") else False
        res = scheduler.start_scheduler(
            start_time=start_time.strip() if start_time and start_time.strip() else None,
            interval_hours=interval_hours if interval_hours else 24,
            hour=h,
            minute=m,
            start_immediately=imm
        )
        msg = f"Scheduler+iniciado+correctamente.+Próxima+ejecución:+{res.get('next_run_time', 'N/A')}"
        return RedirectResponse(url=f"/settings?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        return RedirectResponse(url=f"/settings?err=Error+al+iniciar+scheduler:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/settings/scheduler/stop")
async def action_settings_scheduler_stop():
    try:
        scheduler.stop_scheduler()
        return RedirectResponse(url="/settings?msg=Scheduler+detenido+con+éxito", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        return RedirectResponse(url=f"/settings?err=Error+al+detener+scheduler:+{e}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/action/settings/sql", response_class=HTMLResponse)
async def action_settings_sql(
    request: Request,
    sql_query: str = Form(...)
):
    models = gemini.get_available_models()
    scheduler_status = scheduler.get_scheduler_status()
    tokens_status = gemini.get_tokens_status()
    feeds = db.get_feeds()

    sql_result = db.execute_sql_query(sql_query)

    msg = "Consulta SQL ejecutada correctamente." if sql_result.get("type") != "error" else None
    err = f"Error SQL: {sql_result.get('error')}" if sql_result.get("type") == "error" else None

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_tab": "settings",
            "models": models,
            "scheduler_status": scheduler_status,
            "tokens_status": tokens_status,
            "sql_result": sql_result,
            "last_sql": sql_query,
            "feeds": feeds,
            "message": msg,
            "error": err
        }
    )

@app.post("/action/settings/tokens")
async def action_settings_tokens(
    primary_key: Optional[str] = Form(None),
    backup_key: Optional[str] = Form(None)
):
    try:
        gemini.set_tokens(
            primary_key=primary_key.strip() if primary_key and primary_key.strip() else None,
            backup_key=backup_key.strip() if backup_key and backup_key.strip() else None
        )
        return RedirectResponse(
            url="/settings?msg=Tokens+de+Gemini+actualizados+exitosamente",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error saving tokens: {e}")
        return RedirectResponse(
            url=f"/settings?err=Error+al+guardar+tokens:+{e}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@app.post("/action/settings/tokens/reset")
async def action_settings_tokens_reset():
    try:
        gemini.reset_quota_status()
        return RedirectResponse(
            url="/settings?msg=Estado+de+cuotas+reiniciado.+Token+principal+reactivado.",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error resetting token quota: {e}")
        return RedirectResponse(
            url=f"/settings?err=Error+al+reiniciar+cuota:+{e}",
            status_code=status.HTTP_303_SEE_OTHER
        )

# ==========================================
# REST API ENDPOINTS (100% POSTMAN COMPATIBLE)
# ==========================================

@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "service": "Inviernoticias API (Python/FastAPI)",
        "version": APP_VERSION,
        "release": APP_RELEASE,
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
    except gemini.AllTokensQuotaExceededError as qe:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(qe))
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
    except gemini.AllTokensQuotaExceededError as qe:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(qe))
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

# ==========================================
# CRON & RABBITMQ ENDPOINTS
# ==========================================

@app.post("/api/cron/trigger")
async def api_cron_trigger(payload: Optional[CronTriggerPayload] = None):
    fid = payload.feedId if payload else None
    hrs = payload.hours if payload and payload.hours else 24
    try:
        summary = cron.run_24h_cron_sync_and_analyze(feed_id=fid, hours_back=hrs)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing 24hr CronJob: {e}")

@app.get("/api/cron/status")
async def api_cron_status():
    return scheduler.get_scheduler_status()

@app.get("/api/queue/status")
async def api_queue_status():
    return rabbitmq.get_queue_status()

# ==========================================
# AI MODEL CONFIGURATION ENDPOINTS
# ==========================================

@app.get("/api/models")
async def api_get_models():
    """
    Returns the list of curated Gemini AI models suitable for Mexican satire/bias fact-checking,
    with their capabilities, recommendations, and the currently active default model flagged.
    """
    return {
        "models": gemini.get_available_models(),
        "current_default": gemini.get_selected_model()
    }

@app.post("/api/models/default")
async def api_set_default_model(payload: ModelSelectPayload):
    """
    Selects and persists the default Gemini model used across all automated and direct analyses.
    """
    try:
        updated = gemini.set_default_model(payload.model.strip())
        return {
            "message": f"Modelo de IA predeterminado establecido exitosamente en '{updated}'.",
            "default_model": updated
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al configurar el modelo de IA: {e}")

# ==========================================
# PARAMETRIZED SCHEDULER MANAGEMENT ENDPOINTS
# ==========================================

@app.post("/api/scheduler/start")
async def api_scheduler_start(payload: Optional[SchedulerStartPayload] = None):
    """
    Starts or reconfigures the background scheduler with custom timing parameters.
    - startTime: ISO 8601 datetime (e.g. '2026-10-23T02:00:00Z') or 'HH:MM' (e.g. '03:00')
    - intervalHours: Recurrence interval in hours (default 24)
    - hour / minute: Specific daily execution time (e.g. hour=2, minute=0 for 2:00 AM daily)
    - startImmediately: If true, runs one execution cycle immediately in addition to scheduling
    """
    p = payload or SchedulerStartPayload()
    try:
        res = scheduler.start_scheduler(
            start_time=p.startTime,
            interval_hours=p.intervalHours,
            hour=p.hour,
            minute=p.minute,
            start_immediately=bool(p.startImmediately)
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al iniciar el scheduler: {e}")

@app.post("/api/scheduler/stop")
async def api_scheduler_stop():
    """
    Stops the background scheduler and cancels pending recurring executions.
    """
    try:
        return scheduler.stop_scheduler()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al detener el scheduler: {e}")

@app.get("/api/scheduler/status")
async def api_scheduler_status():
    """
    Returns the current execution state, active job, next run time, and saved configuration of the scheduler.
    """
    return scheduler.get_scheduler_status()

# ==========================================
# SQL CONSOLE & DATABASE ADMINISTRATION
# ==========================================

@app.post("/api/sql/execute")
async def api_sql_execute(payload: SqlExecutePayload):
    """
    Executes an arbitrary SQL statement against the internal SQLite database.
    Supports SELECT, PRAGMA, EXPLAIN, WITH, INSERT, UPDATE, DELETE, DDL.
    """
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="SQL query string cannot be empty.")
    result = db.execute_sql_query(payload.query)
    if result.get("type") == "error":
        return JSONResponse(status_code=400, content=result)
    return result

# ==========================================
# GEMINI API TOKENS & QUOTA MANAGEMENT
# ==========================================

@app.get("/api/tokens/status")
async def api_tokens_status():
    """
    Returns the configuration and quota health status of primary and backup Gemini API tokens.
    """
    return gemini.get_tokens_status()

@app.post("/api/tokens")
async def api_set_tokens(payload: TokenUpdatePayload):
    """
    Configures and persists the primary and/or backup Gemini API tokens.
    """
    try:
        gemini.set_tokens(primary_key=payload.primaryKey, backup_key=payload.backupKey)
        return {
            "message": "Tokens de Gemini actualizados exitosamente.",
            "status": gemini.get_tokens_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar tokens de Gemini: {e}")

@app.post("/api/tokens/reset-quota")
async def api_reset_tokens_quota():
    """
    Resets quota-exhausted flags and restores primary token as the active analyzer.
    """
    try:
        gemini.reset_quota_status()
        return {
            "message": "Estado de cuotas reiniciado. Token principal reactivado.",
            "status": gemini.get_tokens_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al reiniciar estado de cuota: {e}")
