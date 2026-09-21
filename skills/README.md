# Skills（使用者技能包）

> 标准：参照 anthropics/skills SKILL.md 规范 + addyosmani 质量门禁（DEFINE->PLAN->BUILD->VERIFY->REVIEW->SHIP）。
> 用途：小白「边用边学」、沉淀使用者自己的技能、为扩展（图像/PPT/电商）预留打包规范。

| Skill | 作用 | 适用 |
|---|---|---|
| `googletranslate-install` | 一条命令装起来（Windows/venv/Docker） | 首次部署 |
| `googletranslate-use` | OpenAI 兼容客户端接入（curl / SDK / 批量） | 日常调用 |
| `googletranslate-debug` | 排障（502/429/熔断/多 Key/链路摘要） | 出问题时 |
| `googletranslate-extend` | 扩展规范（新端点/多模态/新 SKILL 打包与质量门禁） | 想加功能 |

> 约定：任何新 SKILL 必须满足「安装/使用/调试」自洽 + 有真实输出示例（禁止虚构）；改动走代码同样的门禁。
