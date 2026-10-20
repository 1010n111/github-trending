# GitHub Trending 每日精选 · GitHub Actions 版

把本机 cron 方案迁移到 GitHub Actions。抓取 GitHub Trending → 生成文章 → 发送邮件 → 写入 Hexo → 构建部署 → 备份源码，全流程在云端跑完，不再依赖本机开机与代理状态。

## 与本机版本的关系

`fetch_trending.py` / `render_and_send.py` / `publish_to_hexo.py` **原样复制自 `/home/ww/myCode/GitHubTrending`，一行未改**，已逐个 md5 校验一致。

文章生成这一步（Step 2）已从「`opencode run` headless」改为**直连 OpenAI 兼容的 LLM 接口**，新增 `generate_article.py`（本机版仍用 opencode）。理由见「为什么不用 opencode」。

改动都落在编排层与 Step 2：原本由 `run_daily.sh` 承担的 6 步，现在由 `.github/workflows/daily.yml` 承担。

| | 本机版 | Actions 版 |
|---|---|---|
| 定时 | cron `0 8 * * *` | `cron: '24 4 * * *'` + `timezone: Asia/Shanghai`（北京 04:24，避开整点，见「定时可能延迟」） |
| Python 解释器 | `.venv` | `actions/setup-python` |
| 文章生成 | `opencode run` headless | 直连 LLM API（`generate_article.py`，不依赖 Node） |
| 代理 | 必须，`run_daily.sh` 探测 7897 端口 | **不需要**，runner 出站不经国内 |
| Hexo | 本机 `node node_modules/hexo/bin/hexo`（迁移丢了可执行位） | `npm ci` 全新安装，`npx hexo` 直接可用 |
| git 凭据 | `gh auth setup-git` | 仓库 Secrets 里的部署密钥 |
| 源码备份 | Step 6 `git push` | Step 6 同语义 |

## 为什么不用 opencode

最初是照搬本机版的 `opencode run --auto` headless，后来换掉了，两个原因：

1. **agent 有完整工具权限**。`--auto` 的 opencode 能自己 WebFetch、能读机器上任意文件，
   于是必须再补两道护栏确认它没有绕过 `trending.json` 自行抓数据。为了一个
   「读 JSON 写 JSON」的纯任务引入一个不受控的 agent，并不划算。
2. **少一层重依赖**。原名每次跑都要 `npm install -g opencode-ai`（~30s），且 CLI 参数会随版本变动。

换成直连 Chat Completions 后，调用是纯函数式的：没有工具权限、没有 Node 依赖、输出可预期。

> 仓库里的 `opencode-prompt.md` **保留但不再被 Actions 读取**（本机版仍在用）。
> Actions 版用的 prompt 已内联进 `generate_article.py` 的 `SYSTEM_PROMPT`，
> 因为直连 API 不需要"用 Write 工具写文件"这类只对 agent 有意义的指令。

### 一个必须知道的限制：OpenCode 的免费模型不能直连

OpenCode 有一批免费模型（`opencode/*-free`），本机版用的就是 `opencode/mimo-v2.6-flash-free`。
但它们的免费额度**被服务端锁死在 OpenCode 客户端内**，普通 HTTP 调用会被拒：

```
HTTP 403  {"type":"error","error":{"type":"FreeTierError",
 "message":"OpenCode's free tier can only be used from within OpenCode. ..."}}
```

（`GET https://opencode.ai/zen/v1/models` 无需鉴权即可列出模型清单，但 chat 端点过不去；
伪造客户端身份属于绕过其条款，不做。）

所以"免费"的代价是：**必须换一家厂商并申请免费 key**，具体免费档见 `.env.example` 注释。

> ⚠️ 顺带记一个坑：**GitHub Models 已于 2026-07-30 整体下线**，推理 API 不再可用。
> 网上不少 2026 年的「免费 LLM API 盘点」仍在推荐它，是过期的。

### 文案语言：介绍语句必须中文为主

`trending.json` 里的 `description` 是 GitHub 上的英文原文，模型很容易直接照抄，
导致文章出现「The open source coding agent.」这种整句英文的「简介」。

所以 prompt 里把语言要求提到了**最高优先级**，并定死边界：

- `title` / `intro` / `description` / `highlight` / `summary` 一律简体中文；
- 英文原文只作理解素材，禁止照抄、禁止「英文句子 + 中文句子」拼接；
- 只有仓库名、产品名（opencode、ComfyUI、Claude Code）、编程语言、技术缩写
  （API / SDK / CLI / LLM / RAG / CI/CD）保留英文，不硬译；
- `description` 30 字以内、`highlight` 100-150 汉字、`quick_picks` 15-40 字，
  并且不能为空（原文缺描述就写克制的说明，不许编造功能）。

`generate_article.py` 还会在产物偏英文时打 `::warning::`（不阻断发布），
回看 Actions 日志就能知道当天是不是又退化成照抄英文了。

## 流程

```
Step 1  python fetch_trending.py          -> trending.json
Step 2  python generate_article.py        -> article.json
        （内建字段校验 + 数据来源交叉校验；LLM 全挂时降级为模板生成）
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

即 deploy key 除自身绑定的仓库外，**还能认证任意公开仓库**（pages 仓库是公开的，所以 blog 那把也能通过它的认证）。

> ⚠️ **首次运行失败的教训**：这条性质曾直接导致部署失败。SSH 按顺序逐一试探 agent 里的密钥，服务端接受第一个「认证成功」的就不再试后续的。若两把密钥装在同一个 ssh-agent 中，blog 那把会先被接受（对公开 pages 只能读），push 随即被授权层拒绝：`Permission to 1010n111/1010n111.github.io.git denied to deploy key`——有写权限的 pages 密钥根本轮不到被试。
>
> 因此 workflow **不使用 ssh-agent**，改用两个 SSH 主机别名（`github.com-blog` / `github.com-pages`）配合 `IdentitiesOnly yes`，保证每个连接只提供且只允许使用对应的那一把密钥。

### 3. 配置 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret。

| Secret | 说明 | 示例 |
|---|---|---|
| `BLOG_DEPLOY_KEY` | blog 仓库部署私钥（`~/.ssh/github-trending-blog` 的内容） | `-----BEGIN OPENSSH PRIVATE KEY-----` |
| `PAGES_DEPLOY_KEY` | pages 仓库部署私钥（`~/.ssh/github-trending-pages` 的内容） | 同上 |
| `LLM_BASE_URL` | LLM 接口地址（OpenAI 兼容） | `https://api.groq.com/openai/v1` |
| `LLM_API_KEY` | 上面那家的 API key，**免费档即可** | `gsk_...` |
| `LLM_MODEL` | 模型名 | `openai/gpt-oss-120b` |
| `LLM_FALLBACK_BASE_URL`<br>`LLM_FALLBACK_API_KEY`<br>`LLM_FALLBACK_MODEL` | 可选，备用 provider，三个一组；主 provider 失败时自动切换 | `https://openrouter.ai/api/v1` + `openrouter/free` |
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

`LLM_*` 三个是**必填**的：缺了它们 Step 2 会降级为模板文章（仍能跑通，但内容是机械文案）。
`LLM_FALLBACK_*` 可选，但建议配——免费档普遍会限流，多一个备用能显著降低"当天只出模板文"的概率。

### 主备怎么选

免费档之间延迟差距极大。同一份 13 个仓库的 prompt，实测：

| provider | 耗时 |
|---|---|
| Groq `openai/gpt-oss-120b` | 1~5s |
| OpenRouter `openrouter/free` | 47s / 52s / 149s |

所以**把快的放主、慢的放备**。另外 `openrouter/free` 是个"路由器"，每次会随机挑一个
免费上游：偶尔挑到只把内容写进 `reasoning`、`content` 返回 `null` 的模型
（脚本会把空 `content` 当作可重试条件，见 `generate_article.py` 注释），
也偶尔挑到很慢的上游——这正是它更适合当备而不是当主的原因。

### 4. 首次运行

Actions → Daily GitHub Trending → **Run workflow**。

首次建议勾选 `skip_email`，先验证抓取→生成→发文→部署链路，确认无误后再放开邮件。

## 已知注意事项

### 定时可能延迟

- GitHub 的 cron **不保证准点**，高峰期可能延迟十几分钟甚至更久。
- 官方文档点名**每小时的整点**是 Actions 高负载时段，延迟最严重，负载过高时排队任务甚至会被直接丢弃。
- 因此没有把 schedule 设在 08:00（= UTC 00:00），而是设在北京 **04:24**（= UTC 20:24，非整点）。
  实测佐证：早期把触发点放在整点附近时，唯一一次 schedule 触发在 `2026-10-14 02:39 UTC`
  （北京 10:39，迟 2 小时 39 分），第二天那次到北京 09:29 仍未运行——正是卡在 UTC 00:00 整点的结果。
- 本仓库为公开仓库，因此不受「私有仓库 60 天无活动自动禁用定时工作流」的限制，无需刻意维持 commit 活动。
- 若日后改为私有，需注意该限制：连续 60 天无仓库活动后定时工作流会被自动禁用，GitHub 会发邮件提醒，届时手动 Run workflow 即可恢复。

### 时间语义

workflow 里设了 `TZ: Asia/Shanghai`，三个脚本用的 `datetime.now()` 因此与本机行为一致。

schedule 用 `timezone: Asia/Shanghai` + `cron: '24 4 * * *'` 在北京 04:24 触发（= UTC 20:24）。注意此刻 **UTC 日期比北京日期早一天**，所以文章日期一律以 `TZ` 换算出的北京时间为准，不会出现跨日错位。

### Hexo deploy 的跨仓库推送

`_config.yml` 的 `repo` 仍指向 pages 仓库的 **HTTPS 地址**，一行未改。workflow 用 git 的 `url.*.insteadOf` 把该 URL 精确映射成 SSH 别名 `git@github.com-pages:...`（该别名只配置 `PAGES_DEPLOY_KEY`，见「创建部署密钥」一节的教训），从而不必改动博客配置。

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

生成文章前建议先自检，确认「调得通 + 返回能稳定解析」：

```bash
.venv/bin/python generate_article.py --check   # 只打日志，不写 article.json
.venv/bin/python generate_article.py           # 正式生成
```

`--check` 会把 401/403 明确报出来——免费档最常见的原因就是**风控拦截机房 IP**。
本机 IP 与 Actions 的机房 IP 待遇可能不同，所以**上线前最好直接在 Actions 里跑一次**：

```bash
# 手动触发时把 Step 2 临时改成下面这行即可，或者本地配好 key 后先跑通再推
python generate_article.py --check
```

`HEXO_BLOG_DIR` 留空时取 `../Blog`，与本机版默认行为一致。

## 排除项

- **Cloudflare Workers 方案已评估并否决**：6 步中有 3 步无法运行（无文件系统写不了 Hexo 源文件、跑不了 Hexo 构建、无 git 协议只能改走 API），且 QQ SMTP 需要换成 HTTP 邮件服务。详见迁移讨论记录。
