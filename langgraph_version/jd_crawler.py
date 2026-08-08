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
- BOSS 直聘：DrissionPage 浏览器监听 API（/web/geek/job）
- 拉勾：httpx + Cookie
- 猎聘：httpx + Cookie + HTML 解析
- 智联招聘：httpx + Cookie + HTML 解析

依赖：DrissionPage, httpx, beautifulsoup4, lxml

参考：
- https://github.com/g1879/DrissionPage
- DrissionPage 监听 Boss 直聘 joblist 接口方案
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

from config import CRAWLER_CONFIG, BIG_TECH_COMPANIES, HIGH_FREQUENCY_THRESHOLD, PATH_CONFIG

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Boss 直聘城市编码（常用城市，其他城市默认全国）
# ──────────────────────────────────────────────
BOSS_CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "西安": "101110100",
    "苏州": "101190400",
    "长沙": "101250100",
}


# ══════════════════════════════════════════════
# 对外主接口
# ══════════════════════════════════════════════
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
            jobs = _crawl_platform(platform, keyword, city)
            logger.info("平台 %s 爬取到 %d 个岗位", platform, len(jobs))
            all_jobs.extend(jobs)
        except Exception as e:  # noqa: BLE001
            # 单平台失败不影响其他平台
            logger.warning("平台 %s 爬取失败: %s", platform, e)

    # 去重 + 标记
    all_jobs = deduplicate_jobs(all_jobs)
    all_jobs = mark_premium_jobs(all_jobs)
    return all_jobs


def crawl_jobs_batch(
    keywords: list[str],
    city: str = "全国",
    platforms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Batch crawl jobs while reusing one browser session for Liepin."""
    cleaned_keywords = list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
    if not cleaned_keywords:
        return []

    selected_platforms = platforms or CRAWLER_CONFIG["platforms"]
    all_jobs: list[dict[str, Any]] = []

    if "liepin" in selected_platforms:
        try:
            liepin_jobs = crawl_liepin_browser(cleaned_keywords, city)
            all_jobs.extend(liepin_jobs)
            if not liepin_jobs:
                logger.info("Liepin browser returned no jobs; trying HTTP/curated fallback")
                for keyword in cleaned_keywords:
                    try:
                        http_jobs = _httpx_html_crawl(
                            platform="liepin",
                            search_url="https://www.liepin.com/zhaopin/?key={keyword}",
                            keyword=keyword,
                            city=city,
                        )
                        all_jobs.extend(http_jobs or _load_curated_data("liepin", keyword))
                    except Exception as fallback_error:  # noqa: BLE001
                        logger.warning("Liepin HTTP fallback failed for %s: %s", keyword, fallback_error)
        except Exception as e:  # noqa: BLE001
            logger.warning("Liepin browser batch crawl failed: %s", e)
            for keyword in cleaned_keywords:
                try:
                    all_jobs.extend(_load_curated_data("liepin", keyword))
                except Exception as fallback_error:  # noqa: BLE001
                    logger.warning("Liepin fallback failed for %s: %s", keyword, fallback_error)

    if "zhilian" in selected_platforms:
        try:
            zhilian_jobs = crawl_zhilian_browser(cleaned_keywords, city)
            all_jobs.extend(zhilian_jobs)
            if not zhilian_jobs:
                logger.info("Zhilian browser returned no jobs; trying HTTP/curated fallback")
                for keyword in cleaned_keywords:
                    try:
                        all_jobs.extend(_load_curated_data("zhilian", keyword))
                    except Exception as fallback_error:  # noqa: BLE001
                        logger.warning("Zhilian fallback failed for %s: %s", keyword, fallback_error)
        except Exception as e:  # noqa: BLE001
            logger.warning("Zhilian browser batch crawl failed: %s", e)
            for keyword in cleaned_keywords:
                try:
                    all_jobs.extend(_load_curated_data("zhilian", keyword))
                except Exception as fallback_error:  # noqa: BLE001
                    logger.warning("Zhilian fallback failed for %s: %s", keyword, fallback_error)

    other_platforms = [p for p in selected_platforms if p not in ("liepin", "zhilian")]
    for keyword in cleaned_keywords:
        for platform in other_platforms:
            try:
                all_jobs.extend(_crawl_platform(platform, keyword, city))
            except Exception as e:  # noqa: BLE001
                logger.warning("%s crawl failed for %s: %s", platform, keyword, e)

    return mark_premium_jobs(deduplicate_jobs(all_jobs))


def _crawl_platform(platform: str, keyword: str, city: str) -> list[dict[str, Any]]:
    """单平台爬取分发器（含四级降级）。"""
    dispatch = {
        "boss": _crawl_boss,
        "lagou": _crawl_lagou,
        "liepin": _crawl_liepin,
        "zhilian": _crawl_zhilian,
        "jobui": _crawl_jobui,
        "51job": _crawl_51job,
    }
    handler = dispatch.get(platform)
    if handler is None:
        raise ValueError(f"不支持的平台: {platform}")

    try:
        jobs = handler(keyword, city)
        if jobs:
            return jobs
        logger.warning("平台 %s 在线爬取无结果，尝试本地策展数据兜底", platform)
    except Exception as e:  # noqa: BLE001
        logger.warning("平台 %s 在线爬取异常: %s，尝试本地策展数据兜底", platform, e)

    # 第四级降级：本地策展数据
    return _load_curated_data(platform, keyword)


# ══════════════════════════════════════════════
# BOSS 直聘：DrissionPage 浏览器监听
# ══════════════════════════════════════════════
def _crawl_boss(keyword: str, city: str) -> list[dict[str, Any]]:
    """BOSS 直聘：DrissionPage 打开真实浏览器，监听 joblist 接口 JSON。

    流程：
    1. 启动 ChromiumPage，开启接口监听（关键词 'joblist'）
    2. 检查登录态，未登录则引导扫码
    3. 访问搜索页，触发接口请求
    4. 从监听到的响应中提取岗位列表
    5. 翻页重复，直到达到 max_pages
    """
    try:
        from DrissionPage import ChromiumPage
    except ImportError as e:
        raise ImportError(
            "缺少依赖 DrissionPage，请执行: pip install DrissionPage"
        ) from e

    city_code = BOSS_CITY_CODES.get(city, BOSS_CITY_CODES["全国"])
    max_pages = CRAWLER_CONFIG["max_pages"]

    page = ChromiumPage()
    jobs: list[dict[str, Any]] = []
    try:
        # 开启接口监听
        page.listen.start("joblist")

        # 登录态处理
        _boss_login(page)

        for page_num in range(1, max_pages + 1):
            url = (
                f"https://www.zhipin.com/web/geek/job"
                f"?query={keyword}&city={city_code}&page={page_num}"
            )
            logger.info("BOSS 直聘爬取第 %d 页: %s", page_num, url)
            page.get(url)

            # 等待接口返回
            packet = page.listen.wait(timeout=CRAWLER_CONFIG["timeout"])
            if packet is None:
                logger.warning("BOSS 直聘第 %d 页未捕获到接口响应", page_num)
                break

            page_jobs = _parse_boss_response(packet, keyword, city)
            if not page_jobs:
                logger.info("BOSS 直聘第 %d 页无更多岗位，停止翻页", page_num)
                break
            jobs.extend(page_jobs)

            _polite_sleep()
    finally:
        try:
            page.quit()
        except Exception:  # noqa: BLE001
            pass

    return jobs


def _boss_login(page) -> None:
    """BOSS 直聘登录态处理：已登录则跳过，否则引导扫码/手动登录。"""
    page.get("https://www.zhipin.com/")
    time.sleep(2)

    # 检查是否已登录（页面存在头像元素）
    avatar = page.ele(".avatar", timeout=2)
    if avatar:
        logger.info("BOSS 直聘已登录，跳过登录步骤")
        return

    logger.warning("BOSS 直聘未登录，请在弹出的浏览器中扫码登录...")
    # 尝试点击登录按钮（多种可能选择器，适配页面改版）
    for selector in (".login-btn", ".btn-login", ".user-login"):
        login_btn = page.ele(selector, timeout=2)
        if login_btn:
            try:
                login_btn.click()
            except Exception:  # noqa: BLE001
                pass
            break

    # 等待用户手动完成登录（最多 120 秒）
    for _ in range(60):
        time.sleep(2)
        if page.ele(".avatar", timeout=1):
            logger.info("BOSS 直聘登录成功")
            return
    logger.warning("BOSS 直聘登录等待超时，将以未登录态继续（可能无完整数据）")


def _parse_boss_response(packet, keyword: str, city: str) -> list[dict[str, Any]]:
    """解析 BOSS 直聘 joblist 接口响应。"""
    jobs: list[dict[str, Any]] = []
    try:
        # DrissionPage 的 packet.response.body 为接口返回的 JSON
        body = packet.response.body
        if isinstance(body, str):
            body = json.loads(body)
        job_list = body.get("zpData", {}).get("jobList", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("解析 BOSS 直聘响应失败: %s", e)
        return jobs

    for item in job_list:
        try:
            jobs.append(_normalize_boss_job(item, keyword, city))
        except Exception as e:  # noqa: BLE001
            logger.debug("解析单条 BOSS 岗位失败: %s", e)
    return jobs


def _normalize_boss_job(item: dict[str, Any], keyword: str, city: str) -> dict[str, Any]:
    """将 BOSS 直聘接口字段标准化为统一结构。"""
    encrypt_id = item.get("encryptJobId", "") or item.get("jobId", "")
    skills = item.get("skills", []) or []
    return {
        "job_id": f"boss_{encrypt_id}",
        "platform": "boss",
        "title": item.get("jobName", ""),
        "company": item.get("brandName", ""),
        "company_size": item.get("brandScaleName", ""),
        "salary": item.get("salaryDesc", ""),
        "city": item.get("cityName", city),
        "experience": item.get("jobExperience", ""),
        "education": item.get("jobDegree", ""),
        "skills": skills,
        "jd_text": _build_jd_text(item.get("jobName", ""), item.get("brandName", ""),
                                   skills, item.get("jobDescription", "")),
        "responsibilities": item.get("jobDescription", ""),
        "requirements": ", ".join(skills),
        "is_big_tech": False,
        "match_count": 0,
        "crawled_at": datetime.now().strftime("%Y-%m-%d"),
        "url": f"https://www.zhipin.com/job_detail/{encrypt_id}.html",
    }


# ══════════════════════════════════════════════
# 拉勾 / 猎聘 / 智联：httpx + Cookie
# ══════════════════════════════════════════════
def _crawl_lagou(keyword: str, city: str) -> list[dict[str, Any]]:
    """拉勾：httpx + Cookie 模拟请求。

    注意：拉勾反爬较严，需在 config 中配置有效 Cookie，
    或先用浏览器登录后导出 Cookie。
    """
    # 注意：拉勾接口需登录态 Cookie，实际使用请在 CRAWLER_CONFIG["headers"] 中补充 Cookie
    logger.info("拉勾爬取（需配置 Cookie）: keyword=%s, city=%s", keyword, city)
    return _httpx_html_crawl(
        platform="lagou",
        search_url="https://www.lagou.com/jobs/list_{keyword}",
        keyword=keyword,
        city=city,
    )


def _crawl_liepin(keyword: str, city: str) -> list[dict[str, Any]]:
    """猎聘：httpx + Cookie + HTML 解析。"""
    logger.info("猎聘爬取: keyword=%s, city=%s", keyword, city)
    jobs = _httpx_html_crawl(
        platform="liepin",
        search_url="https://www.liepin.com/zhaopin/?key={keyword}",
        keyword=keyword,
        city=city,
    )
    if jobs:
        return jobs
    return crawl_liepin_browser([keyword], city)


LIEPIN_CARD_SELECTOR = "div.job-card-pc-container"
ZHILIAN_CARD_SELECTOR = "div.joblist-box__item"


def crawl_liepin_browser(keywords: list[str], city: str) -> list[dict[str, Any]]:
    """Crawl public Liepin result pages through one normal browser session."""
    browser_config = CRAWLER_CONFIG.get("liepin_browser", {})
    if not browser_config.get("enabled", True):
        return []

    try:
        from DrissionPage import ChromiumPage
    except ImportError as e:
        raise ImportError("DrissionPage is required for Liepin browser crawling") from e

    page = ChromiumPage()
    jobs: list[dict[str, Any]] = []
    try:
        for keyword in keywords:
            if keyword.strip():
                jobs.extend(_crawl_liepin_browser_keyword(page, keyword.strip(), city))
    finally:
        try:
            page.quit()
        except Exception:  # noqa: BLE001
            pass
    return deduplicate_jobs(jobs)


def _crawl_liepin_browser_keyword(page, keyword: str, city: str) -> list[dict[str, Any]]:
    """Crawl paginated Liepin cards and stop when pages repeat or have no new jobs."""
    from bs4 import BeautifulSoup

    browser_config = CRAWLER_CONFIG.get("liepin_browser", {})
    max_pages = browser_config.get("max_pages", CRAWLER_CONFIG["max_pages"])
    render_wait = browser_config.get("render_wait_seconds", 2)
    min_cards = browser_config.get("min_cards_per_page", 5)
    jobs: list[dict[str, Any]] = []
    seen_pages: set[tuple[str, ...]] = set()
    seen_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = (
            "https://www.liepin.com/zhaopin/?key="
            f"{quote_plus(keyword)}&page={page_num}"
        )
        logger.info("Liepin browser crawl: keyword=%s page=%d", keyword, page_num)
        try:
            page.get(url)
            page.wait.doc_loaded()
        except Exception as e:  # noqa: BLE001
            logger.warning("Liepin page load failed for keyword=%s page=%d: %s", keyword, page_num, e)
            break
        try:
            page.wait.ele_displayed(LIEPIN_CARD_SELECTOR, timeout=CRAWLER_CONFIG["timeout"])
        except Exception:  # noqa: BLE001
            logger.warning("Liepin has no rendered cards for keyword=%s page=%d", keyword, page_num)
            break

        if render_wait:
            page.wait(render_wait)
        cards = BeautifulSoup(page.html, "lxml").select(LIEPIN_CARD_SELECTOR)
        page_jobs = [
            job
            for card in cards
            if (job := _parse_liepin_browser_card(card, city)) is not None
        ]
        page_signature = tuple(sorted(job["job_id"] for job in page_jobs))
        if not page_jobs or page_signature in seen_pages:
            logger.info("Liepin page repeated or contained no jobs; stopping keyword=%s", keyword)
            break
        seen_pages.add(page_signature)

        new_jobs = [job for job in page_jobs if job["job_id"] not in seen_ids]
        if not new_jobs:
            break
        seen_ids.update(job["job_id"] for job in new_jobs)
        jobs.extend(new_jobs)

        if len(cards) < min_cards:
            break
        _polite_sleep()

    return jobs


def _parse_liepin_browser_card(card, fallback_city: str) -> dict[str, Any] | None:
    """Normalize a rendered Liepin result card into the project job schema."""
    title_node = card.select_one(
        'a[data-nick="job-detail-job-info"] .ellipsis-1[title], .job-title[title], h3[title]'
    )
    title = _clean_text(title_node.get("title", "") if title_node else "")
    if not title:
        title = _clean_text(_safe_text(card, ".job-title, h3, .ellipsis-1"))
    if not title:
        return None

    link = card.select_one('a[data-nick="job-detail-job-info"], a[href*="/job/"]')
    url = urljoin("https://www.liepin.com", link.get("href", "")) if link else ""
    company_node = card.select_one('[data-nick="job-detail-company-info"] .ellipsis-1')
    company = _clean_text(company_node.get_text(" ", strip=True) if company_node else "")
    salary = _first_card_text(card, ".job-salary, .salary, .job-money")
    location = _first_card_text(card, ".job-dq, .job-area, .job-location")
    requirements = _first_card_text(card, ".job-require, .job-requirements")
    text = _clean_text(card.get_text(" ", strip=True))

    if not salary:
        match = re.search(r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[kK]|面议", text)
        salary = _clean_text(match.group(0)) if match else ""
    experience_match = re.search(r"\d+(?:\s*-\s*\d+)?年|经验不限|应届", requirements or text)
    education_match = re.search(r"本科|硕士|博士|大专|学历不限", requirements or text)
    skills = [
        _clean_text(node.get_text(" ", strip=True))
        for node in card.select(".tag-list span, .job-tags span")
        if _clean_text(node.get_text(" ", strip=True))
    ]
    city = location or fallback_city
    job_id = _stable_job_id("liepin", title, company, city, url)
    jd_text = _build_jd_text(title, company, skills, requirements)

    return {
        "job_id": job_id,
        "platform": "liepin",
        "title": title,
        "company": company,
        "company_size": "",
        "salary": salary,
        "city": city,
        "experience": experience_match.group(0) if experience_match else "",
        "education": education_match.group(0) if education_match else "",
        "skills": list(dict.fromkeys(skills)),
        "jd_text": jd_text,
        "responsibilities": requirements,
        "requirements": requirements,
        "is_big_tech": False,
        "match_count": 0,
        "crawled_at": datetime.now().strftime("%Y-%m-%d"),
        "url": _clean_url(url),
    }


def crawl_zhilian_browser(keywords: list[str], city: str) -> list[dict[str, Any]]:
    """Crawl public Zhilian (zhaopin) result pages through one normal browser session.

    智联搜索页有 WAF 防护（Security Verification），纯 httpx 请求会被拦截；
    使用 DrissionPage 真实浏览器渲染 + Cookie 注入可正常获取岗位列表。
    """
    browser_config = CRAWLER_CONFIG.get("zhilian_browser", {})
    if not browser_config.get("enabled", True):
        return []

    try:
        from DrissionPage import ChromiumPage
    except ImportError as e:
        raise ImportError("DrissionPage is required for Zhilian browser crawling") from e

    page = ChromiumPage()
    jobs: list[dict[str, Any]] = []
    try:
        for keyword in keywords:
            if keyword.strip():
                jobs.extend(_crawl_zhilian_browser_keyword(page, keyword.strip(), city))
    finally:
        try:
            page.quit()
        except Exception:  # noqa: BLE001
            pass
    return deduplicate_jobs(jobs)


def _crawl_zhilian_browser_keyword(page, keyword: str, city: str) -> list[dict[str, Any]]:
    """Crawl paginated Zhilian cards with Cookie injection; stop on repeat/empty pages."""
    from bs4 import BeautifulSoup

    browser_config = CRAWLER_CONFIG.get("zhilian_browser", {})
    max_pages = browser_config.get("max_pages", CRAWLER_CONFIG["max_pages"])
    render_wait = browser_config.get("render_wait_seconds", 3)
    min_cards = browser_config.get("min_cards_per_page", 5)
    cookie = CRAWLER_CONFIG["cookies"].get("zhilian", "")
    jobs: list[dict[str, Any]] = []
    seen_pages: set[tuple[str, ...]] = set()
    seen_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = (
            "https://sou.zhaopin.com/?jl=530&kw="
            f"{quote_plus(keyword)}&p={page_num}"
        )
        logger.info("Zhilian browser crawl: keyword=%s page=%d", keyword, page_num)
        try:
            page.get(url)
            page.wait.doc_loaded()
        except Exception as e:  # noqa: BLE001
            logger.warning("Zhilian page load failed for keyword=%s page=%d: %s", keyword, page_num, e)
            break
        # 首次访问后注入 Cookie 并刷新，绕过 WAF 登录态校验
        if cookie and page_num == 1:
            try:
                page.set.cookies(cookie)
                page.refresh()
                page.wait.doc_loaded()
            except Exception as e:  # noqa: BLE001
                logger.warning("Zhilian cookie injection failed: %s", e)
        try:
            page.wait.ele_displayed(ZHILIAN_CARD_SELECTOR, timeout=CRAWLER_CONFIG["timeout"])
        except Exception:  # noqa: BLE001
            logger.warning("Zhilian has no rendered cards for keyword=%s page=%d", keyword, page_num)
            break

        if render_wait:
            page.wait(render_wait)
        cards = BeautifulSoup(page.html, "lxml").select(ZHILIAN_CARD_SELECTOR)
        page_jobs = [
            job
            for card in cards
            if (job := _parse_zhilian_browser_card(card, city)) is not None
        ]
        page_signature = tuple(sorted(job["job_id"] for job in page_jobs))
        if not page_jobs or page_signature in seen_pages:
            logger.info("Zhilian page repeated or contained no jobs; stopping keyword=%s", keyword)
            break
        seen_pages.add(page_signature)

        new_jobs = [job for job in page_jobs if job["job_id"] not in seen_ids]
        if not new_jobs:
            break
        seen_ids.update(job["job_id"] for job in new_jobs)
        jobs.extend(new_jobs)

        if len(cards) < min_cards:
            break
        _polite_sleep()

    return jobs


def _parse_zhilian_browser_card(card, fallback_city: str) -> dict[str, Any] | None:
    """Normalize a rendered Zhilian result card into the project job schema."""
    title_node = card.select_one(".jobinfo__name")
    title = _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        return None

    link = card.select_one('.jobinfo__name[href], a[href*="/jobdetail/"]')
    url = urljoin("https://www.zhaopin.com", link.get("href", "")) if link else ""
    company_node = card.select_one(".companyinfo__name")
    company = _clean_text(
        company_node.get("title", "") or company_node.get_text(" ", strip=True)
        if company_node else ""
    )
    info_items = [
        _clean_text(node.get_text(" ", strip=True))
        for node in card.select(".jobinfo__other-info-item")
    ]
    location = info_items[0] if info_items else ""
    requirements = " ".join(info_items[1:])
    salary = _first_card_text(card, ".jobinfo__salary, .salary, .job-money")
    text = _clean_text(card.get_text(" ", strip=True))

    if not salary:
        match = re.search(r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[kK万]|面议", text)
        salary = _clean_text(match.group(0)) if match else ""
    experience_match = re.search(r"\d+(?:\s*-\s*\d+)?年|经验不限|应届", requirements or text)
    education_match = re.search(r"本科|硕士|博士|大专|学历不限", requirements or text)
    skills = [
        _clean_text(node.get_text(" ", strip=True))
        for node in card.select(".joblist-box__item-tag")
        if _clean_text(node.get_text(" ", strip=True))
    ]
    city = location or fallback_city
    job_id = _stable_job_id("zhilian", title, company, city, url)
    jd_text = _build_jd_text(title, company, skills, requirements)

    return {
        "job_id": job_id,
        "platform": "zhilian",
        "title": title,
        "company": company,
        "company_size": "",
        "salary": salary,
        "city": city,
        "experience": experience_match.group(0) if experience_match else "",
        "education": education_match.group(0) if education_match else "",
        "skills": list(dict.fromkeys(skills)),
        "jd_text": jd_text,
        "responsibilities": requirements,
        "requirements": requirements,
        "is_big_tech": False,
        "match_count": 0,
        "crawled_at": datetime.now().strftime("%Y-%m-%d"),
        "url": _clean_url(url),
    }


def _first_card_text(card, selector: str) -> str:
    node = card.select_one(selector)
    return _clean_text(node.get_text(" ", strip=True) if node else "")


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_url(value: Any) -> str:
    return "".join(str(value or "").split())


def _stable_job_id(platform: str, title: str, company: str, city: str, url: str) -> str:
    identity = _clean_url(url) or "|".join(
        [_clean_text(title), _clean_text(company), _clean_text(city)]
    )
    digest = hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]
    return f"{platform}_{digest}"


def _crawl_zhilian(keyword: str, city: str) -> list[dict[str, Any]]:
    """智联招聘：httpx + Cookie + HTML 解析。"""
    logger.info("智联招聘爬取: keyword=%s, city=%s", keyword, city)
    return _httpx_html_crawl(
        platform="zhilian",
        search_url="https://sou.zhaopin.com/?jl=530&kw={keyword}",
        keyword=keyword,
        city=city,
    )


def _crawl_jobui(keyword: str, city: str) -> list[dict[str, Any]]:
    """Crawl the public Jobui search result page using its configured selectors."""
    return _crawl_configured_html_platform("jobui", keyword, city)


def _crawl_51job(keyword: str, city: str) -> list[dict[str, Any]]:
    """Crawl the public 51job search result page using its configured selectors."""
    return _crawl_configured_html_platform("51job", keyword, city)


def _crawl_configured_html_platform(
    platform: str, keyword: str, city: str
) -> list[dict[str, Any]]:
    source = CRAWLER_CONFIG.get("html_sources", {}).get(platform)
    if not source:
        raise ValueError(f"No HTML source configuration for platform: {platform}")
    return _httpx_html_crawl(
        platform=platform,
        search_url=source["search_url"],
        keyword=keyword,
        city=city,
        page_param=source.get("page_param", "page"),
    )


def _httpx_html_crawl(
    platform: str,
    search_url: str,
    keyword: str,
    city: str,
    page_param: str = "page",
) -> list[dict[str, Any]]:
    """通用 httpx + BeautifulSoup HTML 解析骨架。

    各平台页面结构不同，_parse_list_html 需按平台适配。
    反爬触发时抛出异常，由上层降级到本地策展数据。
    """
    try:
        import httpx
    except ImportError as e:
        raise ImportError("缺少依赖 httpx，请执行: pip install httpx") from e

    url = search_url.format(keyword=keyword)
    headers = dict(CRAWLER_CONFIG["headers"])

    # 附加登录 Cookie（若已配置），绕过登录态校验
    cookie = CRAWLER_CONFIG.get("cookies", {}).get(platform, "")
    if cookie:
        headers["Cookie"] = cookie
        logger.info("平台 %s 已附加 Cookie（%d 字符）", platform, len(cookie))

    jobs: list[dict[str, Any]] = []
    with httpx.Client(
        headers=headers, timeout=CRAWLER_CONFIG["timeout"], follow_redirects=True
    ) as client:
        for page_num in range(1, CRAWLER_CONFIG["max_pages"] + 1):
            try:
                resp = client.get(url, params={page_param: page_num})
                resp.raise_for_status()
            except Exception as e:  # noqa: BLE001
                logger.warning("%s 第 %d 页请求失败: %s", platform, page_num, e)
                break

            page_jobs = _parse_list_html(platform, resp.text, keyword, city)
            if not page_jobs:
                break
            jobs.extend(page_jobs)
            _polite_sleep()

    return jobs


def _parse_list_html(
    platform: str, html: str, keyword: str, city: str
) -> list[dict[str, Any]]:
    """解析搜索列表页 HTML，提取岗位卡片。

    各平台选择器不同，这里提供基于 BeautifulSoup 的通用骨架，
    实际需按目标平台的 DOM 结构补充选择器。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise ImportError(
            "缺少依赖 beautifulsoup4，请执行: pip install beautifulsoup4"
        ) from e

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:  # lxml is an optional performance dependency.
        logger.warning("lxml parser unavailable; using html.parser: %s", e)
        soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    source_config = CRAWLER_CONFIG.get("html_sources", {}).get(platform, {})
    source_selectors = source_config.get("selectors", {})

    # Each new public HTML source supplies selectors through CRAWLER_CONFIG.
    card_selectors = {
        "lagou": ".item__10RTO",
        "liepin": ".job-list-item",
        "zhilian": ".joblist-box__item",
    }
    selector = source_selectors.get("card", card_selectors.get(platform, ".job-item"))
    title_selector = source_selectors.get("title", ".title, .job-title, h3")
    company_selector = source_selectors.get("company", ".company, .company-name")
    salary_selector = source_selectors.get("salary", ".salary, .money__3eAe5")
    city_selector = source_selectors.get("city", ".city, .job-area, .job-location")
    base_url = source_config.get("base_url", _platform_base_url(platform))

    for card in soup.select(selector):
        try:
            title = _safe_text(card, title_selector)
            company = _safe_text(card, company_selector)
            salary = _safe_text(card, salary_selector)
            if not title:
                continue
            link = card.select_one("a[href]")
            url = urljoin(base_url, link.get("href", "")) if link else ""
            job_city = _safe_text(card, city_selector) or city
            jobs.append(
                {
                    "job_id": _stable_job_id(platform, title, company, job_city, url),
                    "platform": platform,
                    "title": title,
                    "company": company,
                    "company_size": "",
                    "salary": salary,
                    "city": job_city,
                    "experience": "",
                    "education": "",
                    "skills": [],
                    "jd_text": _build_jd_text(title, company, [], ""),
                    "responsibilities": "",
                    "requirements": "",
                    "is_big_tech": False,
                    "match_count": 0,
                    "crawled_at": datetime.now().strftime("%Y-%m-%d"),
                    "url": _clean_url(url),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("解析 %s 单条岗位失败: %s", platform, e)

    return jobs


def _safe_text(element, selector: str) -> str:
    """安全提取元素内首个匹配选择器的文本。"""
    node = element.select_one(selector)
    return _clean_text(node.get_text(" ", strip=True) if node else "")


def _platform_base_url(platform: str) -> str:
    return {
        "lagou": "https://www.lagou.com",
        "liepin": "https://www.liepin.com",
        "zhilian": "https://sou.zhaopin.com",
    }.get(platform, "")


def crawl_job_detail(job_url: str, platform: str) -> dict[str, Any]:
    """爬取单个岗位详情页，获取完整 JD。

    Args:
        job_url: 岗位详情页 URL
        platform: 所属平台

    Returns:
        完整岗位信息字典（含 jd_text 全文）
    """
    try:
        import httpx
    except ImportError as e:
        raise ImportError("缺少依赖 httpx，请执行: pip install httpx") from e

    headers = dict(CRAWLER_CONFIG["headers"])
    with httpx.Client(headers=headers, timeout=CRAWLER_CONFIG["timeout"],
                      follow_redirects=True) as client:
        resp = client.get(job_url)
        resp.raise_for_status()
        html = resp.text

    # 注意：需按平台适配详情页 JD 全文解析（不同平台 DOM 结构不同）
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        detail_selectors = {
            "boss": ".job-detail",
            "lagou": ".job-detail",
            "liepin": ".job-detail",
            "zhilian": ".job-detail",
        }
        node = soup.select_one(detail_selectors.get(platform, ".job-detail"))
        jd_text = node.get_text("\n", strip=True) if node else ""
    except Exception as e:  # noqa: BLE001
        logger.warning("解析详情页失败: %s", e)
        jd_text = ""

    return {
        "job_id": f"{platform}_{hashlib.md5(job_url.encode()).hexdigest()[:12]}",
        "platform": platform,
        "jd_text": jd_text,
        "url": job_url,
        "crawled_at": datetime.now().strftime("%Y-%m-%d"),
    }


# ══════════════════════════════════════════════
# 去重 / 标记 / 工具函数
# ══════════════════════════════════════════════
def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按岗位 ID 去重，同平台去重 + 跨平台去重。

    跨平台去重策略：按「岗位名称 + 公司名 + 地点」组合判断。
    """
    seen_ids: set[str] = set()
    seen_cross: set[str] = set()
    result: list[dict[str, Any]] = []

    for job in jobs:
        job = dict(job)
        for field in ("job_id", "title", "company", "city", "url"):
            job[field] = _clean_url(job.get(field, "")) if field == "url" else _clean_text(job.get(field, ""))

        job_id = str(job.get("job_id", ""))
        # 同平台按 job_id 去重
        if job_id:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

        # 跨平台按 (title, company, city) 组合去重
        cross_key = "|".join(
            [
                job["title"].lower(),
                job["company"].lower(),
                job["city"],
            ]
        )
        if cross_key != "||" and cross_key in seen_cross:
            continue
        seen_cross.add(cross_key)

        result.append(job)

    return result


def mark_premium_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标记大厂（BAT/字节/华为等）和高频匹配岗位。"""
    for job in jobs:
        company = job.get("company", "")
        job["is_big_tech"] = any(big in company for big in BIG_TECH_COMPANIES)
        job["is_high_frequency"] = (
            job.get("match_count", 0) >= HIGH_FREQUENCY_THRESHOLD
        )
    return jobs


def _build_jd_text(title: str, company: str, skills: list[str], description: str) -> str:
    """拼接岗位全文 JD（用于向量化）。"""
    parts = [
        f"岗位：{title}",
        f"公司：{company}",
        f"技能：{', '.join(skills)}" if skills else "",
        f"职位描述：{description}" if description else "",
    ]
    return "\n".join(p for p in parts if p)


def _polite_sleep() -> None:
    """请求间隔，加入随机抖动避免触发反爬。"""
    base = CRAWLER_CONFIG["request_interval"]
    time.sleep(base + random.uniform(0, 1.5))


def _load_curated_data(platform: str, keyword: str) -> list[dict[str, Any]]:
    """第四级降级：加载本地策展数据（离线兜底，永远能用）。

    策展数据放在 data/raw/curated_{platform}.json，
    可按关键词简单过滤。
    """
    curated_file = Path(PATH_CONFIG["raw_data_dir"]) / f"curated_{platform}.json"
    if not curated_file.exists():
        logger.info("无本地策展数据: %s", curated_file)
        return []

    try:
        with open(curated_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取策展数据失败: %s", e)
        return []

    if not isinstance(data, list):
        return []

    kw = keyword.strip().lower()
    if kw:
        data = [
            job for job in data
            if kw in str(job.get("title", "")).lower()
            or kw in str(job.get("jd_text", "")).lower()
        ]
    logger.info("从本地策展数据加载 %d 个岗位（平台 %s）", len(data), platform)
    return data


def save_jobs(jobs: list[dict[str, Any]], tag: str = "") -> str:
    """将爬取结果存档为 JSON 文件（按日期命名）。

    Args:
        jobs: 岗位列表
        tag: 文件名附加标签（如关键词）

    Returns:
        存档文件路径
    """
    out_dir = Path(PATH_CONFIG["crawled_jobs_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_{tag}" if tag else ""
    filename = f"jobs_{date_str}{suffix}.json"
    out_path = out_dir / filename

    temp_path = out_path.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    temp_path.replace(out_path)

    logger.info("岗位数据已存档: %s（%d 条）", out_path, len(jobs))
    return str(out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 自测示例：爬取 BOSS 直聘北京 Python 岗位
    results = crawl_jobs("Python", "北京", platforms=["boss"])
    print(f"爬取到 {len(results)} 个岗位")
    if results:
        save_jobs(results, tag="python_北京")
