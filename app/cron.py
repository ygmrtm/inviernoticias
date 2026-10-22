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
    CronJob executed every 24 hours:
    1. Computes end_date = now(), start_date = now() - 24 hours.
    2. Requests Sync of a specific/configured Feed.
    3. Lists all Unanalysed articles for that feed (or global unanalyzed).
    4. Dispatches an 'analyze article request' to the RabbitMQ exchange for each article.
    """
    # 1. Determine Feed to sync
    configured_feed_id = feed_id
    if configured_feed_id is None:
        env_feed = os.getenv("CRON_FEED_ID")
        if env_feed and env_feed.isdigit():
            configured_feed_id = int(env_feed)

    target_feed = None
    if configured_feed_id:
        target_feed = db.get_feed_by_id(configured_feed_id)

    if not target_feed:
        # Fallback to the first feed found in DB
        all_feeds = db.get_feeds()
        if all_feeds:
            target_feed = all_feeds[0]
            configured_feed_id = target_feed["id"]
        else:
            logger.warning("No feeds configured in database. Cannot run 24h cron sync.")
            return {
                "status": "error",
                "message": "No feeds configured in database."
            }

    # 2. Compute date window: start_date is 24 hours back, end_date is now
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(hours=hours_back)

    start_date_iso = start_date.isoformat()
    end_date_iso = end_date.isoformat()

    logger.info(
        f"[CronJob] Starting 24hr process for Feed '{target_feed['name']}' (ID: {configured_feed_id}). "
        f"Window: [{start_date_iso} --> {end_date_iso}]"
    )

    # 3. Request Sync for the specific feed
    sync_result = rss.sync_feed_articles(
        feed_id=configured_feed_id,
        date_range_start=start_date_iso,
        date_range_end=end_date_iso,
        limit=100
    )
    logger.info(f"[CronJob] Feed sync complete: {sync_result['message']}")

    # 4. List all Unanalysed articles
    unanalyzed_articles = db.get_articles(
        feed_id=configured_feed_id,
        has_analysis=False,
        limit=500
    )
    logger.info(f"[CronJob] Found {len(unanalyzed_articles)} unanalyzed articles to dispatch to RabbitMQ.")

    # 5. Publish an 'analyze article request' to the Exchange for each article
    dispatched_ids = []
    feed_type = target_feed["name"].lower().replace(" ", "_")

    # Ensure RabbitMQ topology exists
    try:
        rabbitmq.setup_rabbitmq()
    except Exception as e:
        logger.warning(f"Could not verify RabbitMQ topology: {e}")

    for article in unanalyzed_articles:
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
        "feed_id": configured_feed_id,
        "feed_name": target_feed["name"],
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
