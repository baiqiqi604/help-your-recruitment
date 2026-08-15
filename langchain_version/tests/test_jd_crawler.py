"""jd_crawler 岗位爬虫模块的确定性测试（不发起真实网络请求）。"""

from __future__ import annotations

import json
from pathlib import Path

import config
import jd_crawler


class TestSaveJobs:
    def test_save_jobs_writes_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setitem(config.PATH_CONFIG, "crawled_jobs_dir", str(tmp_path))
        jobs = [{"id": "1", "title": "Python 后端"}, {"id": "2", "title": "Java 后端"}]

        path = jd_crawler.save_jobs(jobs)

        assert path.endswith(".json")
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        assert len(saved) == 2

    def test_save_jobs_dedup_merge(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setitem(config.PATH_CONFIG, "crawled_jobs_dir", str(tmp_path))
        jd_crawler.save_jobs([{"id": "1", "title": "A"}])
        jd_crawler.save_jobs([{"id": "1", "title": "A"}, {"id": "2", "title": "B"}])

        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        # 同 id 去重合并，不重复写入
        assert [j["id"] for j in saved] == ["1", "2"]

    def test_save_jobs_empty_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setitem(config.PATH_CONFIG, "crawled_jobs_dir", str(tmp_path))
        assert jd_crawler.save_jobs([]) == ""


class TestCrawlJobs:
    def test_crawl_jobs_unknown_platform_skipped(self, monkeypatch) -> None:
        monkeypatch.setitem(config.CRAWLER_CONFIG, "platforms", ["bogus_platform"])
        monkeypatch.setitem(config.CRAWLER_CONFIG, "request_interval", 0)

        assert jd_crawler.crawl_jobs("Python") == []

    def test_crawl_jobs_error_platform_skipped(self, monkeypatch) -> None:
        def boom(keyword: str, city: str):
            raise RuntimeError("网络错误")

        monkeypatch.setitem(config.CRAWLER_CONFIG, "platforms", ["boss"])
        monkeypatch.setitem(config.CRAWLER_CONFIG, "request_interval", 0)
        monkeypatch.setattr(jd_crawler, "_CRAWLERS", {"boss": boom})

        # 平台异常被跳过，不抛出，整体返回空
        assert jd_crawler.crawl_jobs("Python") == []

    def test_crawl_jobs_success_aggregates(self, monkeypatch) -> None:
        def fake_crawl(keyword: str, city: str) -> list[dict]:
            return [{"id": "x", "title": keyword}]

        monkeypatch.setitem(config.CRAWLER_CONFIG, "platforms", ["boss", "lagou"])
        monkeypatch.setitem(config.CRAWLER_CONFIG, "request_interval", 0)
        monkeypatch.setattr(
            jd_crawler, "_CRAWLERS", {"boss": fake_crawl, "lagou": fake_crawl}
        )

        result = jd_crawler.crawl_jobs("Python")

        assert len(result) == 2
        assert all(j["title"] == "Python" for j in result)
