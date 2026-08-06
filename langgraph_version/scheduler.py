"""
定时爬取调度器

职责：
1. 使用 APScheduler 实现每日定时爬取
2. 按预设关键词列表逐个爬取
3. 爬取结果存档 + 增量更新知识库

依赖：APScheduler
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from config import SCHEDULER_CONFIG, CRAWLER_CONFIG, PATH_CONFIG

logger = logging.getLogger(__name__)


def daily_crawl_task() -> dict[str, Any]:
    """每日爬取任务：按预设关键词列表逐个爬取。

    Returns:
        爬取统计信息：
        {
            "total_jobs": int,
            "by_platform": {...},
            "saved_path": str,
            "finished_at": str
        }
    """
    from jd_crawler import crawl_jobs, save_jobs

    keywords = CRAWLER_CONFIG["keywords"]
    city = CRAWLER_CONFIG["default_city"]

    all_jobs: list[dict[str, Any]] = []
    by_platform: dict[str, int] = {}

    for keyword in keywords:
        logger.info("正在爬取关键词: %s", keyword)
        try:
            jobs = crawl_jobs(keyword, city)
            all_jobs.extend(jobs)
            # 统计各平台数量
            for job in jobs:
                platform = job.get("platform", "unknown")
                by_platform[platform] = by_platform.get(platform, 0) + 1
        except Exception as e:  # noqa: BLE001
            logger.warning("关键词 %s 爬取失败: %s", keyword, e)

    # 跨关键词统一去重
    from jd_crawler import deduplicate_jobs, mark_premium_jobs

    all_jobs = mark_premium_jobs(deduplicate_jobs(all_jobs))

    # 存档到 data/crawled_jobs（按日期命名 JSON）
    saved_path = ""
    if all_jobs:
        saved_path = save_jobs(all_jobs, tag="daily")

    # 增量更新知识库
    try:
        from jd_knowledge_base import increment_update

        increment_update(all_jobs)
    except Exception as e:  # noqa: BLE001
        logger.warning("知识库增量更新失败: %s", e)

    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        "每日爬取完成：共 %d 个岗位，各平台 %s",
        len(all_jobs),
        by_platform,
    )

    return {
        "total_jobs": len(all_jobs),
        "by_platform": by_platform,
        "saved_path": saved_path,
        "finished_at": finished_at,
    }


def start_scheduler() -> None:
    """启动定时调度器（后台运行，阻塞主线程）。"""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as e:
        raise ImportError(
            "缺少依赖 APScheduler，请执行: pip install APScheduler"
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
        "定时调度器已启动：每日 %02d:%02d 执行爬取",
        SCHEDULER_CONFIG["hour"],
        SCHEDULER_CONFIG["minute"],
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


def run_once() -> dict[str, Any]:
    """手动触发一次爬取任务（用于测试）。"""
    return daily_crawl_task()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 用法：python scheduler.py [once|daemon]
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "daemon":
        start_scheduler()
    else:
        print(run_once())
