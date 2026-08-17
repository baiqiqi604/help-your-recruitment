"""
岗位爬虫模块（多平台骨架）

职责：
1. 基于 httpx + BeautifulSoup 的多平台岗位爬虫骨架
   （boss / lagou / liepin / zhilian）
2. crawl_jobs(keyword, city) 聚合各平台结果
3. save_jobs(jobs) 按日期存档 JSON 到 data/crawled_jobs

说明：
- 各平台站点结构 / 反爬策略频繁变化，本模块为可扩展骨架，
  具体选择器需按站点实际 DOM 调整。
- 任一平台失败只记 warning，不中断整体流程。
- 对 JS 渲染型页面（如智联 SPA），可能需要配合
  DrissionPage / Playwright 抓取，此处留出扩展位。

依赖：httpx、beautifulsoup4
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from config import CRAWLER_CONFIG, PATH_CONFIG

logger = logging.getLogger(__name__)

# 平台元信息（搜索入口）
_PLATFORM_CONFIG: dict[str, dict[str, str]] = {
    "boss": {"label": "BOSS直聘", "search_url": "https://www.zhipin.com/web/geek/job"},
    "lagou": {"label": "拉勾", "search_url": "https://www.lagou.com/jobs/list_{kw}"},
    "liepin": {"label": "猎聘", "search_url": "https://www.liepin.com/zhaopin/"},
    "zhilian": {"label": "智联招聘", "search_url": "https://sou.zhaopin.com/"},
}


def _fetch(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> str | None:
    """发起 GET 请求，返回 HTML 文本；失败返回 None 并记 warning。"""
    headers = CRAWLER_CONFIG.get("headers", {})
    try:
        resp = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        # 优先按响应头编码，其次按 apparent_encoding 兜底
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        return resp.text
    except Exception as e:  # noqa: BLE001
        logger.warning("请求失败 %s: %s", url, e)
        return None


def _text(node: Any) -> str:
    """提取节点文本（去除空白）。"""
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _make_job(
    *,
    title: str,
    company: str,
    city: str,
    salary: str,
    jd_text: str,
    url: str,
    platform: str,
) -> dict[str, Any]:
    """构造标准岗位字典（id 为内容哈希，稳定可去重）。"""
    raw = f"{platform}|{title}|{company}|{city}|{url}|{jd_text}"
    return {
        "id": hashlib.md5(raw.encode("utf-8")).hexdigest(),
        "title": title,
        "company": company,
        "city": city,
        "salary": salary,
        "jd_text": jd_text,
        "url": url,
        "platform": platform,
        "crawled_at": datetime.now().isoformat(timespec="seconds"),
    }


def _fetch_jd_text(url: str) -> str:
    """抓取岗位详情页正文（骨架实现，选择器按站点调整）。"""
    html = _fetch(url)
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        ".job-sec-text",
        ".job-detail",
        ".description",
        "#job-detail",
        "main",
    ):
        node = soup.select_one(selector)
        if node:
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                return text
    return ""


# ──────────────────────────────────────────────
# 各平台爬虫（骨架）
# ──────────────────────────────────────────────
def _crawl_boss(keyword: str, city: str) -> list[dict[str, Any]]:
    """BOSS 直聘岗位爬取（骨架，选择器按站点实际 DOM 调整）。"""
    cfg = _PLATFORM_CONFIG["boss"]
    html = _fetch(cfg["search_url"], {"query": keyword, "city": city, "page": 1})
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    for card in soup.select("li.job-card-wrapper, .job-card-wrapper"):
        title = _text(card.select_one(".job-name"))
        company = _text(card.select_one(".company-name"))
        salary = _text(card.select_one(".salary"))
        area = _text(card.select_one(".job-area"))
        link = card.select_one("a.job-card-left")
        href = link.get("href") if link else ""
        if not title or not href:
            continue
        url = urljoin(cfg["search_url"], href)
        jd_text = _fetch_jd_text(url) or f"{title} | {company} | {area} | {salary}"
        jobs.append(
            _make_job(
                title=title, company=company, city=city, salary=salary,
                jd_text=jd_text, url=url, platform="boss",
            )
        )
    logger.debug("[boss] 关键词 %s 获取 %d 条", keyword, len(jobs))
    return jobs


def _crawl_lagou(keyword: str, city: str) -> list[dict[str, Any]]:
    """拉勾网岗位爬取（骨架）。"""
    url = _PLATFORM_CONFIG["lagou"]["search_url"].format(kw=keyword)
    html = _fetch(url, {"city": city, "needAddtionalResult": "false"})
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    for item in soup.select("li[class*='job'], div[class*='position']"):
        title_el = item.select_one("a[class*='position'], .position-link, a")
        if not title_el:
            continue
        title = _text(title_el)
        company = _text(item.select_one(".company_name, [class*='company']"))
        salary = _text(item.select_one(".money, [class*='salary']"))
        href = title_el.get("href") or ""
        url = urljoin("https://www.lagou.com", href) if href else ""
        jd_text = _fetch_jd_text(url) if url else ""
        if not title:
            continue
        jobs.append(
            _make_job(
                title=title, company=company, city=city, salary=salary,
                jd_text=jd_text, url=url, platform="lagou",
            )
        )
    logger.debug("[lagou] 关键词 %s 获取 %d 条", keyword, len(jobs))
    return jobs


def _crawl_liepin(keyword: str, city: str) -> list[dict[str, Any]]:
    """猎聘网岗位爬取（骨架）。"""
    url = _PLATFORM_CONFIG["liepin"]["search_url"]
    html = _fetch(url, {"key": keyword, "city": city})
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    for item in soup.select(".job-info, li[class*='job']"):
        title_el = item.select_one("a[class*='title'], .job-title, a")
        if not title_el:
            continue
        title = _text(title_el)
        company = _text(item.select_one(".company-name, [class*='company']"))
        salary = _text(item.select_one(".job-salary, [class*='salary']"))
        href = title_el.get("href") or ""
        url = urljoin(url, href) if href else ""
        jd_text = _fetch_jd_text(url) if url else ""
        if not title:
            continue
        jobs.append(
            _make_job(
                title=title, company=company, city=city, salary=salary,
                jd_text=jd_text, url=url, platform="liepin",
            )
        )
    logger.debug("[liepin] 关键词 %s 获取 %d 条", keyword, len(jobs))
    return jobs


def _crawl_zhilian(keyword: str, city: str) -> list[dict[str, Any]]:
    """智联招聘岗位爬取（骨架）。

    注意：sou.zhaopin.com 为 JS 渲染 SPA，纯 httpx 通常拿不到列表数据。
    此处演示骨架结构，可扩展为 DrissionPage / Playwright 渲染抓取。
    """
    url = _PLATFORM_CONFIG["zhilian"]["search_url"]
    html = _fetch(url, {"kw": keyword, "city": city})
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    for item in soup.select(".joblist-box__item, .joblist-box_ea0c5, li[class*='job']"):
        title_el = item.select_one(".joblist-box__iteminfo, a[class*='title'], a")
        if not title_el:
            continue
        title = _text(title_el)
        company = _text(item.select_one("[class*='company']"))
        salary = _text(item.select_one("[class*='salary']"))
        href = title_el.get("href") or ""
        url = urljoin(url, href) if href else ""
        jd_text = _fetch_jd_text(url) if url else ""
        if not title:
            continue
        jobs.append(
            _make_job(
                title=title, company=company, city=city, salary=salary,
                jd_text=jd_text, url=url, platform="zhilian",
            )
        )
    logger.debug("[zhilian] 关键词 %s 获取 %d 条", keyword, len(jobs))
    return jobs


# 平台 → 爬虫函数注册表
_CRAWLERS: dict[str, Callable[[str, str], list[dict[str, Any]]]] = {
    "boss": _crawl_boss,
    "lagou": _crawl_lagou,
    "liepin": _crawl_liepin,
    "zhilian": _crawl_zhilian,
}


# ──────────────────────────────────────────────
# 对外接口
# ──────────────────────────────────────────────
def crawl_jobs(keyword: str, city: str | None = None) -> list[dict[str, Any]]:
    """按关键词与城市爬取多平台岗位。

    任一平台失败仅记 warning 并跳过，不抛出异常；
    全部失败时返回空列表。

    Returns:
        [{id, title, company, city, salary, jd_text, url, platform, crawled_at}]
    """
    city = city or CRAWLER_CONFIG.get("default_city", "全国")
    interval = CRAWLER_CONFIG.get("request_interval", 3)

    results: list[dict[str, Any]] = []
    for platform in CRAWLER_CONFIG.get("platforms", []):
        crawler = _CRAWLERS.get(platform)
        if not crawler:
            logger.warning("未知平台: %s，跳过", platform)
            continue
        try:
            jobs = crawler(keyword, city)
        except Exception as e:  # noqa: BLE001
            logger.warning("平台 [%s] 爬取异常，跳过: %s", platform, e)
            jobs = []
        results.extend(jobs)
        time.sleep(interval)

    logger.info(
        "爬虫完成：keyword=%s city=%s platforms=%d 共获取 %d 条",
        keyword, city, len(_CRAWLERS), len(results),
    )
    return results


def save_jobs(jobs: list[dict[str, Any]]) -> str:
    """按日期将岗位存档为 JSON 文件（增量合并去重）。

    Args:
        jobs: 岗位列表

    Returns:
        存档文件绝对路径；无数据时返回 ""
    """
    if not jobs:
        logger.info("无岗位数据可保存")
        return ""

    save_dir = Path(PATH_CONFIG["crawled_jobs_dir"])
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"jobs_{date.today().isoformat()}.json"

    existing: list[dict[str, Any]] = []
    if file_path.exists():
        try:
            existing = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取既有存档失败，重建存档: %s", e)
            existing = []

    seen = {str(j.get("id")) for j in existing if j.get("id")}
    merged = list(existing)
    for job in jobs:
        job_id = str(job.get("id") or "")
        if job_id and job_id not in seen:
            merged.append(job)
            seen.add(job_id)

    file_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("岗位存档完成：%s（累计 %d 条）", file_path, len(merged))
    return str(file_path)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    keyword = sys.argv[1] if len(sys.argv) > 1 else "Python"
    jobs = crawl_jobs(keyword)
    print("获取到 %d 条岗位" % len(jobs))
    if jobs:
        saved = save_jobs(jobs)
        print("已保存:", saved)
