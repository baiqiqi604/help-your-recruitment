"""
面试/笔试经验爬虫（依据《面试笔试经验知识库设计》）

职责：
1. 从公开低反爬站点抓取面试经验/笔试算法题原始素材
2. 优先：CSDN、掘金（浏览器渲染 + BeautifulSoup 解析）
3. 力扣题解：公开题目页抓取（部分需登录，失败降级）
4. 输出：原始素材列表（标题/正文/来源 URL），供加工层 LLM 结构化

反爬策略（复用智联/猎聘浏览器渲染经验）：
- DrissionPage 真实浏览器渲染，绕过 JS 动态渲染
- 单条失败不崩溃、分页去重、礼貌等待

依赖：DrissionPage, beautifulsoup4, httpx
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from config import CRAWLER_CONFIG, PATH_CONFIG

logger = logging.getLogger(__name__)

# 抓取目标站点（公开、低反爬）
EXPERIENCE_PLATFORMS = ["csdn", "juejin"]

# 默认抓取关键词（可覆盖）——聚焦 AI 产品经理 / Agent 工程师方向
DEFAULT_KEYWORDS = [
    "AI产品经理 面试题", "AI产品经理 面经", "大模型产品经理 面试",
    "Agent工程师 面试", "AI Agent 工程师 面经", "LLM Agent 面试题",
    "大模型应用开发 笔试", "RAG 面试题", "提示词工程 面试",
]

CSDN_SEARCH_URL = "https://so.csdn.net/so/search?q={keyword}&t=blog"
JUEJIN_SEARCH_URL = "https://juejin.cn/search?query={keyword}&type=0"


def crawl_experiences(
    keywords: list[str] | None = None,
    platforms: list[str] | None = None,
    max_pages: int = 2,
    max_items: int = 0,
) -> list[dict[str, Any]]:
    """抓取面试/笔试经验原始素材（复用同一浏览器会话）。

    Args:
        keywords: 搜索关键词（默认 DEFAULT_KEYWORDS 前若干）
        platforms: 站点列表（默认 csdn, juejin）
        max_pages: 每站每关键词最大抓取页数
        max_items: 单次最多抓取条数（0 = 不限制；用于控制耗时）

    Returns:
        [
            {
                "source": "csdn",
                "title": "...",
                "url": "https://...",
                "content": "正文全文...",
                "keyword": "Python 面试题",
                "collected_at": "2026-08-09",
            }, ...
        ]
    """
    cleaned_keywords = list(
        dict.fromkeys(k.strip() for k in (keywords or DEFAULT_KEYWORDS) if k.strip())
    )
    if not cleaned_keywords:
        return []
    selected = [p for p in (platforms or EXPERIENCE_PLATFORMS) if p in EXPERIENCE_PLATFORMS]
    if not selected:
        return []

    try:
        from DrissionPage import ChromiumPage
    except ImportError as e:
        raise ImportError("DrissionPage is required for experience crawling") from e

    page = ChromiumPage()
    items: list[dict[str, Any]] = []
    try:
        for platform in selected:
            for keyword in cleaned_keywords:
                try:
                    if platform == "csdn":
                        items.extend(_crawl_csdn_keyword(page, keyword, max_pages))
                    elif platform == "juejin":
                        items.extend(_crawl_juejin_keyword(page, keyword, max_pages))
                except Exception as e:  # noqa: BLE001
                    logger.warning("站点 %s 关键词 %s 抓取失败: %s", platform, keyword, e)
                if max_items and len(items) >= max_items:
                    logger.info("达到 max_items=%d，提前结束", max_items)
                    break
            if max_items and len(items) >= max_items:
                break
    finally:
        try:
            page.quit()
        except Exception:  # noqa: BLE001
            pass

    return _deduplicate_items(items)[: max_items or None]


def _crawl_csdn_keyword(page, keyword: str, max_pages: int) -> list[dict[str, Any]]:
    """抓取 CSDN 搜索结果页中的面经/面试题文章。"""
    from bs4 import BeautifulSoup

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = CSDN_SEARCH_URL.format(keyword=quote_plus(keyword))
        if page_num > 1:
            url += f"&p={page_num}"
        logger.info("CSDN 抓取: keyword=%s page=%d", keyword, page_num)
        try:
            page.get(url)
            page.wait.doc_loaded()
            page.wait(2)
        except Exception as e:  # noqa: BLE001
            logger.warning("CSDN 页面加载失败: %s", e)
            break

        soup = BeautifulSoup(page.html, "lxml")
        # CSDN 搜索结果：匹配 blog.csdn.net 文章链接（类名不稳定，用链接模式更鲁棒）
        seen_urls: set[str] = set()
        found = 0
        for link in soup.select('a[href*="blog.csdn.net"][href*="/article/details/"]'):
            href = link.get("href", "").split("?")[0]
            if not href.startswith("http"):
                continue
            if href in seen_urls:
                continue
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue
            seen_urls.add(href)
            # 正文：点开详情页抓取（失败则仅存标题+摘要）
            content = _fetch_article_content(page, href)
            items.append(
                {
                    "source": "csdn",
                    "title": title,
                    "url": href,
                    "content": content,
                    "keyword": keyword,
                    "collected_at": datetime.now().strftime("%Y-%m-%d"),
                }
            )
            found += 1
        logger.info("CSDN 关键词 %s 第 %d 页抓取 %d 条", keyword, page_num, found)
        if found == 0:
            break
        _polite_sleep()
    return items


def _crawl_juejin_keyword(page, keyword: str, max_pages: int) -> list[dict[str, Any]]:
    """抓取掘金搜索结果页中的面经/面试题文章。"""
    from bs4 import BeautifulSoup

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = JUEJIN_SEARCH_URL.format(keyword=quote_plus(keyword))
        if page_num > 1:
            url += f"&p={page_num}"
        logger.info("掘金抓取: keyword=%s page=%d", keyword, page_num)
        try:
            page.get(url)
            page.wait.doc_loaded()
            page.wait(3)  # 掘金搜索结果异步渲染，等待更久
        except Exception as e:  # noqa: BLE001
            logger.warning("掘金页面加载失败: %s", e)
            break

        soup = BeautifulSoup(page.html, "lxml")
        # 掘金搜索结果：匹配 /post/ 文章链接（相对路径，需补全域名）
        seen_urls: set[str] = set()
        found = 0
        for link in soup.select('a[href*="/post/"]'):
            raw_href = link.get("href", "")
            href = raw_href.split("?")[0]
            if href.startswith("/"):
                href = "https://juejin.cn" + href
            if not href.startswith("http"):
                continue
            if href in seen_urls:
                continue
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue
            seen_urls.add(href)
            content = _fetch_article_content(page, href)
            items.append(
                {
                    "source": "juejin",
                    "title": title,
                    "url": href,
                    "content": content,
                    "keyword": keyword,
                    "collected_at": datetime.now().strftime("%Y-%m-%d"),
                }
            )
            found += 1
        logger.info("掘金关键词 %s 第 %d 页抓取 %d 条", keyword, page_num, found)
        if found == 0:
            break
        _polite_sleep()
    return items


def _fetch_article_content(page, url: str, max_chars: int = 6000) -> str:
    """打开文章详情页，提取正文纯文本（失败返回空串）。"""
    try:
        page.get(url)
        page.wait.doc_loaded()
        page.wait(1.5)
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page.html, "lxml")
        # 通用正文选择器（按站点结构尽力提取）
        content_node = soup.select_one(
            "article, .article_content, .markdown-body, "
            ".article-content, .markdown-body-container, #article-content, "
            "[class*='article-content'], [class*='markdown']"
        )
        if not content_node:
            return ""
        text = content_node.get_text("\n", strip=True)
        return text[:max_chars]
    except Exception as e:  # noqa: BLE001
        logger.debug("正文抓取失败 %s: %s", url, e)
        return ""


def _deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 URL 去重。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _stable_id(item: dict[str, Any]) -> str:
    """生成稳定 ID（内容指纹）。"""
    identity = f"{item.get('source', '')}_{item.get('url', '')}_{item.get('title', '')}"
    return hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]


def save_raw_experiences(items: list[dict[str, Any]], tag: str = "") -> str:
    """将原始素材保存为 JSON（data/raw/experience/ 目录）。

    Returns:
        保存的文件路径
    """
    if not items:
        raise ValueError("没有可保存的面试经验素材")

    out_dir = Path(PATH_CONFIG["raw_data_dir"]) / "experience"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"experiences_{ts}{('_' + tag) if tag else ''}.json"
    out_path = out_dir / filename

    payload = []
    for item in items:
        payload.append({**item, "item_id": _stable_id(item)})

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("面试经验素材已存档: %s（%d 条）", out_path, len(payload))
    return str(out_path)


def load_raw_experiences() -> list[dict[str, Any]]:
    """加载 data/raw/experience/ 下全部原始素材 JSON。"""
    exp_dir = Path(PATH_CONFIG["raw_data_dir"]) / "experience"
    if not exp_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for json_file in sorted(exp_dir.glob("experiences_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items.extend(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("素材文件解析失败 %s: %s", json_file, e)
    return items


def save_manual_experience(
    text: str,
    company: str = "",
    role: str = "",
    stage: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    """保存用户手动粘贴的面经/笔试经验（覆盖高反爬平台，如牛客等）。

    该素材标记 source=manual，与爬虫素材同目录存档，后续统一由加工层结构化入库。

    Args:
        text: 用户粘贴的面经原文（必填）
        company: 公司名（可选）
        role: 岗位名（可选）
        stage: 面试轮次（可选，HR面/业务面/专业面/主管面/终面/笔试）
        source_url: 来源链接（可选）

    Returns:
        保存后的素材 dict（含 item_id）

    Raises:
        ValueError: 面经文本为空
    """
    if not text or not text.strip():
        raise ValueError("面经文本不能为空")

    item = {
        "source": "manual",
        "title": f"手动录入_{company or '通用'}_{role or '通用'}"[:80],
        "url": source_url or "",
        "content": text.strip(),
        "keyword": "",
        "company": company.strip(),
        "role": role.strip(),
        "stage": stage.strip(),
        "collected_at": datetime.now().strftime("%Y-%m-%d"),
    }
    item["item_id"] = _stable_id(item)

    # 存档：手动素材写入独立 JSON（避免与爬虫批次混淆）
    out_dir = Path(PATH_CONFIG["raw_data_dir"]) / "experience"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"manual_{ts}_{item['item_id']}.json"
    out_path.write_text(json.dumps([item], ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("手动面经已存档: %s", out_path)
    return item


def _polite_sleep() -> None:
    """礼貌等待，降低反爬风险。"""
    interval = float(CRAWLER_CONFIG.get("request_interval", 3))
    time.sleep(interval * random.uniform(0.8, 1.4))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    items = crawl_experiences(keywords=["Python 面试题"], max_pages=1)
    print(f"抓取到 {len(items)} 条原始素材")
    for item in items[:3]:
        print(f"- [{item['source']}] {item['title']} ({item['url'][:60]})")
    if items:
        path = save_raw_experiences(items, tag="test")
        print(f"已保存: {path}")
