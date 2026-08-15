"""
全局配置文件
集中管理多 Provider LLM、路径、向量库、爬虫、定时任务等配置。

支持通过 .env 或环境变量注入敏感信息：
    LLM_PROVIDER=deepseek | openai | dashscope | zhipu
    DEEPSEEK_API_KEY=...
    OPENAI_API_KEY=...
"""

import os
import sys
from pathlib import Path

# ──────────────────────────────────────────────
# 项目根目录
# ──────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # PyInstaller 打包后：以 exe 所在目录为根（可写，数据文件由桌面启动器首启补齐）
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# 尝试加载 .env（失败则忽略，依赖环境变量）
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# ──────────────────────────────────────────────
# 模型离线加载兜底（任何启动入口生效）
# 说明：embedding / rerank 模型均本地缓存，必须离线加载；
# 网络受限时 HF 的 HEAD 联网检查会重试 5 次 × 超时（实测每次 20s+），
# 导致启动/首次检索被卡数分钟。这里 setdefault 兜底——
# start_server.bat / start_web_offline.py 已显式设置的值优先级更高；
# 直接 `python web_app.py` 直启等路径也自动生效。
# ──────────────────────────────────────────────
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

# ──────────────────────────────────────────────
# 多 Provider LLM 配置
# 统一走 OpenAI 兼容接口（ChatOpenAI）
# ──────────────────────────────────────────────
LLM_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "label": "DeepSeek",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "label": "OpenAI",
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-plus",
        "env_key": "DASHSCOPE_API_KEY",
        "label": "通义千问",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-4-flash",
        "env_key": "ZHIPU_API_KEY",
        "label": "智谱 GLM",
    },
}

# 当前启用的 provider（deepseek / openai / dashscope / zhipu）
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()

# 校验延迟到 validate_config()（真正使用 LLM 前调用），
# 避免 import config 在非交互场景（IDE 索引 / 文档工具 / 静态分析）被抛错打断。
_PROVIDER_CFG = LLM_PROVIDERS.get(LLM_PROVIDER)


def validate_config() -> None:
    """校验 LLM Provider 配置；非法时抛 ValueError。

    说明：import config 不再直接抛错，由调用方在真正使用 LLM 前显式调用
    （llm_client._make_llm / web 启动预热）。
    """
    if LLM_PROVIDER not in LLM_PROVIDERS:
        raise ValueError(
            f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，可选: {', '.join(LLM_PROVIDERS)}"
        )


if _PROVIDER_CFG is None:
    # 非法 provider：占位配置（api_key 为空），真正使用时由 validate_config() 拒绝
    _PROVIDER_CFG = {
        "label": LLM_PROVIDER,
        "env_key": "",
        "base_url": "",
        "model_name": "",
    }

LLM_CONFIG = {
    "provider": LLM_PROVIDER,
    "provider_label": _PROVIDER_CFG["label"],
    "api_key": os.getenv(_PROVIDER_CFG["env_key"], ""),
    "base_url": _PROVIDER_CFG["base_url"],
    "model_name": os.getenv("LLM_MODEL", _PROVIDER_CFG["model_name"]),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),  # 简历优化偏稳定
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "4096")),
    "timeout": int(os.getenv("LLM_TIMEOUT", "120")),
}

# ──────────────────────────────────────────────
# Embedding 模型配置（BGE-small-zh-v1.5）
# 说明：small（约 95MB）为实际部署口径（.env 与 exe 打包一致）；
# 若需 large（1.3GB，下载易超时）可显式设置 EMBEDDING_MODEL 覆盖。
# 注意：与 langgraph 版共享同一向量库，两版必须使用同一 Embedding 模型。
# ──────────────────────────────────────────────
EMBEDDING_CONFIG = {
    "model_name": os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
    "device": os.getenv("EMBEDDING_DEVICE", "cpu"),  # 有 GPU 可改为 cuda
}

# ──────────────────────────────────────────────
# 向量数据库配置（ChromaDB）
# ──────────────────────────────────────────────
# RAG 与 langgraph 版共享同一向量库（interview_kb 等集合），避免重复建库。
# 优先级：
#   1. CHROMA_DIR 环境变量显式指定（推荐，两版指向同一目录）；
#   2. 若 langgraph_version/data/chroma_db 存在则复用（旧自动探测逻辑，保留兼容）；
#   3. 否则使用本目录下的 data/chroma_db。
# 注意：两版同时运行时必须指向同一目录，否则会出现"看似共享实则分库"。
_CHROMA_DIR_ENV = os.getenv("CHROMA_DIR", "").strip()
if _CHROMA_DIR_ENV:
    _SHARED_CHROMA_DIR = Path(_CHROMA_DIR_ENV)
elif (BASE_DIR.parent / "langgraph_version" / "data" / "chroma_db").exists():
    _SHARED_CHROMA_DIR = BASE_DIR.parent / "langgraph_version" / "data" / "chroma_db"
else:
    _SHARED_CHROMA_DIR = BASE_DIR / "data" / "chroma_db"

CHROMA_CONFIG = {
    "persist_directory": str(_SHARED_CHROMA_DIR),
    "collection_fulltext": "jd_fulltext",   # 岗位全文 JD
    "collection_premium": "jd_premium",     # 大厂 + 高频岗位
    "collection_title": "jd_title",         # 岗位标题/技能短文本（检索单元，命中后映射回全文）
}

# ──────────────────────────────────────────────
# Rerank 重排配置（bge-reranker-v2-m3，跨编码器精排）
# 说明：
# - 懒加载：首次检索时才加载模型；加载失败（缺依赖/无网络/被墙）自动降级为
#   不重排，按向量距离原序返回，不影响功能。
# - 模型约 2GB，首次使用会从 HuggingFace 下载；国内网络可设 HF_ENDPOINT 镜像。
# - 测试环境请设 RERANK_ENABLED=0 跳过模型加载（tests/conftest.py 已默认设置）。
# ──────────────────────────────────────────────
# Rerank 模型默认路径：若本地已下载（models/bge-reranker-v2-m3，两版共享）则优先使用，
# 否则回退 HuggingFace 模型 ID（首次使用会联网下载；可设 HF_ENDPOINT 镜像）。
_LOCAL_RERANK_MODEL = BASE_DIR.parent / "models" / "bge-reranker-v2-m3"
_DEFAULT_RERANK_MODEL = (
    str(_LOCAL_RERANK_MODEL) if _LOCAL_RERANK_MODEL.exists() else "BAAI/bge-reranker-v2-m3"
)
RERANK_CONFIG = {
    "enabled": os.getenv("RERANK_ENABLED", "1") != "0",
    "model_name": os.getenv("RERANK_MODEL", _DEFAULT_RERANK_MODEL),
    "device": os.getenv("RERANK_DEVICE", EMBEDDING_CONFIG["device"]),
    # 粗召回倍数：先按 top_k * multiplier 召回候选，再重排取 top_k
    "candidate_multiplier": int(os.getenv("RERANK_CANDIDATE_MULTIPLIER", "5")),
    # 送入重排的候选上限（防超长列表拖慢打分）
    "max_candidates": int(os.getenv("RERANK_MAX_CANDIDATES", "50")),
}

# ──────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────
PATH_CONFIG = {
    "input_dir": str(BASE_DIR / "input"),            # 原始简历
    "output_dir": str(BASE_DIR / "output"),          # 优化后简历
    "raw_data_dir": str(BASE_DIR / "data" / "raw"),  # 爬虫原始 JSON
    "crawled_jobs_dir": str(BASE_DIR / "data" / "crawled_jobs"),  # 每日爬取存档
    "templates_dir": str(BASE_DIR / "templates"),    # Web 前端模板
}

# ──────────────────────────────────────────────
# 爬虫配置
# ──────────────────────────────────────────────
# 额外爬取关键词/平台：内置默认 + 环境变量扩展（CRAWLER_EXTRA_KEYWORDS /
# CRAWLER_EXTRA_PLATFORMS，逗号分隔），去重后写入配置。
_EXTRA_CRAWLER_KEYWORDS = ["Go", "C++", "人工智能", "数据开发", "网络安全"]
_ENV_EXTRA_CRAWLER_KEYWORDS = [
    keyword.strip()
    for keyword in os.getenv("CRAWLER_EXTRA_KEYWORDS", "").split(",")
    if keyword.strip()
]
_ENV_EXTRA_CRAWLER_PLATFORMS = [
    platform.strip()
    for platform in os.getenv("CRAWLER_EXTRA_PLATFORMS", "").split(",")
    if platform.strip()
]

CRAWLER_CONFIG = {
    # 岗位爬虫总开关：默认关闭（岗位库已降级，主流程不再依赖）
    # 如需启用：CRAWLER_ENABLED=1（并配置对应平台 Cookie）
    "enabled": os.getenv("CRAWLER_ENABLED", "0") != "0",
    "platforms": list(
        dict.fromkeys(
            ["boss", "lagou", "liepin", "zhilian", "jobui", "51job"]
            + _ENV_EXTRA_CRAWLER_PLATFORMS
        )
    ),
    "default_city": "全国",
    "keywords": list(
        dict.fromkeys(
            [
                "Python", "Java", "前端", "产品经理", "数据分析",
                "算法工程师", "测试", "运维", "UI设计", "运营",
            ]
            + _EXTRA_CRAWLER_KEYWORDS
            + _ENV_EXTRA_CRAWLER_KEYWORDS
        )
    ),
    "request_interval": float(os.getenv("CRAWLER_REQUEST_INTERVAL", "3")),
    "max_pages": int(os.getenv("CRAWLER_MAX_PAGES", "3")),
    "timeout": int(os.getenv("CRAWLER_TIMEOUT", "30")),
    "liepin_browser": {
        "enabled": os.getenv("LIEPIN_BROWSER_ENABLED", "0") != "0",
        "max_pages": int(os.getenv("LIEPIN_BROWSER_MAX_PAGES", "5")),
        "render_wait_seconds": float(
            os.getenv("LIEPIN_BROWSER_RENDER_WAIT_SECONDS", "2")
        ),
        "min_cards_per_page": int(
            os.getenv("LIEPIN_BROWSER_MIN_CARDS_PER_PAGE", "5")
        ),
    },
    "zhilian_browser": {
        "enabled": os.getenv("ZHILIAN_BROWSER_ENABLED", "0") != "0",
        "max_pages": int(os.getenv("ZHILIAN_BROWSER_MAX_PAGES", "3")),
        "render_wait_seconds": float(
            os.getenv("ZHILIAN_BROWSER_RENDER_WAIT_SECONDS", "3")
        ),
        "min_cards_per_page": int(
            os.getenv("ZHILIAN_BROWSER_MIN_CARDS_PER_PAGE", "5")
        ),
    },
    # Public HTML search sources. Add a source here to reuse the generic
    # paginated parser without adding another standalone crawler script.
    "html_sources": {
        "jobui": {
            "search_url": "https://www.jobui.com/jobs?keyword={keyword}",
            "base_url": "https://www.jobui.com",
            "page_param": "page",
            "selectors": {
                "card": ".job-item, .job-list-item, .job-list-item__content",
                "title": ".job-name, .job-title, h3, h2",
                "company": ".company-name, .company, .c-name",
                "salary": ".salary, .job-salary, .money",
                "city": ".job-area, .city, .job-location",
            },
        },
        "51job": {
            "search_url": "https://we.51job.com/pc/search?keyword={keyword}",
            "base_url": "https://we.51job.com",
            "page_param": "pageNo",
            "selectors": {
                "card": ".joblist-item, .job-item, article.job-item",
                "title": ".job-title, .jname, h3, h2",
                "company": ".company-name, .cname, .company",
                "salary": ".salary, .sal, .job-salary",
                "city": ".job-area, .work-area, .city",
            },
        },
    },
    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    },
    # 各平台登录 Cookie（从 .env 注入，绕过反爬登录态校验）
    "cookies": {
        "lagou": os.getenv("COOKIE_LAGOU", ""),
        "liepin": os.getenv("COOKIE_LIEPIN", ""),
        "zhilian": os.getenv("COOKIE_ZHILIAN", ""),
        "jobui": os.getenv("COOKIE_JOBUI", ""),
        "51job": os.getenv("COOKIE_51JOB", ""),
    },
}

# ──────────────────────────────────────────────
# 定时调度配置
# ──────────────────────────────────────────────
SCHEDULER_CONFIG = {
    "hour": 2,
    "minute": 0,
    "job_id": "daily_jd_crawl",
}

# ──────────────────────────────────────────────
# 大厂名单（用于标记优质岗位）
# ──────────────────────────────────────────────
BIG_TECH_COMPANIES = [
    "阿里巴巴", "腾讯", "百度", "字节跳动", "华为",
    "美团", "京东", "小米", "网易", "拼多多",
    "快手", "滴滴", "小红书", "B站", "蚂蚁集团",
]

# 高频岗位阈值：被匹配次数达到该值即标记为高频
HIGH_FREQUENCY_THRESHOLD = 5

# ──────────────────────────────────────────────
# Web 服务配置
# ──────────────────────────────────────────────
WEB_CONFIG = {
    "host": os.getenv("WEB_HOST", "127.0.0.1"),
    "port": int(os.getenv("WEB_PORT", "8000")),
}

# ──────────────────────────────────────────────
# 汇总导出
# ──────────────────────────────────────────────
CONFIG = {
    "llm": LLM_CONFIG,
    "embedding": EMBEDDING_CONFIG,
    "chroma": CHROMA_CONFIG,
    "rerank": RERANK_CONFIG,
    "path": PATH_CONFIG,
    "crawler": CRAWLER_CONFIG,
    "scheduler": SCHEDULER_CONFIG,
    "big_tech_companies": BIG_TECH_COMPANIES,
    "high_frequency_threshold": HIGH_FREQUENCY_THRESHOLD,
    "web": WEB_CONFIG,
}
