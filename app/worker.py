import json
import logging
import threading
import time
from typing import Optional
import pika

from . import db
from . import gemini
from . import notion
from . import rabbitmq

logger = logging.getLogger(__name__)

class WorkerService:
    def __init__(self):
        self.should_stop = False
        self.threads = []

    def start_analyzer_consumer(self):
        """
        Subscribed process for reading 'articles.analyze.queue',
        executing AI analysis, updating DB, and publishing to the Notion queue.
        """
        while not self.should_stop:
            try:
                conn = rabbitmq.get_connection()
                channel = conn.channel()
                # Ensure queues and topology exist before consuming
                rabbitmq.setup_rabbitmq(channel=channel)
                channel.basic_qos(prefetch_count=1)

                def on_analyze_message(ch, method, properties, body):
                    try:
                        data = json.loads(body.decode("utf-8"))
                        article_id = data.get("article_id")
                        logger.info(f"Received Analyze Request for Article ID: {article_id}")

                        article = db.get_article_by_id(article_id)
                        if not article:
                            logger.warning(f"Article ID {article_id} not found in database. Acknowledging message.")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        # Check if already analyzed
                        if article.get("analysis_obj"):
                            analysis_result = article["analysis_obj"]
                            logger.info(f"Article ID {article_id} already has analysis. Skipping AI call.")
                        else:
                            # Run Gemini Analysis
                            analysis_result = gemini.analyze_content(
                                title=article["title"],
                                content=article.get("content") or ""
                            )
                            db.update_article_analysis(article_id, analysis_result)
                            logger.info(f"Successfully analyzed Article ID {article_id} with Gemini.")

                        # Determine Type of Article: Mock-ticia (satire) vs Real-ticia (real)
                        is_satire = analysis_result.get("isSatire", False)
                        article_type = "mockticia" if is_satire else "realticia"

                        # Post message to Exchange for 'post in Notion', routed by Type of Article
                        rabbitmq.publish_notion_request(article_id=article_id, article_type=article_type)

                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        logger.info(f"Article ID {article_id} processed & forwarded to Notion queue with type='{article_type}'.")

                    except Exception as e:
                        logger.error(f"Error processing Analyze Request: {e}", exc_info=True)
                        rabbitmq.handle_consumer_failure(ch, method, properties, body, str(e))

                channel.basic_consume(
                    queue=rabbitmq.ANALYZE_QUEUE,
                    on_message_callback=on_analyze_message,
                    auto_ack=False
                )
                logger.info(f"[*] Analyzer Consumer started. Waiting for messages on '{rabbitmq.ANALYZE_QUEUE}'...")
                channel.start_consuming()

            except pika.exceptions.AMQPConnectionError as conn_err:
                if self.should_stop:
                    break
                logger.warning(f"RabbitMQ connection lost in Analyzer Consumer: {conn_err}. Reconnecting in 5s...")
                time.sleep(5)
            except Exception as e:
                if self.should_stop:
                    break
                logger.error(f"Unexpected error in Analyzer Consumer: {e}. Reconnecting in 5s...")
                time.sleep(5)

    def start_notion_consumer(self):
        """
        Subscribed process for reading 'articles.notion.queue',
        and posting the analyzed article into the Notion Database.
        """
        while not self.should_stop:
            try:
                conn = rabbitmq.get_connection()
                channel = conn.channel()
                # Ensure queues and topology exist before consuming
                rabbitmq.setup_rabbitmq(channel=channel)
                channel.basic_qos(prefetch_count=1)

                def on_notion_message(ch, method, properties, body):
                    try:
                        data = json.loads(body.decode("utf-8"))
                        article_id = data.get("article_id")
                        article_type = data.get("article_type", "general")
                        logger.info(f"Received Notion Post Request for Article ID: {article_id} (Type: {article_type})")

                        article = db.get_article_by_id(article_id)
                        if not article:
                            logger.warning(f"Article ID {article_id} not found in database. Acknowledging message.")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        analysis = article.get("analysis_obj")
                        if not analysis:
                            raise ValueError(f"Article ID {article_id} does not have analysis yet. Cannot post to Notion.")

                        # Post to Notion
                        page_id = notion.publish_to_notion(article, analysis)
                        db.update_article_notion_page(article_id, page_id)
                        logger.info(f"Article ID {article_id} successfully published to Notion (Page ID: {page_id})")

                        ch.basic_ack(delivery_tag=method.delivery_tag)

                    except Exception as e:
                        logger.error(f"Error processing Notion Load Request: {e}", exc_info=True)
                        rabbitmq.handle_consumer_failure(ch, method, properties, body, str(e))

                channel.basic_consume(
                    queue=rabbitmq.NOTION_QUEUE,
                    on_message_callback=on_notion_message,
                    auto_ack=False
                )
                logger.info(f"[*] Notion Consumer started. Waiting for messages on '{rabbitmq.NOTION_QUEUE}'...")
                channel.start_consuming()

            except pika.exceptions.AMQPConnectionError as conn_err:
                if self.should_stop:
                    break
                logger.warning(f"RabbitMQ connection lost in Notion Consumer: {conn_err}. Reconnecting in 5s...")
                time.sleep(5)
            except Exception as e:
                if self.should_stop:
                    break
                logger.error(f"Unexpected error in Notion Consumer: {e}. Reconnecting in 5s...")
                time.sleep(5)

    def start_all(self):
        """
        Starts both Analyzer and Notion consumers in background threads.
        """
        self.should_stop = False
        t1 = threading.Thread(target=self.start_analyzer_consumer, name="Worker-Analyzer", daemon=True)
        t2 = threading.Thread(target=self.start_notion_consumer, name="Worker-Notion", daemon=True)

        t1.start()
        t2.start()
        self.threads = [t1, t2]
        logger.info("RabbitMQ Background Consumer Workers started.")

    def stop_all(self):
        self.should_stop = True
        logger.info("Stopping RabbitMQ Background Workers...")

worker_service = WorkerService()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Setting up RabbitMQ topology...")
    rabbitmq.setup_rabbitmq()
    logger.info("Starting standalone RabbitMQ Worker Process...")
    worker_service.start_all()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down worker...")
        worker_service.stop_all()
