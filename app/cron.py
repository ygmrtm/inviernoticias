import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from . import db
from . import rss
from . import rabbitmq

logger = logging.getLogger(__name__)

def run_24h_cron_sync_and_analyze(
    feed_id: Optional[int] = None,
    hours_back: int = 24
) -> Dict[str, Any]:
    """
    CronJob executed periodically (e.g. every 24 hours):
    1. Computes end_date = now(), start_date = now() - hours_back.
    2. Requests Sync of feeds:
       - If feed_id is provided, syncs that specific feed.
       - If feed_id is None, syncs ALL feeds configured in the database.
    3. Lists all unanalyzed articles for the selected feed(s).
    4. Dispatches an 'analyze article request' to the RabbitMQ exchange for each article,
       routed by that article's feed type.
    """
    # 1. Determine Feeds to sync
    if feed_id is not None:
        target_feed = db.get_feed_by_id(feed_id)
        if not target_feed:
            logger.warning(f"Feed with ID {feed_id} not found in database.")
            return {
                "status": "error",
                "message": f"Feed with ID {feed_id} not found in database."
            }
        feeds_to_process = [target_feed]
        feed_sync_target = feed_id
        feed_query_target = feed_id
        scope_desc = f"Feed '{target_feed['name']}' (ID: {feed_id})"
    else:
        feeds_to_process = db.get_feeds()
        if not feeds_to_process:
            logger.warning("No feeds configured in database. Cannot run cron sync.")
            return {
                "status": "error",
                "message": "No feeds configured in database."
            }
        feed_sync_target = None
        feed_query_target = None
        names_str = ", ".join([f["name"] for f in feeds_to_process])
        scope_desc = f"ALL feeds ({len(feeds_to_process)} feeds configured: {names_str})"

    # 2. Compute date window: start_date is hours_back back, end_date is now
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(hours=hours_back)

    start_date_iso = start_date.isoformat()
    end_date_iso = end_date.isoformat()

    logger.info(
        f"[CronJob] Starting process for {scope_desc}. "
        f"Window: [{start_date_iso} --> {end_date_iso}]"
    )

    # 3. Request Sync for the feed(s)
    sync_result = rss.sync_feed_articles(
        feed_id=feed_sync_target,
        date_range_start=start_date_iso,
        date_range_end=end_date_iso,
        limit=100
    )
    logger.info(f"[CronJob] Feeds sync complete: {sync_result.get('message', '')}")

    # 4. List all Unanalysed articles
    unanalyzed_articles = db.get_articles(
        feed_id=feed_query_target,
        has_analysis=False,
        limit=500
    )
    logger.info(f"[CronJob] Found {len(unanalyzed_articles)} unanalyzed articles to dispatch to RabbitMQ.")

    # 5. Ensure RabbitMQ topology exists
    try:
        rabbitmq.setup_rabbitmq()
    except Exception as e:
        logger.warning(f"Could not verify RabbitMQ topology: {e}")

    # 6. Publish an 'analyze article request' to the Exchange for each article
    dispatched_ids = []
    for article in unanalyzed_articles:
        feed_name = article.get("feed_name") or "general"
        feed_type = feed_name.strip().lower().replace(" ", "_")
        try:
            rabbitmq.publish_analyze_request(
                article_id=article["id"],
                feed_type=feed_type
            )
            dispatched_ids.append(article["id"])
        except Exception as pub_err:
            logger.error(f"[CronJob] Failed to dispatch article ID {article['id']} to RabbitMQ: {pub_err}")

    summary = {
        "status": "success",
        "feed_id": feed_id,
        "feeds_count": len(feeds_to_process),
        "feed_names": [f["name"] for f in feeds_to_process],
        "start_date": start_date_iso,
        "end_date": end_date_iso,
        "synced_count": sync_result.get("syncedCount", 0),
        "dispatched_count": len(dispatched_ids),
        "dispatched_ids": dispatched_ids,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    logger.info(f"[CronJob] Execution completed successfully: {summary}")
    return summary

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Executing 24hr CronJob manually from CLI...")
    result = run_24h_cron_sync_and_analyze()
    print("\nCronJob Summary Result:")
    import pprint
    pprint.pprint(result)
