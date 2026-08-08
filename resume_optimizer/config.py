"""
全局配置文件
集中管理 API Key、模型名、路径、爬虫参数等配置项。

使用方式：
    from config import CONFIG
    api_key = CONFIG["llm"]["api_key"]

注意：
    生产环境建议通过环境变量注入敏感信息（如 API Key），
    不要将真实 Key 硬编码或提交到版本库。
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
# 大语言模型配置（DeepSeek）
# DeepSeek 提供 OpenAI 兼容接口
# ──────────────────────────────────────────────
LLM_CONFIG = {
    "provider": "deepseek",
    "api_key": os.getenv("DEEPSEEK_API_KEY", "sk-bc783143515b42dab04ea20b1cd0b84a"),
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-chat",  # deepseek-chat / deepseek-reasoner
    "temperature": 0.3,             # 简历优化偏稳定，温度调低
    "max_tokens": 4096,
    "timeout": 120,
}

# ──────────────────────────────────────────────
# Embedding 模型配置（BGE-large-zh-v1.5）
# ──────────────────────────────────────────────
EMBEDDING_CONFIG = {
    # 使用 sentence-transformers 本地加载 BGE 模型
    "model_name": "BAAI/bge-large-zh-v1.5",
    "device": "cpu",  # 有 GPU 可改为 "cuda"
}

# ──────────────────────────────────────────────
# 向量数据库配置（ChromaDB）
# ──────────────────────────────────────────────
CHROMA_CONFIG = {
    "persist_directory": str(BASE_DIR / "data" / "chroma_db"),
    "collection_fulltext": "jd_fulltext",   # 岗位全文 JD
    "collection_premium": "jd_premium",     # 大厂 + 高频岗位
}

# ──────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────
PATH_CONFIG = {
    "input_dir": str(BASE_DIR / "input"),            # 原始简历 PDF
    "output_dir": str(BASE_DIR / "output"),          # 优化后简历
    "raw_data_dir": str(BASE_DIR / "data" / "raw"),  # 爬虫原始 JSON
    "crawled_jobs_dir": str(BASE_DIR / "data" / "crawled_jobs"),  # 每日爬取存档
}

# ──────────────────────────────────────────────
# 爬虫配置
# ──────────────────────────────────────────────
CRAWLER_CONFIG = {
    # 启用的平台
    "platforms": ["boss", "lagou", "liepin", "zhilian"],
    # 默认爬取城市
    "default_city": "全国",
    # 默认爬取关键词列表（每日定时任务使用）
    "keywords": [
        "Python", "Java", "前端", "产品经理", "数据分析",
        "算法工程师", "测试", "运维", "UI设计", "运营",
    ],
    # 请求间隔（秒），避免触发反爬
    "request_interval": 3,
    # 单个关键词最大爬取页数
    "max_pages": 3,
    # 请求超时（秒）
    "timeout": 30,
    # 请求头
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
    "hour": 2,      # 凌晨 2 点执行
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
}
