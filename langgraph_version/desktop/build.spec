# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：AI 简历优化 Agent 桌面版（onedir + windowed）。

构建命令：
    pyinstaller desktop/build.spec --noconfirm \
        --distpath desktop/dist --workpath desktop/build

产物：desktop/dist/AI简历优化Agent/（整目录分发，exe 双击即用）
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(r"D:\项目\aiagent\langgraph_version")

# 需要全量收集的第三方包（含动态导入 / 数据文件 / 元数据）
COLLECT_PKGS = [
    "chromadb",
    "sentence_transformers",
    "transformers",
    "tokenizers",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "langgraph",
    "onnxruntime",
    "uvicorn",
    "fastapi",
    "pydantic",
]

datas, binaries, hiddenimports = [], [], []
for pkg in COLLECT_PKGS:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        datas += copy_metadata(pkg)
    except Exception as exc:  # 个别包收集失败不阻塞整体
        print(f"[warn] collect_all({pkg}) failed: {exc}")


def _add_dir(src_rel: str, dest: str = "") -> None:
    p = ROOT / src_rel
    if p.exists():
        datas.append((str(p), dest))


# 项目数据文件（首启由 launcher 复制到 exe 目录）
_add_dir("templates", "templates")
_add_dir("static", "static")
_add_dir("data/chroma_db", "data/chroma_db")
_add_dir("input", "input")
_add_dir(".env", ".")

# BGE 嵌入模型（HF hub 目录结构，随包离线加载）
MODEL_CACHE = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5"
if MODEL_CACHE.exists():
    datas.append((str(MODEL_CACHE), "hf_model/hub/models--BAAI--bge-small-zh-v1.5"))
else:
    raise SystemExit(f"未找到 BGE 模型缓存: {MODEL_CACHE}")

a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI简历优化Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed：不显示黑色控制台
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AI简历优化Agent",
)
