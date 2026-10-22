import os
import logging
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Optional, Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from . import cron
from . import db

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

JOB_ID = "24h_feed_sync_and_analyze"

def scheduled_job_wrapper():
    logger.info("[Scheduler] Executing scheduled 24h cronjob...")
    try:
        cron.run_24h_cron_sync_and_analyze()
    except Exception as e:
        logger.error(f"[Scheduler] Error executing scheduled 24h cron: {e}", exc_info=True)

def parse_start_time(start_time_str: str) -> datetime:
    """
    Parses start_time into a datetime object.
    Supports:
    1. ISO format: "2026-10-22T15:30:00Z", "2026-10-22T15:30:00"
    2. Time-only format: "15:30" or "02:00" (calculates next occurrence today or tomorrow)
    """
    now = datetime.now()
    clean_str = start_time_str.strip()

    # Time-only: HH:MM
    if ":" in clean_str and len(clean_str) in (4, 5) and "T" not in clean_str and "-" not in clean_str:
        parts = clean_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        target_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target_today > now:
            return target_today
        else:
            return target_today + timedelta(days=1)

    # Full datetime format
    # Replace trailing Z for fromisoformat compatibility
    clean_iso = clean_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean_iso)
        # If naive, make local
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception as e:
        logger.warning(f"Could not parse start_time '{start_time_str}' as ISO: {e}. Falling back to now.")
        return now

def start_scheduler(
    start_time: Optional[str] = None,
    interval_hours: Optional[int] = None,
    hour: Optional[int] = None,
    minute: Optional[int] = None,
    start_immediately: bool = False
) -> Dict[str, Any]:
    """
    Configures and starts/restarts the scheduler with parametrized start timing.
    - start_time: ISO datetime string or 'HH:MM' time string for first execution.
    - interval_hours: Recurrence interval (defaults to 24 or env CRON_INTERVAL_HOURS).
    - hour / minute: Specific daily time for CronTrigger (e.g. hour=2, minute=0 for 02:00 AM daily).
    - start_immediately: If True, executes once immediately and then follows schedule.
    """
    # Fallback to env or defaults
    env_interval = int(os.getenv("CRON_INTERVAL_HOURS", "24"))
    hrs = interval_hours if interval_hours is not None else env_interval
    hrs = max(1, hrs)

    # Build trigger
    first_run_date = None
    trigger_desc = ""

    if hour is not None:
        min_val = minute if minute is not None else 0
        trigger = CronTrigger(hour=hour, minute=min_val)
        trigger_desc = f"Diario a las {hour:02d}:{min_val:02d}"
    else:
        if start_time:
            first_run_date = parse_start_time(start_time)
            trigger = IntervalTrigger(hours=hrs, start_date=first_run_date)
            trigger_desc = f"Cada {hrs}h a partir de {first_run_date.strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            trigger = IntervalTrigger(hours=hrs)
            trigger_desc = f"Cada {hrs}h desde el inicio"

    # Add or replace the job
    job = scheduler.add_job(
        scheduled_job_wrapper,
        trigger=trigger,
        id=JOB_ID,
        name="Inviernoticias 24hr Feed Sync & RabbitMQ Dispatch",
        replace_existing=True
    )

    if not scheduler.running:
        scheduler.start()

    # If requested to run immediately
    if start_immediately:
        logger.info("[Scheduler] 'start_immediately' requested. Dispatched immediate job execution.")
        scheduler.add_job(scheduled_job_wrapper, id="immediate_run_once")

    # Persist parameters in DB
    try:
        db.set_setting("scheduler_enabled", "true")
        db.set_setting("scheduler_interval_hours", str(hrs))
        if start_time:
            db.set_setting("scheduler_start_time", str(start_time))
        if hour is not None:
            db.set_setting("scheduler_hour", str(hour))
        if minute is not None:
            db.set_setting("scheduler_minute", str(minute))
    except Exception as e:
        logger.warning(f"Could not persist scheduler settings to DB: {e}")

    logger.info(f"Scheduler configured successfully: {trigger_desc}. Next execution: {job.next_run_time}")

    return {
        "status": "started",
        "job_id": JOB_ID,
        "trigger": trigger_desc,
        "interval_hours": hrs,
        "first_run_date": str(first_run_date) if first_run_date else None,
        "next_run_time": str(job.next_run_time) if job.next_run_time else None,
        "running": scheduler.running
    }

def stop_scheduler() -> Dict[str, Any]:
    """
    Stops the scheduled job and pauses the scheduler.
    """
    try:
        job = scheduler.get_job(JOB_ID)
        if job:
            scheduler.remove_job(JOB_ID)
    except Exception as e:
        logger.warning(f"Error removing job {JOB_ID}: {e}")

    try:
        db.set_setting("scheduler_enabled", "false")
    except Exception:
        pass

    logger.info("Scheduler job stopped and removed.")
    return {
        "status": "stopped",
        "running": scheduler.running
    }

def get_scheduler_status() -> Dict[str, Any]:
    """
    Returns full diagnostics of the scheduler, next run time, and saved configuration.
    """
    job = None
    if scheduler.running:
        job = scheduler.get_job(JOB_ID)

    saved_settings = {}
    try:
        saved_settings = {
            "enabled": db.get_setting("scheduler_enabled", "true") == "true",
            "interval_hours": db.get_setting("scheduler_interval_hours", "24"),
            "start_time": db.get_setting("scheduler_start_time"),
            "hour": db.get_setting("scheduler_hour"),
            "minute": db.get_setting("scheduler_minute")
        }
    except Exception:
        pass

    return {
        "running": scheduler.running,
        "has_active_job": job is not None,
        "job_id": JOB_ID if job else None,
        "next_run_time": str(job.next_run_time) if job and job.next_run_time else None,
        "saved_config": saved_settings
    }

def load_and_start_from_db():
    """
    Called on server startup to restore previously saved schedule parameters.
    """
    try:
        enabled = db.get_setting("scheduler_enabled", "true") == "true"
        if not enabled:
            logger.info("Scheduler disabled in saved settings. Skipping autostart.")
            return

        start_time = db.get_setting("scheduler_start_time")
        interval_hours = db.get_setting("scheduler_interval_hours")
        hour_val = db.get_setting("scheduler_hour")
        minute_val = db.get_setting("scheduler_minute")

        start_scheduler(
            start_time=start_time,
            interval_hours=int(interval_hours) if interval_hours and interval_hours.isdigit() else None,
            hour=int(hour_val) if hour_val and hour_val.isdigit() else None,
            minute=int(minute_val) if minute_val and minute_val.isdigit() else None,
            start_immediately=False
        )
    except Exception as e:
        logger.warning(f"Could not load scheduler settings from DB, using defaults: {e}")
        start_scheduler()
