"""Scheduled job crawling and knowledge-base updates."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from config import CRAWLER_CONFIG, SCHEDULER_CONFIG

logger = logging.getLogger(__name__)


def daily_crawl_task() -> dict[str, Any]:
    """Crawl all configured keywords and update the local job knowledge base."""
    from jd_crawler import crawl_jobs_batch, save_jobs

    keywords = CRAWLER_CONFIG["keywords"]
    city = CRAWLER_CONFIG["default_city"]
    try:
        jobs = crawl_jobs_batch(keywords, city)
    except Exception as e:  # noqa: BLE001
        logger.warning("Batch crawl failed: %s", e)
        jobs = []

    by_platform: dict[str, int] = {}
    for job in jobs:
        platform = str(job.get("platform", "unknown"))
        by_platform[platform] = by_platform.get(platform, 0) + 1

    saved_path = save_jobs(jobs, tag="daily") if jobs else ""
    try:
        from jd_knowledge_base import increment_update

        increment_update(jobs)
    except Exception as e:  # noqa: BLE001
        logger.warning("Knowledge base update failed: %s", e)

    return {
        "total_jobs": len(jobs),
        "by_platform": by_platform,
        "saved_path": saved_path,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def start_scheduler() -> None:
    """Start the blocking daily scheduler."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as e:
        raise ImportError(
            "APScheduler is required; install it with: pip install APScheduler"
        ) from e

    scheduler = BlockingScheduler()
    scheduler.add_job(
        func=daily_crawl_task,
        trigger="cron",
        hour=SCHEDULER_CONFIG["hour"],
        minute=SCHEDULER_CONFIG["minute"],
        id=SCHEDULER_CONFIG["job_id"],
        replace_existing=True,
    )
    logger.info(
        "Scheduler started: daily crawl at %02d:%02d",
        SCHEDULER_CONFIG["hour"],
        SCHEDULER_CONFIG["minute"],
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


def run_once() -> dict[str, Any]:
    """Trigger one crawl immediately, useful for manual verification."""
    return daily_crawl_task()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "daemon":
        start_scheduler()
    else:
        print(run_once())
