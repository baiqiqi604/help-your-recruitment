# CI/CD 管线实施总结

> 实施日期：2026-08-18　|　涉及版本：langgraph_version（主力）/ langchain_version（并行）

## 一、背景

项目此前仅有基础 CI（`.github/workflows/ci.yml`：同步检查 + ruff lint + pytest 测试矩阵），存在以下问题：

- 无手动触发、无 pip 缓存，CI 重跑慢；
- 无 CD（发布）环节；
- langchain 版覆盖率仅 53.47%，**低于 60% 门槛，CI langchain 矩阵实际处于失败状态**（本地验证时发现）；
- lint 存在 isort 违规（`resume_writer.py` 局部 import），CI 一旦启用即红。

本次按「一般项目 CI/CD 标准」的简化版方案实施：增强 CI、新增 CD、补齐 langchain 测试，并修复 lint 阻塞项。

## 二、实施内容

### 1. CI 增强（`.github/workflows/ci.yml`）

| 改动 | 说明 |
|------|------|
| `workflow_dispatch` 触发 | 支持仓库页面手动触发 CI，便于验证 |
| pip 缓存 | lint / test job 的 `setup-python` 开启 `cache: pip`，重跑提速 |
| 既有检查保持 | sync-check（19 个共享文件逐字节一致）+ ruff lint + pytest 矩阵（3.10/3.11 × 双版本，覆盖率 ≥60%，`MOCK_LLM=1` 免密钥） |

### 2. CD 新增（`.github/workflows/release.yml`）

推送 `v*` tag（如 `git tag v0.1.0`）自动触发：

1. 同步一致性检查（`scripts/check_sync.py`）
2. ruff 静态检查
3. pytest 测试（langgraph 版，覆盖率 ≥60%，MOCK_LLM 模式）
4. 打包双版本 zip（`dist/langgraph_version.zip` / `dist/langchain_version.zip`）
5. 自动创建 GitHub Release（`softprops/action-gh-release`，自动生成 Release Notes）

> 项目为本地运行服务（web_app.py），无云端部署目标，故 CD 以「发布物打包」替代部署。

### 3. langchain 版测试补齐（覆盖率高危模块）

移植 langgraph 版 4 个仅依赖**共享模块**的测试文件（逐字节一致复制，`cmp` 验证）：

| 移植文件 | 覆盖模块 |
|----------|----------|
| `test_resume_io.py` | resume_reader / resume_writer |
| `test_resume_formatter.py` | resume_formatter / schemas |
| `test_knowledge_bases.py` | interview_knowledge_base / jd_knowledge_base |
| `test_llm_modules.py` | jd_analyzer / content_optimizer / company_researcher / interview_advisor / experience_processor |

> 未移植 `test_graph_flow` / `test_agent_cli` / `test_main_flow`（依赖版本特有代码 graph / agent / main；langchain 版已有 `test_chain.py` 覆盖 LCEL 管道）。

### 4. lint 阻塞修复

`resume_writer.py` 照片插入函数内局部 import 排序违规（isort I001），两版同步修复，恢复 CI lint 通过。

## 三、验证结果

| 检查项 | 结果 |
|--------|------|
| 同步一致性（check_sync） | ✅ 19 个共享文件两版完全一致 |
| ruff（CI 同版本 0.16.3、同参数） | ✅ 全部通过 |
| langgraph 版 pytest | ✅ 166 过 / 0 失败，覆盖率 74.02% ≥ 60% |
| langchain 版 pytest | ✅ **146 过 / 0 失败，覆盖率 53.47% → 71.24%** ≥ 60% |
| YAML 解析（ci.yml / release.yml） | ✅ 通过 |

## 四、使用方式

```bash
# CI：推 master / langgraph / langchain 分支或开 PR 自动触发；
#      也可在仓库 Actions 页面手动 Run workflow

# CD 发布：
git tag v0.1.0
git push origin v0.1.0   # 自动检查 + 打包 + 创建 Release
```

## 五、已知问题与注意

1. **本地 `.env` 干扰 2 个测试（非代码 bug）**：config 使用 `load_dotenv(override=True)`，本地 `.env` 的 `LLM_PROVIDER` 会覆盖测试子进程注入的 `bogus_provider`，导致 `test_invalid_provider_validate_raises` / `test_invalid_provider_api_key_placeholder_empty` 在本地失败。CI 环境无 `.env`，不受影响。本地跑测试时临时移开 `.env` 即可。
2. **版本维护约定不变**：改动先在 langgraph_version 落地再同步到 langchain_version；共享文件（`SHARED_FILES` 清单）必须逐字节一致，由 sync-check 把关。本次新增的 4 个测试文件不在共享清单内（测试可随版本差异），但复制时仍按逐字节一致执行。
3. **覆盖率门槛**：两版均为 60%（`--cov-fail-under=60`），release.yml 仅测 langgraph 版。
