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
    from jd_crawler import crawl_jobs

    keywords = CRAWLER_CONFIG["keywords"]
    city = CRAWLER_CONFIG["default_city"]

    all_jobs: list[dict[str, Any]] = []
    for keyword in keywords:
        logger.info("正在爬取关键词: %s", keyword)
        try:
            jobs = crawl_jobs(keyword, city)
            all_jobs.extend(jobs)
        except Exception as e:  # noqa: BLE001
            logger.warning("关键词 %s 爬取失败: %s", keyword, e)

    # TODO: 存档到 data/crawled_jobs（按日期命名 JSON）
    # TODO: 增量更新知识库（调用 jd_knowledge_base.increment_update）
    # TODO: 统计并返回结果
    raise NotImplementedError("daily_crawl_task 待实现")


def start_scheduler() -> None:
    """启动定时调度器（后台运行）。"""
    # TODO: 使用 APScheduler 的 BackgroundScheduler
    # from apscheduler.schedulers.background import BackgroundScheduler
    # scheduler = BackgroundScheduler()
    # scheduler.add_job(
    #     func=daily_crawl_task,
    #     trigger="cron",
    #     hour=SCHEDULER_CONFIG["hour"],
    #     minute=SCHEDULER_CONFIG["minute"],
    #     id=SCHEDULER_CONFIG["job_id"],
    # )
    # scheduler.start()
    raise NotImplementedError("start_scheduler 待实现")


def run_once() -> dict[str, Any]:
    """手动触发一次爬取任务（用于测试）。"""
    return daily_crawl_task()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 手动执行一次
    # print(run_once())
    # 或启动定时调度
    # start_scheduler()
    print("scheduler 模块：使用 run_once() 手动触发或 start_scheduler() 定时运行")
