"""
岗位爬虫模块（四大平台）

职责：
1. 每日定时从四大招聘网站爬取岗位信息
2. 获取岗位全文 JD（含公司、薪资、技能要求、职责描述等）
3. 数据去重、清洗、结构化存储
4. 标记大厂岗位和高频岗位

爬取方案（四级降级策略，参考开源项目 JobOS）：
1. DrissionPage 浏览器监听（最稳定，推荐）
2. httpx + Cookie 直调 API（最快）
3. requests + HTML 解析（兜底）
4. 本地策展数据（离线兜底，永远能用）

支持平台：
- BOSS 直聘：DrissionPage 浏览器监听
- 拉勾：requests + Cookie
- 猎聘：requests + Cookie
- 智联招聘：requests + Cookie

依赖：DrissionPage, httpx, beautifulsoup4, lxml
"""

from __future__ import annotations

import logging
from typing import Any

from config import CRAWLER_CONFIG, BIG_TECH_COMPANIES, HIGH_FREQUENCY_THRESHOLD

logger = logging.getLogger(__name__)


def crawl_jobs(
    keyword: str,
    city: str = "全国",
    platforms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """爬取指定关键词和城市的岗位信息。

    Args:
        keyword: 搜索关键词（如 "Python"）
        city: 工作城市，默认 "全国"
        platforms: 平台列表，默认全平台 ["boss", "lagou", "liepin", "zhilian"]

    Returns:
        结构化岗位列表，每个元素字段见模块文档「数据字段定义」
    """
    if platforms is None:
        platforms = CRAWLER_CONFIG["platforms"]

    all_jobs: list[dict[str, Any]] = []
    for platform in platforms:
        try:
            # TODO: 根据 platform 分发到对应爬虫实现
            # 单平台失败不影响其他平台
            jobs = _crawl_platform(platform, keyword, city)
            all_jobs.extend(jobs)
        except Exception as e:  # noqa: BLE001
            logger.warning("平台 %s 爬取失败: %s", platform, e)

    # 去重 + 标记
    all_jobs = deduplicate_jobs(all_jobs)
    all_jobs = mark_premium_jobs(all_jobs)
    return all_jobs


def _crawl_platform(platform: str, keyword: str, city: str) -> list[dict[str, Any]]:
    """单平台爬取分发器。"""
    # TODO: 实现平台分发
    # if platform == "boss": return _crawl_boss(keyword, city)
    # if platform == "lagou": return _crawl_lagou(keyword, city)
    # ...
    raise NotImplementedError(f"平台 {platform} 爬虫待实现")


def _crawl_boss(keyword: str, city: str) -> list[dict[str, Any]]:
    """BOSS 直聘：DrissionPage 浏览器监听 API 返回。"""
    # TODO: 使用 DrissionPage 打开真实 Chrome，监听 API JSON
    raise NotImplementedError("_crawl_boss 待实现")


def _crawl_lagou(keyword: str, city: str) -> list[dict[str, Any]]:
    """拉勾：requests + Cookie 模拟请求。"""
    # TODO: 使用 httpx + Cookie 请求，解析 JSON/HTML
    raise NotImplementedError("_crawl_lagou 待实现")


def _crawl_liepin(keyword: str, city: str) -> list[dict[str, Any]]:
    """猎聘：requests + Cookie 模拟请求。"""
    # TODO: 使用 httpx + Cookie 请求，解析 HTML
    raise NotImplementedError("_crawl_liepin 待实现")


def _crawl_zhilian(keyword: str, city: str) -> list[dict[str, Any]]:
    """智联招聘：requests + Cookie 模拟请求。"""
    # TODO: 使用 httpx + Cookie 请求，解析 HTML
    raise NotImplementedError("_crawl_zhilian 待实现")


def crawl_job_detail(job_url: str, platform: str) -> dict[str, Any]:
    """爬取单个岗位详情页，获取完整 JD。

    Args:
        job_url: 岗位详情页 URL
        platform: 所属平台

    Returns:
        完整岗位信息字典（含 jd_text 全文）
    """
    # TODO: 根据平台请求详情页，解析完整 JD
    raise NotImplementedError("crawl_job_detail 待实现")


def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按岗位 ID 去重，同平台去重 + 跨平台去重。

    跨平台去重策略：按「岗位名称 + 公司名 + 地点」组合判断。
    """
    # TODO: 实现去重逻辑
    # 1. 优先按 job_id 去重
    # 2. 跨平台按 (title, company, city) 组合去重
    raise NotImplementedError("deduplicate_jobs 待实现")


def mark_premium_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标记大厂（BAT/字节/华为等）和高频匹配岗位。"""
    for job in jobs:
        # 大厂标记
        company = job.get("company", "")
        if any(big in company for big in BIG_TECH_COMPANIES):
            job["is_big_tech"] = True
        else:
            job.setdefault("is_big_tech", False)

        # 高频标记
        if job.get("match_count", 0) >= HIGH_FREQUENCY_THRESHOLD:
            job["is_high_frequency"] = True
        else:
            job.setdefault("is_high_frequency", False)

    return jobs


if __name__ == "__main__":
    # 自测示例
    results = crawl_jobs("Python", "北京", platforms=["boss"])
    print(f"爬取到 {len(results)} 个岗位")
