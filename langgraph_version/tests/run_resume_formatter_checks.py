"""
Resume Formatter 离线自检（不依赖 pytest，直接断言）。
运行：
    cd langgraph_version
    py -3 tests/run_resume_formatter_checks.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 将 langgraph_version 目录加入 sys.path（等价于在此目录下运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 复用测试用例中的 SAMPLE_DATA 和自检逻辑
from tests.test_resume_formatter import (
    SAMPLE_DATA,
    TestHeuristicParse,
    TestResumeCheck,
    TestTemplates,
    TestWriteCustomizedResumeHtml,
    TestWriteFiles,
    TestYamlRoundTrip,
)

from resume_formatter import (
    TEMPLATE_MODERN,
    TEMPLATE_PROFESSIONAL,
    TEMPLATE_TECH,
    render_resume_html,
    resume_from_yaml,
    resume_to_yaml,
    run_resume_check,
    write_resume_outputs,
)


def run() -> None:
    import traceback

    passed = 0
    failed: list[tuple[str, str]] = []

    # 简单的 pytest 替代：收集 Test 开头类内 test_ 开头方法，逐个执行
    classes = [
        TestTemplates(),
        TestHeuristicParse(),
        TestResumeCheck(),
        TestYamlRoundTrip(),
        TestWriteFiles(),
        TestWriteCustomizedResumeHtml(),
    ]

    for instance in classes:
        for name in dir(instance):
            if not name.startswith("test_"):
                continue
            fn = getattr(instance, name)
            if not callable(fn):
                continue
            case_id = f"{type(instance).__name__}::{name}"
            try:
                # 含 tmp_path 参数的方法需要临时目录
                import inspect

                sig = inspect.signature(fn)
                if "tmp_path" in sig.parameters:
                    with tempfile.TemporaryDirectory() as d:
                        fn(tmp_path=Path(d))
                else:
                    fn()
                passed += 1
                print(f"  ✓ {case_id}")
            except AssertionError as e:
                failed.append((case_id, f"AssertionError: {e}"))
                print(f"  ✗ {case_id} — {e}")
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc(limit=4)
                failed.append((case_id, f"{type(e).__name__}: {e}\n{tb}"))
                print(f"  ✗ {case_id} — {type(e).__name__}: {e}")

    # 三套模板体积目测
    print("\n── 模板输出尺寸 ──")
    for t in (TEMPLATE_MODERN, TEMPLATE_PROFESSIONAL, TEMPLATE_TECH):
        html = render_resume_html(SAMPLE_DATA, template=t)
        print(f"  {t}: {len(html):>7} bytes")

    # YAML 往返
    yaml_txt = resume_to_yaml(SAMPLE_DATA)
    restored = resume_from_yaml(yaml_txt)
    assert restored.basic.name == SAMPLE_DATA.basic.name
    print(f"\n── YAML 往返 OK (yaml={len(yaml_txt)} bytes) ──")

    # 检查报告示例输出
    results = run_resume_check(SAMPLE_DATA)
    total_pass = sum(1 for r in results if r.passed)
    score = round(total_pass / max(1, len(results)) * 100)
    print(f"── 检查清单: {total_pass}/{len(results)} 通过 (≈{score}分) ──")

    # 端到端写文件
    with tempfile.TemporaryDirectory() as d:
        out = write_resume_outputs(SAMPLE_DATA, d, base_name="demo_self_check", template=TEMPLATE_MODERN)
        print(f"── 文件写入: {Path(out['html_path']).name}  {Path(out['yaml_path']).name} ──")
        for k, p in out.items():
            if isinstance(p, str) and Path(p).exists():
                print(f"  {k}: {Path(p).stat().st_size} bytes")

    print("\n" + ("=" * 50))
    print(f"总测试：{passed + len(failed)}，通过：{passed}，失败：{len(failed)}")
    if failed:
        print("\n── 失败详情 ──")
        for case, reason in failed:
            print(f"  [{case}]\n    {reason.replace(chr(10), chr(10) + '    ')}")
        sys.exit(1)
    print("🎉 所有测试通过！")


if __name__ == "__main__":
    run()
