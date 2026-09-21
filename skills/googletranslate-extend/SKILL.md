---
name: googletranslate-extend
description: 扩展 googletranslate-2api（新端点/多模态/新 SKILL）的规范：先分析后实施、TDD、真实验收、按主题提交。
---

# 扩展规范

1. **先分析**：在 `计划文档/结果计划指南.md` 选阶段；新功能必须回答「价值/上游依赖/风险/验收」。
2. **TDD**：先写失败测试->实现->跑 `pytest -q --cov=app --cov=main`（>=97，当前 100）+ `ruff check` + `mypy`。
3. **真实验收**：任何对外行为必须有真实运行证据（curl 输出/指标计数），禁止「理论上通过」。
4. **多模态预留**：provider 层保持 OpenAI 兼容外壳，新模态（图像等）加到 `/v1/*`，先定上游再实现。
5. **打包新 SKILL**：仿 `skills/googletranslate-*`，满足「安装/使用/调试」三节自洽 + 真实示例。
6. **提交流**：main 分支、按主题 commit、严禁 `-f`；push 前 fetch 核对远端 SHA；变更版本号同步 `config.py` 与 `CHANGELOG.md`。
