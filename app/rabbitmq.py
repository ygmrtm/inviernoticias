import os
import json
import logging
from typing import Dict, Any, Optional
import pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

EXCHANGE_NAME = "articles.exchange"
DLX_EXCHANGE_NAME = "articles.dlx.exchange"

ANALYZE_QUEUE = "articles.analyze.queue"
NOTION_QUEUE = "articles.notion.queue"
RETRY_QUEUE = "articles.retry.queue"
FAILED_QUEUE = "articles.failed.queue"

RETRY_DELAY_MS = int(os.getenv("RABBITMQ_RETRY_DELAY_MS", "30000")) # 30 seconds delay before retry
MAX_RETRIES = int(os.getenv("RABBITMQ_MAX_RETRIES", "3"))

def get_connection():
    params = pika.URLParameters(RABBITMQ_URL)
    params.heartbeat = 60
    params.blocked_connection_timeout = 300
    params.socket_timeout = 2.0
    return pika.BlockingConnection(params)

def setup_rabbitmq(channel=None) -> bool:
    """
    Declares Exchanges, Queues, DLX and Bindings.
    Safe to run idempotently on startup, worker reconnect, or status inspection.
    """
    conn = None
    created_channel = False
    try:
        if channel is None:
            conn = get_connection()
            channel = conn.channel()
            created_channel = True

        # 1. Main Topic Exchange
        channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="topic",
            durable=True
        )

        # 2. Dead Letter Exchange (DLX)
        channel.exchange_declare(
            exchange=DLX_EXCHANGE_NAME,
            exchange_type="topic",
            durable=True
        )

        # 3. Analyze Queue with DLX configuration
        channel.queue_declare(
            queue=ANALYZE_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE_NAME,
                "x-dead-letter-routing-key": "article.dlx.analyze"
            }
        )
        channel.queue_bind(
            queue=ANALYZE_QUEUE,
            exchange=EXCHANGE_NAME,
            routing_key="article.analyze.#"
        )

        # 4. Notion Queue with DLX configuration (routing by article type, e.g. mockticia / realticia)
        channel.queue_declare(
            queue=NOTION_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE_NAME,
                "x-dead-letter-routing-key": "article.dlx.notion"
            }
        )
        channel.queue_bind(
            queue=NOTION_QUEUE,
            exchange=EXCHANGE_NAME,
            routing_key="article.notion.#"
        )

        # 5. Retry Queue (Delay buffer with TTL, dead-letters back to main exchange for reprocessing)
        channel.queue_declare(
            queue=RETRY_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": RETRY_DELAY_MS,
                "x-dead-letter-exchange": EXCHANGE_NAME  # Re-routes back to main exchange after TTL
            }
        )
        channel.queue_bind(
            queue=RETRY_QUEUE,
            exchange=DLX_EXCHANGE_NAME,
            routing_key="article.dlx.#"
        )

        # 6. Failed / Poison Queue (When max retries exceeded)
        channel.queue_declare(
            queue=FAILED_QUEUE,
            durable=True
        )
        channel.queue_bind(
            queue=FAILED_QUEUE,
            exchange=DLX_EXCHANGE_NAME,
            routing_key="article.failed.#"
        )

        if created_channel:
            channel.close()
            conn.close()

        logger.info("RabbitMQ Exchanges, Queues, and DLX topology initialized successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to setup RabbitMQ topology: {e}")
        if created_channel and conn and not conn.is_closed:
            try:
                conn.close()
            except Exception:
                pass
        return False

def get_queue_status() -> Dict[str, Any]:
    """
    Connects to RabbitMQ, ensures queues/topology exist (creating them if missing),
    and retrieves message counts.
    """
    try:
        conn = get_connection()
        try:
            channel = conn.channel()
            # Ensure topology (exchanges, queues, bindings) exists so passive=True never fails with 404
            setup_rabbitmq(channel=channel)

            q_analyze = channel.queue_declare(queue=ANALYZE_QUEUE, passive=True)
            q_notion = channel.queue_declare(queue=NOTION_QUEUE, passive=True)
            q_retry = channel.queue_declare(queue=RETRY_QUEUE, passive=True)
            q_failed = channel.queue_declare(queue=FAILED_QUEUE, passive=True)

            return {
                "status": "connected",
                "queues": {
                    ANALYZE_QUEUE: q_analyze.method.message_count,
                    NOTION_QUEUE: q_notion.method.message_count,
                    RETRY_QUEUE: q_retry.method.message_count,
                    FAILED_QUEUE: q_failed.method.message_count
                }
            }
        finally:
            if not conn.is_closed:
                conn.close()
    except Exception as e:
        return {
            "status": "disconnected",
            "error": str(e)
        }

def publish_message(routing_key: str, payload: Dict[str, Any], headers: Optional[Dict[str, Any]] = None):
    """
    Publishes a persistent message to the main articles exchange.
    """
    conn = get_connection()
    try:
        channel = conn.channel()
        channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)

        hdrs = headers or {}
        if "x-original-routing-key" not in hdrs:
            hdrs["x-original-routing-key"] = routing_key
        if "x-retry-count" not in hdrs:
            hdrs["x-retry-count"] = 0

        properties = pika.BasicProperties(
            delivery_mode=2,  # Make message persistent
            content_type="application/json",
            headers=hdrs
        )

        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
            body=json.dumps(payload, ensure_ascii=False),
            properties=properties
        )
        logger.info(f"Published message to exchange='{EXCHANGE_NAME}', routing_key='{routing_key}', payload={payload}")
    finally:
        conn.close()

def publish_analyze_request(article_id: int, feed_type: str = "general"):
    """
    Dispatches an 'analyze article request' to the exchange, routed by feed/article type.
    """
    clean_type = (feed_type or "general").strip().lower().replace(" ", "_")
    routing_key = f"article.analyze.{clean_type}"
    payload = {
        "article_id": article_id,
        "feed_type": clean_type
    }
    publish_message(routing_key=routing_key, payload=payload)

def publish_notion_request(article_id: int, article_type: str):
    """
    Dispatches a 'post in Notion' message to the exchange, routing by Type of Article (e.g. mockticia vs realticia).
    """
    clean_type = (article_type or "general").strip().lower().replace(" ", "_")
    routing_key = f"article.notion.{clean_type}"
    payload = {
        "article_id": article_id,
        "article_type": clean_type
    }
    publish_message(routing_key=routing_key, payload=payload)

def handle_consumer_failure(channel, method, properties, body_bytes: bytes, error_message: str):
    """
    Handles processing errors using DLX and retry counters.
    If retry_count < MAX_RETRIES, routes message to retry queue via DLX with original routing key.
    If retry_count >= MAX_RETRIES, routes message to failed queue.
    """
    headers = properties.headers or {}
    retry_count = int(headers.get("x-retry-count", 0)) + 1
    original_routing_key = headers.get("x-original-routing-key", method.routing_key)

    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        body = {"raw": body_bytes.decode("utf-8", errors="ignore")}

    body["last_error"] = str(error_message)

    if retry_count <= MAX_RETRIES:
        logger.warning(
            f"Message failed (Attempt {retry_count}/{MAX_RETRIES}). Routing to DLX retry queue for reprocessing in {RETRY_DELAY_MS}ms. "
            f"Original Key='{original_routing_key}', Error: {error_message}"
        )
        # Publish to DLX exchange with routing key that when dead-lettered after TTL will re-enter with original key
        # RabbitMQ dead-letter with original routing key:
        new_headers = dict(headers)
        new_headers["x-retry-count"] = retry_count

        # When dead-lettered back to main exchange, it uses the original routing key:
        channel.basic_publish(
            exchange=DLX_EXCHANGE_NAME,
            routing_key="article.dlx.retry",
            body=json.dumps(body, ensure_ascii=False),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=new_headers,
                # Setting CC or dead-letter parameters so after TTL it routes back to original_routing_key:
                expiration=str(RETRY_DELAY_MS)
            )
        )
    else:
        logger.error(
            f"Message exceeded MAX_RETRIES ({MAX_RETRIES}). Routing to FAILED queue '{FAILED_QUEUE}'. "
            f"Payload={body}, Error: {error_message}"
        )
        channel.basic_publish(
            exchange=DLX_EXCHANGE_NAME,
            routing_key="article.failed.max_retries",
            body=json.dumps(body, ensure_ascii=False),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=headers
            )
        )

    # Acknowledge original message to remove it from the processing queue (it has been forwarded to retry/failed)
    channel.basic_ack(delivery_tag=method.delivery_tag)
