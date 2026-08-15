"""main.py CLI 关键路径测试（MOCK_LLM 模式，无真实 API 调用）。

覆盖 main.py 的低覆盖率区域（此前仅 32%）：
- cmd_optimize：成功全流程 / 缺公司名 / 简历文件不存在
- cmd_doctor：就绪报告
- cmd_chat：退出交互
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import config
import main


@pytest.fixture()
def isolated_output_dir(tmp_path, monkeypatch):
    """把 output 目录指向临时目录，避免测试污染真实 output/。"""
    out_dir = tmp_path / "output"
    monkeypatch.setitem(config.PATH_CONFIG, "output_dir", str(out_dir))
    return out_dir


def _sample_files(tmp_path) -> tuple[Path, Path]:
    resume = tmp_path / "resume.txt"
    resume.write_text("张三，3年Python后端开发经验，熟悉Django、MySQL、Redis。", encoding="utf-8")
    jd = tmp_path / "jd.txt"
    jd.write_text("岗位：Python后端开发工程师，3年以上经验，熟悉Django/MySQL/Redis。", encoding="utf-8")
    return resume, jd


def _optimize_args(tmp_path, company: str = "某科技有限公司"):
    resume, jd = _sample_files(tmp_path)
    return mock.Mock(resume=str(resume), jd=str(jd), job_id="", company=company)


# ──────────────────────────────────────────────
# cmd_optimize：一次性定制优化
# ──────────────────────────────────────────────
class TestCmdOptimize:
    def test_optimize_success_writes_archive(self, tmp_path, isolated_output_dir, capsys) -> None:
        args = _optimize_args(tmp_path)
        code = main.cmd_optimize(args)
        assert code == 0

        out = capsys.readouterr().out
        assert "定制完成" in out
        # 生成了纯文本存档
        archives = list(isolated_output_dir.glob("optimized_*.txt"))
        assert len(archives) == 1
        assert archives[0].read_text(encoding="utf-8").strip()

    def test_optimize_missing_company_returns_1(self, tmp_path, capsys) -> None:
        args = _optimize_args(tmp_path, company="")
        assert main.cmd_optimize(args) == 1
        assert "目标公司" in capsys.readouterr().out

    def test_optimize_missing_resume_raises(self, tmp_path) -> None:
        _, jd = _sample_files(tmp_path)
        args = mock.Mock(resume=str(tmp_path / "no_such.txt"), jd=str(jd), job_id="", company="某公司")
        with pytest.raises(FileNotFoundError):
            main.cmd_optimize(args)


# ──────────────────────────────────────────────
# cmd_doctor：环境自检
# ──────────────────────────────────────────────
class TestCmdDoctor:
    def test_doctor_reports_json(self, capsys) -> None:
        code = main.cmd_doctor(mock.Mock())
        report = json.loads(capsys.readouterr().out)
        assert "ready" in report
        assert "llm_mode" in report
        # MOCK 模式下应当就绪（无缺失依赖、无坏 JSON、LLM 可用）
        assert code == 0


# ──────────────────────────────────────────────
# cmd_chat：命令行对话
# ──────────────────────────────────────────────
class TestCmdChat:
    def test_chat_exit_on_quit_input(self, monkeypatch, capsys) -> None:
        inputs = iter(["exit"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        args = mock.Mock(session="test-session")
        main.cmd_chat(args)  # 不应抛异常
        assert "再见" in capsys.readouterr().out

    def test_chat_handles_eof(self, monkeypatch, capsys) -> None:
        def raise_eof(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        main.cmd_chat(mock.Mock(session="s"))
        assert "再见" in capsys.readouterr().out
