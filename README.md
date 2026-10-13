# GitHub Trending 每日精选 · GitHub Actions 版

把本机 cron 方案迁移到 GitHub Actions。抓取 GitHub Trending → 生成文章 → 发送邮件 → 写入 Hexo → 构建部署 → 备份源码，全流程在云端跑完，不再依赖本机开机与代理状态。

## 与本机版本的关系

三个 Python 脚本与 prompt **原样复制自 `/home/ww/myCode/GitHubTrending`，一行未改**，已逐个 md5 校验一致。

改动只发生在编排层：原本由 `run_daily.sh` 承担的 6 步，现在由 `.github/workflows/daily.yml` 承担。

| | 本机版 | Actions 版 |
|---|---|---|
| 定时 | cron `0 8 * * *` | `cron: '0 0 * * *'`（UTC，等于北京 08:00） |
| Python 解释器 | `.venv` | `actions/setup-python` |
| opencode | 本机 nvm 安装 | 每次 `npm install -g opencode-ai` |
| 代理 | 必须，`run_daily.sh` 探测 7897 端口 | **不需要**，runner 出站不经国内 |
| Hexo | 本机 `node node_modules/hexo/bin/hexo`（迁移丢了可执行位） | `npm ci` 全新安装，`npx hexo` 直接可用 |
| git 凭据 | `gh auth setup-git` | 仓库 Secrets 里的部署密钥 |
| 源码备份 | Step 6 `git push` | Step 6 同语义 |

## 流程

```
Step 1  python fetch_trending.py          -> trending.json
Step 2  opencode run ...                  -> article.json
        （附带校验，避免 opencode 成功退出但没写出文件）
Step 3  python render_and_send.py         -> 发送 HTML 邮件（可选跳过）
Step 4  python publish_to_hexo.py         -> blog/source/_posts/<日期> Github热门仓库.md
Step 5  npm ci && npx hexo generate/deploy -> 推送 public/ 到 pages 仓库
Step 6  git add/commit/push source/_posts -> 备份文章源码
```

## 搭建步骤

### 1. 建仓库并推送

本目录即为一个完整仓库。**设为公开**：代码里没有任何密钥（密钥全部走仓库 Secrets），公开可换来两个好处——免费 Actions 额度无限，且不会因长期无 commit 活动而被自动禁用定时工作流。

在 GitHub 新建公开仓库后推送即可；实际操作时也可直接用 `gh repo create --public` 一步完成。

### 2. 创建部署密钥

流水线仓库的内置 `GITHUB_TOKEN` 无法访问另外两个仓库，因此各用一把 **deploy key**（写权限）：

```bash
ssh-keygen -t ed25519 -N '' -C gha-deploy-blog  -f ~/.ssh/github-trending-blog
ssh-keygen -t ed25519 -N '' -C gha-deploy-pages -f ~/.ssh/github-trending-pages

gh api repos/1010n111/blog/keys \
  -f title=github-actions-deploy-blog \
  -f key="$(cat ~/.ssh/github-trending-blog.pub)" -F read_only=false

gh api repos/1010n111/1010n111.github.io/keys \
  -f title=github-actions-deploy-pages \
  -f key="$(cat ~/.ssh/github-trending-pages.pub)" -F read_only=false
```

选 deploy key 而非 PAT 的原因：它由 API 直接创建，不必手动去网页生成；且写权限绑定在各自仓库上，不涉及其他仓库。

**实测过的隔离边界**（写文档前逐条验证过，不是照抄官方说法）：

| 场景 | 结果 |
|---|---|
| pages 密钥访问私有 blog 仓库 | `Repository not found`——已认证，被授权层拒绝 |
| 随机无关密钥访问 blog | `Permission denied (publickey)`——认证即失败 |
| blog 密钥读取公开 pages 仓库 | 成功 |

即 deploy key 除自身绑定的仓库外，**还能读取任意公开仓库**。pages 仓库是公开的，所以 blog 那把密钥也能读它；但真正需要的写操作仍分别由各自绑定的密钥完成，不受影响。

### 3. 配置 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret。

| Secret | 说明 | 示例 |
|---|---|---|
| `BLOG_DEPLOY_KEY` | blog 仓库部署私钥（`~/.ssh/github-trending-blog` 的内容） | `-----BEGIN OPENSSH PRIVATE KEY-----` |
| `PAGES_DEPLOY_KEY` | pages 仓库部署私钥（`~/.ssh/github-trending-pages` 的内容） | 同上 |
| `SMTP_SERVER` | SMTP 服务器 | `smtp.qq.com` |
| `SMTP_PORT` | SMTP 端口 | `587` |
| `SMTP_USER` | 发信账号 | `xxx@qq.com` |
| `SMTP_PASS` | **授权码**，不是登录密码 | `xxxxxxxx` |
| `EMAIL_TO` | 收件人，逗号分隔 | `xxx@qq.com` |

私钥可用命令写入，避免粘贴出错：

```bash
cat ~/.ssh/github-trending-blog  | gh secret set BLOG_DEPLOY_KEY  --repo 1010n111/github-trending
cat ~/.ssh/github-trending-pages | gh secret set PAGES_DEPLOY_KEY --repo 1010n111/github-trending
```

`OPENCODE_MODEL` 已写死在 workflow 的 `env` 里，无需配置。

### 4. 首次运行

Actions → Daily GitHub Trending → **Run workflow**。

首次建议勾选 `skip_email`，先验证抓取→生成→发文→部署链路，确认无误后再放开邮件。

## 已知注意事项

### 定时可能延迟

- GitHub 的 cron **不保证准点**，高峰期可能延迟十几分钟甚至更久。
- 本仓库为公开仓库，因此不受「私有仓库 60 天无活动自动禁用定时工作流」的限制，无需刻意维持 commit 活动。
- 若日后改为私有，需注意该限制：连续 60 天无仓库活动后定时工作流会被自动禁用，GitHub 会发邮件提醒，届时手动 Run workflow 即可恢复。

### 时间语义

workflow 里设了 `TZ: Asia/Shanghai`，三个脚本用的 `datetime.now()` 因此与本机行为一致。UTC 00:00 触发时，UTC 日期与北京日期相同，不会出现跨日错位。

### Hexo deploy 的跨仓库推送

`_config.yml` 的 `repo` 仍指向 pages 仓库的 **HTTPS 地址**，一行未改。workflow 用 git 的 `url.*.insteadOf` 把该 URL 精确映射成 SSH 地址，改由 `PAGES_DEPLOY_KEY` 认证，从而不必改动博客配置。

### Step 5 与 Step 6 的区别

- **Step 5** 推的是渲染后的 HTML（`public/`）到 `1010n111.github.io`，决定线上站点内容。
- **Step 6** 推的是文章源码 `.md` 到 `1010n111/blog`，是可编辑原文的备份。

只做 Step 5 会导致源码只存在于 runner 的临时工作区，跑完即丢。两步缺一不可。

## 本地调试

脚本可脱离 Actions 直接跑：

```bash
cd /home/ww/myCode/GitHubTrending-Actions
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填入实际值
.venv/bin/python fetch_trending.py
```

`HEXO_BLOG_DIR` 留空时取 `../Blog`，与本机版默认行为一致。

## 排除项

- **Cloudflare Workers 方案已评估并否决**：6 步中有 3 步无法运行（无文件系统写不了 Hexo 源文件、跑不了 Hexo 构建、无 git 协议只能改走 API），且 QQ SMTP 需要换成 HTTP 邮件服务。详见迁移讨论记录。
