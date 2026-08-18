"""agent 对话流 / main CLI / validate_runtime / config 校验的确定性测试。

- agent.chat_with_agent：MOCK 模式返回模拟回复；_extract_reply_text 纯函数
- main：argparse 解析、简历/JD 读取（txt 直读、参数校验）
- validate_runtime：MOCK/API Key 分支、坏 JSON 文件检测
- config：非法 LLM_PROVIDER 在子进程中抛 ValueError（隔离验证，避免污染进程内单例）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import agent
import main
import pytest
import validate_runtime


# ──────────────────────────────────────────────
# agent 对话流（MOCK 模式）
# ──────────────────────────────────────────────
class TestAgentChat:
    def test_chat_mock_mode_returns_reply(self) -> None:
        reply = agent.chat_with_agent("你好，帮我分析这段 JD", session_id="test-s1")
        assert isinstance(reply, str)
        assert reply.strip()
        assert "MOCK" in reply

    def test_chat_empty_input_returns_prompt(self) -> None:
        assert "请输入内容" in agent.chat_with_agent("", "s1")
        assert "请输入内容" in agent.chat_with_agent("   ", "s1")

    def test_extract_reply_text_variants(self) -> None:
        extract = agent._extract_reply_text
        assert extract(None) == ""
        assert extract("纯文本") == "纯文本"
        assert extract([{"type": "text", "text": "块一"}, {"type": "tool_use"}]) == "块一"
        assert extract([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "ab"
        assert extract(123) == "123"
        assert extract([{"type": "image"}]) == ""


# ──────────────────────────────────────────────
# main CLI（argparse / 文件加载）
# ──────────────────────────────────────────────
class TestMainCli:
    def test_parser_requires_subcommand(self) -> None:
        parser = main.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_web_chat_doctor(self) -> None:
        parser = main.build_parser()
        assert parser.parse_args(["web"]).command == "web"
        assert parser.parse_args(["chat"]).command == "chat"
        args = parser.parse_args(["chat", "--session", "s1"])
        assert args.session == "s1"
        assert parser.parse_args(["doctor"]).command == "doctor"

    def test_parser_optimize_requires_resume(self) -> None:
        parser = main.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["optimize", "--jd", "jd.txt"])

    def test_load_resume_text_txt(self, tmp_path) -> None:
        path = tmp_path / "resume.txt"
        path.write_text("张三，Python 后端", encoding="utf-8")
        assert main._load_resume_text(str(path)) == "张三，Python 后端"

    def test_load_resume_text_missing_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            main._load_resume_text("no_such_file.txt")

    def test_load_jd_text_from_file(self, tmp_path) -> None:
        path = tmp_path / "jd.txt"
        path.write_text("岗位：Python 后端", encoding="utf-8")
        assert main._load_jd_text(str(path), "") == "岗位：Python 后端"

    def test_load_jd_text_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            main._load_jd_text("no_such_jd.txt", "")

    def test_load_jd_text_job_id_not_found_raises(self) -> None:
        # conftest 桩的 get_job_by_id 返回 None → 抛 ValueError
        with pytest.raises(ValueError):
            main._load_jd_text("", "boss_not_exists")

    def test_load_jd_text_neither_provided_raises(self) -> None:
        with pytest.raises(ValueError):
            main._load_jd_text("", "")


# ──────────────────────────────────────────────
# validate_runtime
# ──────────────────────────────────────────────
class TestValidateRuntime:
    def test_mock_mode_ready(self, monkeypatch) -> None:
        monkeypatch.setenv("MOCK_LLM", "1")
        report = validate_runtime.collect_diagnostics()
        assert report["llm_mode"] == "mock"
        # 本环境依赖齐全、无坏 JSON 时 ready
        assert report["ready"] is (not report["missing_dependencies"] and not report["invalid_job_files"])

    def test_missing_api_key_mode(self, monkeypatch) -> None:
        import config

        monkeypatch.delenv("MOCK_LLM", raising=False)
        monkeypatch.setitem(config.LLM_CONFIG, "api_key", "")
        report = validate_runtime.collect_diagnostics()
        assert report["llm_mode"] == "missing_api_key"
        assert report["ready"] is False

    def test_invalid_job_files_detected(self, monkeypatch, tmp_path) -> None:
        import config

        monkeypatch.setenv("MOCK_LLM", "1")
        bad_dir = tmp_path / "crawled"
        bad_dir.mkdir()
        (bad_dir / "bad.json").write_text("{not valid json", encoding="utf-8")
        monkeypatch.setitem(config.PATH_CONFIG, "raw_data_dir", str(tmp_path / "raw"))
        monkeypatch.setitem(config.PATH_CONFIG, "crawled_jobs_dir", str(bad_dir))

        report = validate_runtime.collect_diagnostics()
        assert len(report["invalid_job_files"]) == 1
        assert report["invalid_job_files"][0].endswith("bad.json")
        assert report["ready"] is False

    def test_valid_json_not_reported(self, monkeypatch, tmp_path) -> None:
        import config

        monkeypatch.setenv("MOCK_LLM", "1")
        good_dir = tmp_path / "raw"
        good_dir.mkdir()
        (good_dir / "ok.json").write_text(json.dumps([{"title": "Python 后端"}]), encoding="utf-8")
        monkeypatch.setitem(config.PATH_CONFIG, "raw_data_dir", str(good_dir))
        monkeypatch.setitem(config.PATH_CONFIG, "crawled_jobs_dir", str(tmp_path / "empty"))

        report = validate_runtime.collect_diagnostics()
        assert report["invalid_job_files"] == []


# ──────────────────────────────────────────────
# config 校验（子进程隔离，避免污染进程内 config 单例）
# ──────────────────────────────────────────────
class TestConfigValidation:
    LANGGRAPH_DIR = str(Path(__file__).resolve().parent.parent)

    def _run_import_config(self, extra_env: dict[str, str]) -> int:
        env = dict(os.environ)
        env["MOCK_LLM"] = "1"
        env["SKIP_DOTENV"] = "1"  # 隔离本机 .env，防止覆盖测试环境变量
        env.update(extra_env)
        result = subprocess.run(
            [sys.executable, "-c", "import config"],
            cwd=self.LANGGRAPH_DIR,
            env=env,
            capture_output=True,
            timeout=60,
        )
        return result.returncode

    def _run_validate_config(self, extra_env: dict[str, str]) -> int:
        env = dict(os.environ)
        env["MOCK_LLM"] = "1"
        env["SKIP_DOTENV"] = "1"  # 隔离本机 .env，防止覆盖测试环境变量
        env.update(extra_env)
        result = subprocess.run(
            [sys.executable, "-c", "import config; config.validate_config()"],
            cwd=self.LANGGRAPH_DIR,
            env=env,
            capture_output=True,
            timeout=60,
        )
        return result.returncode

    def test_valid_provider_imports_ok(self) -> None:
        assert self._run_import_config({"LLM_PROVIDER": "deepseek"}) == 0
        assert self._run_import_config({"LLM_PROVIDER": "zhipu"}) == 0

    def test_invalid_provider_import_ok(self) -> None:
        # 校验已延迟：非法 provider 时 import config 不再抛错（退出码 0）
        assert self._run_import_config({"LLM_PROVIDER": "bogus_provider"}) == 0

    def test_invalid_provider_validate_raises(self) -> None:
        # 显式调用 validate_config() 时抛 ValueError → 子进程退出码非 0
        assert self._run_validate_config({"LLM_PROVIDER": "bogus_provider"}) != 0

    def test_invalid_provider_api_key_placeholder_empty(self) -> None:
        # 非法 provider 时 LLM_CONFIG 使用空 api_key 占位（避免 import 崩溃）
        env = dict(os.environ)
        env["MOCK_LLM"] = "1"
        env["SKIP_DOTENV"] = "1"  # 隔离本机 .env，防止覆盖测试环境变量
        env["LLM_PROVIDER"] = "bogus_provider"
        result = subprocess.run(
            [sys.executable, "-c", "import config; print(repr(config.LLM_CONFIG['api_key']))"],
            cwd=self.LANGGRAPH_DIR,
            env=env,
            capture_output=True,
            timeout=60,
        )
        assert result.stdout.decode("utf-8", "replace").strip() == "''"

    def test_default_provider_is_deepseek(self) -> None:
        env = dict(os.environ)
        env.pop("LLM_PROVIDER", None)
        env["MOCK_LLM"] = "1"
        env["SKIP_DOTENV"] = "1"  # 隔离本机 .env，防止覆盖测试环境变量
        result = subprocess.run(
            [sys.executable, "-c", "import config; print(config.LLM_PROVIDER)"],
            cwd=self.LANGGRAPH_DIR,
            env=env,
            capture_output=True,
            timeout=60,
        )
        assert result.stdout.decode("utf-8", "replace").strip() == "deepseek"
