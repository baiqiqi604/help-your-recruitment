"""scheduler 定时调度模块的确定性测试（mock 爬虫与知识库，不发起真实请求）。"""

from __future__ import annotations

import sys
from unittest import mock

import config
import scheduler


def _patch_modules(monkeypatch, crawl_side_effect) -> mock.MagicMock:
    """把 jd_crawler 替换为可控桩；jd_knowledge_base 由 conftest 桩提供。"""
    fake_crawler = mock.MagicMock()
    if isinstance(crawl_side_effect, Exception):
        fake_crawler.crawl_jobs.side_effect = crawl_side_effect
    else:
        fake_crawler.crawl_jobs.return_value = crawl_side_effect
    fake_crawler.save_jobs.return_value = "/tmp/fake_jobs.json"
    monkeypatch.setitem(sys.modules, "jd_crawler", fake_crawler)
    return fake_crawler


class TestCrawlTask:
    def test_crawl_task_success_writes_and_indexes(self, monkeypatch) -> None:
        monkeypatch.setitem(config.CRAWLER_CONFIG, "keywords", ["Python"])
        fake_crawler = _patch_modules(
            monkeypatch, crawl_side_effect=[{"id": "1", "title": "Python 后端"}]
        )
        fake_kb = sys.modules.get("jd_knowledge_base")

        scheduler._crawl_task()

        fake_crawler.crawl_jobs.assert_called_once_with("Python")
        fake_crawler.save_jobs.assert_called_once()
        fake_kb.add_jobs.assert_called_once()

    def test_crawl_task_empty_result_skips_save(self, monkeypatch) -> None:
        monkeypatch.setitem(config.CRAWLER_CONFIG, "keywords", ["Python"])
        fake_crawler = _patch_modules(monkeypatch, crawl_side_effect=[])

        scheduler._crawl_task()

        fake_crawler.save_jobs.assert_not_called()

    def test_crawl_task_platform_error_skipped(self, monkeypatch) -> None:
        monkeypatch.setitem(config.CRAWLER_CONFIG, "keywords", ["Python", "Java"])
        fake_crawler = _patch_modules(
            monkeypatch, crawl_side_effect=RuntimeError("网络错误")
        )

        # 平台异常被捕获跳过，不抛出、不中断整体任务
        scheduler._crawl_task()

        fake_crawler.save_jobs.assert_not_called()

    def test_crawl_task_empty_keywords_noop(self, monkeypatch) -> None:
        monkeypatch.setitem(config.CRAWLER_CONFIG, "keywords", [])
        _patch_modules(monkeypatch, crawl_side_effect=[])

        scheduler._crawl_task()  # 不应抛异常
