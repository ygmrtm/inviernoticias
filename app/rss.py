import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any, List
from . import db

def parse_published_date(entry: Any) -> datetime:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    if hasattr(entry, "published") and entry.published:
        try:
            return parsedate_to_datetime(entry.published)
        except Exception:
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6])
        except Exception:
            pass
    return datetime.utcnow()

def sync_feed_articles(
    feed_id: Optional[int] = None,
    limit: int = 50,
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None
) -> Dict[str, Any]:
    if feed_id:
        feed = db.get_feed_by_id(feed_id)
        if not feed:
            raise ValueError("Feed not found")
        feeds_to_sync = [feed]
    else:
        feeds_to_sync = db.get_feeds()

    start_dt = None
    if date_range_start:
        try:
            start_dt = datetime.fromisoformat(date_range_start.replace("Z", "+00:00"))
        except Exception:
            pass

    end_dt = None
    if date_range_end:
        try:
            end_dt = datetime.fromisoformat(date_range_end.replace("Z", "+00:00"))
        except Exception:
            pass

    total_synced = 0

    for feed in feeds_to_sync:
        parsed = feedparser.parse(feed["url"])
        count = 0
        for entry in parsed.entries:
            if count >= limit:
                break

            pub_date = parse_published_date(entry)
            
            # Simple timezone-naive comparison if needed
            pub_date_cmp = pub_date.replace(tzinfo=None) if pub_date.tzinfo else pub_date
            if start_dt:
                s_cmp = start_dt.replace(tzinfo=None) if start_dt.tzinfo else start_dt
                if pub_date_cmp < s_cmp:
                    continue
            if end_dt:
                e_cmp = end_dt.replace(tzinfo=None) if end_dt.tzinfo else end_dt
                if pub_date_cmp > e_cmp:
                    continue

            guid = getattr(entry, "id", None) or getattr(entry, "link", None) or f"{feed['id']}-{int(pub_date_cmp.timestamp())}-{count}"
            raw_title = getattr(entry, "title", "Sin Título")
            title = db.clean_html_text(raw_title)
            link = getattr(entry, "link", "")
            
            # Content / summary snippet
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].value
            elif hasattr(entry, "summary") and entry.summary:
                content = entry.summary
            elif hasattr(entry, "description") and entry.description:
                content = entry.description
            content = db.clean_html_text(content)

            added = db.add_article(
                feed_id=feed["id"],
                guid=guid,
                title=title,
                link=link,
                pub_date=pub_date.isoformat(),
                content=content
            )
            if added:
                total_synced += 1
            count += 1

    return {
        "message": f"Sincronización completada. {total_synced} artículos nuevos importados.",
        "syncedCount": total_synced
    }
