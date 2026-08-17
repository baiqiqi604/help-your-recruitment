"""Dependency-free runtime preflight checks for the LangGraph application."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from config import LLM_CONFIG, PATH_CONFIG

REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "langchain": "langchain",
    "langchain_openai": "langchain-openai",
    "langgraph": "langgraph",
    "chromadb": "chromadb",
    "sentence_transformers": "sentence-transformers",
    "pdf2docx": "pdf2docx",
    "docx": "python-docx",
    "bs4": "beautifulsoup4",
    "httpx": "httpx",
    "dotenv": "python-dotenv",
}


def collect_diagnostics() -> dict[str, Any]:
    missing_dependencies = [
        label for module, label in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    invalid_job_files: list[str] = []
    for directory in (PATH_CONFIG["raw_data_dir"], PATH_CONFIG["crawled_jobs_dir"]):
        path = Path(directory)
        if not path.exists():
            continue
        for json_file in path.glob("*.json"):
            try:
                json.loads(json_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_job_files.append(str(json_file))

    mock_enabled = os.getenv("MOCK_LLM", "").strip().lower() in {"1", "true", "yes"}
    llm_ready = mock_enabled or bool(LLM_CONFIG["api_key"])
    ready = not missing_dependencies and not invalid_job_files and llm_ready
    return {
        "ready": ready,
        "llm_mode": "mock" if mock_enabled else ("configured" if llm_ready else "missing_api_key"),
        "missing_dependencies": missing_dependencies,
        "invalid_job_files": invalid_job_files,
    }


def main() -> int:
    report = collect_diagnostics()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
