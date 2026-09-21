# 上游 Key 轮换与历史清理指引

> 状态：**指引文档**（供用户手动执行）。`git filter-repo` 重写历史为**不可逆操作**，需你逐条确认后再执行，全程保留备份，严禁 `--force` 覆盖他人提交。

## 一、谷歌侧轮换 GOOGLE_API_KEY（应立即执行）

1. 登录能查看该 key 的账号，进入 Google Cloud Console -> APIs & Services -> Credentials -> API keys
2. 定位用于 `translateHtml` 的 key（`AIza...`），点击 **Restrict key** 复核用途
3. 点 **Rotate key** 或新建一个 key（建议启用 API 限制 + 应用限制）
4. 用新 key 替换本地 `.env` 的 `GOOGLE_API_KEY` / `GOOGLE_API_KEYS`，删除旧 key（或先禁用观察一天）
5. 验证：`python -m pytest tests/test_integration_real.py`（`RUN_REAL_INTEGRATION=1`）或真实 curl 翻译一次

> 轮换完成后，旧 key 即失效，历史 commit 中的旧文本密钥也不再可用——这是最直接有效的降险手段。

## 二、历史泄漏清理（git filter-repo，需你确认后执行）

前置：
- 全仓库备份：`git clone --mirror <remote> backup-mirror.git`（异地再存一份）
- 安装 `git filter-repo`（`pip install git-filter-repo`）

流程（**在你本地自行执行**，勿让任何人代跑 `--force` push）：
```bash
# 1) 仓库根目录
git filter-repo --replace-text <(echo "GOOGLE_API_KEY=<旧key>") --force   # 只替换该字符串
# 2) 重新核对远端（fetch 后用 git log -p 抽查无 AIza 前缀）
git log -p | grep -c "AIza"
# 3) 同步远端（会改写历史，需所有协作者重新 clone；确认无他人未备份提交）
git push --force-with-lease origin main --all   # 明确授权后才执行
```
> 实测前先确认：**没有其他协作者的重大未提交工作**；否则先协调再执行。

## 三、轮换后本仓库需要做什么

- 更新 `.env` / `.env.example`（不提交真实 key）
- 更新 `docs/rotate-key.md` 状态为"已轮换 YYYY-MM-DD"
- 在 `CHANGELOG.md` 记录一次安全维护动作
