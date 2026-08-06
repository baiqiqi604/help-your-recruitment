"""
定时调度模块（APScheduler）

职责：
1. 每天按 SCHEDULER_CONFIG 中 hour:minute 触发岗位爬虫
2. 爬取 → 存档 → 写入知识库 全链路
3. 使用 BlockingScheduler 阻塞运行，适合独立进程启动

依赖：APScheduler
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from config import CRAWLER_CONFIG, SCHEDULER_CONFIG

logger = logging.getLogger(__name__)


def _crawl_task() -> None:
    """定时任务：遍历关键词爬取岗位，存档并写入知识库。"""
    import jd_crawler
    import jd_knowledge_base

    total = 0
    for keyword in CRAWLER_CONFIG.get("keywords", []):
        try:
            jobs = jd_crawler.crawl_jobs(keyword)
            if jobs:
                jd_crawler.save_jobs(jobs)
                jd_knowledge_base.add_jobs(jobs)
                total += len(jobs)
                logger.info("关键词 [%s] 完成，累计 %d 条", keyword, total)
            else:
                logger.warning("关键词 [%s] 未获取到岗位", keyword)
        except Exception as e:  # noqa: BLE001
            logger.warning("关键词 [%s] 处理失败，跳过: %s", keyword, e)

    logger.info("本次定时爬取完成，共 %d 条岗位", total)


def start_scheduler() -> None:
    """启动 BlockingScheduler（阻塞当前进程直到被终止）。

    触发规则：每天 SCHEDULER_CONFIG['hour']:SCHEDULER_CONFIG['minute']
    """
    hour = SCHEDULER_CONFIG.get("hour", 2)
    minute = SCHEDULER_CONFIG.get("minute", 0)
    job_id = SCHEDULER_CONFIG.get("job_id", "daily_jd_crawl")

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _crawl_task,
        trigger="cron",
        hour=hour,
        minute=minute,
        id=job_id,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.info("定时任务已启动：每天 %02d:%02d 执行 [%s]", hour, minute, job_id)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_scheduler()
