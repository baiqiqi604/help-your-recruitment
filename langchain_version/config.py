"""
全局配置文件
集中管理多 Provider LLM、路径、向量库、爬虫、定时任务等配置。

支持通过 .env 或环境变量注入敏感信息：
    LLM_PROVIDER=deepseek | openai | dashscope | zhipu
    DEEPSEEK_API_KEY=...
    OPENAI_API_KEY=...
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# 项目根目录
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

# 尝试加载 .env（失败则忽略，依赖环境变量）
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

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

if LLM_PROVIDER not in LLM_PROVIDERS:
    raise ValueError(
        f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，可选: {', '.join(LLM_PROVIDERS)}"
    )

_PROVIDER_CFG = LLM_PROVIDERS[LLM_PROVIDER]

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
# Embedding 模型配置（BGE-large-zh-v1.5）
# ──────────────────────────────────────────────
EMBEDDING_CONFIG = {
    "model_name": os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
    "device": os.getenv("EMBEDDING_DEVICE", "cpu"),  # 有 GPU 可改为 cuda
}

# ──────────────────────────────────────────────
# 向量数据库配置（ChromaDB）
# ──────────────────────────────────────────────
# RAG 与 langgraph 版共享同一向量库（interview_kb 等集合），避免重复建库
_SHARED_CHROMA_DIR = BASE_DIR.parent / "langgraph_version" / "data" / "chroma_db"
if not _SHARED_CHROMA_DIR.exists():
    _SHARED_CHROMA_DIR = BASE_DIR / "data" / "chroma_db"

CHROMA_CONFIG = {
    "persist_directory": str(_SHARED_CHROMA_DIR),
    "collection_fulltext": "jd_fulltext",   # 岗位全文 JD
    "collection_premium": "jd_premium",     # 大厂 + 高频岗位
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
CRAWLER_CONFIG = {
    "platforms": ["boss", "lagou", "liepin", "zhilian"],
    "default_city": "全国",
    "keywords": [
        "Python", "Java", "前端", "产品经理", "数据分析",
        "算法工程师", "测试", "运维", "UI设计", "运营",
    ],
    "request_interval": 3,   # 秒，避免触发反爬
    "max_pages": 3,
    "timeout": 30,
    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
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
    "path": PATH_CONFIG,
    "crawler": CRAWLER_CONFIG,
    "scheduler": SCHEDULER_CONFIG,
    "big_tech_companies": BIG_TECH_COMPANIES,
    "high_frequency_threshold": HIGH_FREQUENCY_THRESHOLD,
    "web": WEB_CONFIG,
}
