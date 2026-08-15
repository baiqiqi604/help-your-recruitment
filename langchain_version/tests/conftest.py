"""pytest 共享配置（langchain_version）。

- 统一开启 MOCK_LLM（不依赖真实 API Key / 网络）
- 用轻量桩替换重型知识库模块（chromadb / sentence-transformers），
  保证测试在未安装或未建库的环境下也能确定性运行
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

# 让测试能 import 项目根目录模块（chain / config / llm_client / web_app ...）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MOCK_LLM"] = "1"

# 测试环境跳过 Rerank 模型加载（bge-reranker-v2-m3 约 2GB，避免下载与不确定性）
os.environ["RERANK_ENABLED"] = "0"

# ──────────────────────────────────────────────
# 重型模块桩（避免测试依赖 chromadb / sentence-transformers）
# ──────────────────────────────────────────────
_FAKE_KB = mock.MagicMock()
_FAKE_KB.search_questions.return_value = []
_FAKE_KB.count_questions.return_value = 0
_FAKE_KB.get_questions_by_company.return_value = []
_FAKE_KB.get_algorithm_questions.return_value = []
_FAKE_KB.add_experiences.return_value = 0
sys.modules.setdefault("interview_knowledge_base", _FAKE_KB)

_FAKE_JD_KB = mock.MagicMock()
_FAKE_JD_KB.get_job_by_id.return_value = None
_FAKE_JD_KB.search_jds.return_value = []
_FAKE_JD_KB.get_premium_jobs.return_value = []
sys.modules.setdefault("jd_knowledge_base", _FAKE_JD_KB)
