"""调用 OpenAI 兼容的 Chat Completions 接口生成 article.json。

设计目标：取代 `opencode run` 那一步（Step 2），但不改变上下游的契约——
输入仍是 trending.json，输出仍是 article.json，字段与 opencode-prompt.md 一致，
因此 render_and_send.py / publish_to_hexo.py 一行都不用改。

与 opencode 方案的区别：
  1. 纯函数式调用，没有工具权限，不存在"绕过 trending.json 自行抓取"的可能；
  2. 不需要 npm / Node 运行时（Node 仍要留给 Hexo）；
  3. 厂商无关：只认 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 三个变量，
     换厂商 = 换配置，代码零改动。

三层容错（免费档会抽风，所以不做单点）：
  第 1 层  LLM_*              —— 主 provider
  第 2 层  LLM_FALLBACK_*     —— 备用 provider
  第 3 层  模板生成（不调 LLM）—— 永不失败的兜底，保证当天一定有文章产出
第 3 层可用 --no-fallback（或 TEMPLATE_FALLBACK=off）关掉，改为失败即退出。

用法：
    python generate_article.py                # 正式生成 article.json
    python generate_article.py --check        # 连通性自检，只打日志不写文件
    python generate_article.py --no-fallback  # 不允许降级到模板，失败即退出
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
TRENDING_JSON = BASE_DIR / "trending.json"
ARTICLE_JSON = BASE_DIR / "article.json"

# 连接超时与读取超时必须分开：
#   - 连接超时要短。端点被网络黑洞吞掉（丢包而非拒绝连接）时，
#     每次尝试都会耗满超时，若用 180s 会把整条流水线拖垮。
#   - 读取超时要长。免费档高峰期模型排队可能很久。
#
# 20s 而非 10s：走代理访问境外 API 时，代理自身的上游建连与 TLS 握手
# 都算在连接阶段内，实测冷启动会超过 10s（热态仅 0.3s）。
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 120

# 单个 provider 的总时间上限（含所有重试与变体）。
# 防止某个端点卡死时无限重试，把 Actions 的 45 分钟预算吃光。
PROVIDER_DEADLINE = 240
# 单个 payload 变体的重试次数（针对 429/5xx 等可重试状态）
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# 模板兜底的开关。默认开启：宁可用机械文案也不断更。
# 显式设为 off/false/0/no 时关闭，此时 LLM 全挂即整体失败（退出码 1）。
TEMPLATE_FALLBACK_OFF = {"off", "false", "0", "no"}

# 免费档的便捷默认值：只有在检测到对应的 API key 变量时才启用，
# 且随时可被 LLM_BASE_URL / LLM_MODEL 覆盖。
#
# ⚠️ 模型 id 是易腐的：这里的默认值会被厂商下线（实测 Groq 的
#    llama-3.3-70b-versatile 已经不可用，模型列表里已无此 id）。
#    默认值只是"少配一个变量"的便利，正式使用时请显式设置 LLM_MODEL。
#    各家当前可用模型可用 `curl` 打 /models 端点确认。
KNOWN_PROVIDERS = {
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1", "openrouter/free"),
    "GROQ_API_KEY": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "CEREBRAS_API_KEY": ("https://api.cerebras.ai/v1", "llama-3.3-70b"),
}

SYSTEM_PROMPT = """你是一个技术公众号的编辑。用户会给你一份 GitHub Trending 仓库列表（JSON），
请你从中挑选并撰写一篇简体中文技术文章，只输出一个 JSON 对象。

输出格式（严格遵守，不要输出 Markdown、HTML 或任何额外解释）：

{
  "title": "吸引人的标题，带今天的日期",
  "intro": "开头引言，1-2 句话",
  "featured": [
    {
      "name": "仓库名(owner/repo)",
      "url": "仓库 URL",
      "description": "一句话中文简介，30 字以内",
      "highlight": "100-150 个汉字的中文介绍，突出亮点和用途"
    }
  ],
  "quick_picks": [
    {
      "name": "仓库名(owner/repo)",
      "url": "仓库 URL",
      "description": "15-40 字的中文一句话介绍"
    }
  ],
  "summary": "结尾总结，一句话"
}

语言要求（最高优先级，违反即视为不合格）：
1. 全篇以简体中文为主，title / intro / description / highlight / summary 都必须是
   中文句子，不允许出现一整句英文。
2. 列表里的 description 是英文原文，只能当作理解素材：禁止照抄，禁止整句保留，
   必须读懂后改写成地道的中文。
3. 英文只允许出现在这些地方：仓库名（owner/repo）、产品名与专有名词（如 opencode、
   ComfyUI、Claude Code）、编程语言与文件名、通行技术缩写（如 API、SDK、CLI、LLM、
   RAG、CI/CD）。这些词直接沿用原写法，不要硬译。
4. 不要「英中拼接」，例如「The open source coding agent，一个开源编码助手」这种
   半句英文半句中文的写法一律不允许。
5. 中文句子使用中文标点（，。：；！？），不要在中文里混用英文逗号句号。
6. 用口语化的技术中文，避免翻译腔：不要连续使用「它是一个……的工具，它能够……」，
   也不要出现「该项目」「赋能」「一站式解决方案」这类空话。
7. 改写示例（照这个风格写）：
   原文：「The most powerful and modular diffusion model GUI, api and backend with a
   graph/nodes interface.」
   ✅「用节点图搭 Diffusion 工作流，采样、后处理、插件都能拖拽组装，本地跑起来也快。」
   ❌「The most powerful and modular diffusion model GUI，一个强大的节点式界面。」

内容要求：
1. title 要吸引人，必须包含今天的日期（YYYY-MM-DD）。
2. featured 精选 3 个最有意思的仓库；每个 highlight 100-150 个汉字，至少说清
   「解决什么问题」「怎么用」「适合谁」其中的两点，让读者知道值不值得点进去。
3. description 是一句话中文简介，30 字以内，说清它是做什么的；页面上已经把仓库名
   当小标题展示了，不要再用仓库名开头，也不要和 highlight 重复同一句话。
4. quick_picks 放剩下的仓库，每个用 15-40 字的中文一句话点出它的独特之处，
   不要写成「某某项目」这种没有信息量的短语。
5. description 和 highlight 都不能为空。若原始 description 缺失或信息量太少，
   就依据仓库名、语言和已知信息写一句克制的说明，不要编造具体功能、数据或荣誉。
6. 风格轻松有趣，适合公众号阅读；featured 的 highlight 可带 1 个 emoji，
   不要整篇堆 emoji。
7. summary 用一句话收尾，可以带一句轻量互动（例如问问读者最想试哪个项目）。

事实与来源约束：
1. 只能使用用户提供的列表中的仓库，不得引入列表之外的任何项目。
2. name 必须是列表中的原始仓库名，url 必须是原始 URL，不得改动、不得编造。
3. 只允许输出上述字段，不要新增字段。
4. 可以引用列表里的 stars / today_stars 数据，但不得改写、估算或四舍五入数字。

输出前自检（只在心里检查，不要把检查过程写进输出）：
- description / highlight 里还有没有整句英文？有就改写成中文。
- 有没有仓库名写错、URL 编造、字段缺失或多余字段？
- 输出的 JSON 是否可以被直接解析？"""


def load_dotenv(path: Path) -> None:
    """轻量加载 .env，避免依赖 python-dotenv"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"").strip()
        os.environ.setdefault(key, value)


def collect_providers() -> list[dict]:
    """按主/备顺序收集可用的 provider。

    优先级：
      1. LLM_*        —— 通用主配置
      2. LLM_FALLBACK_* —— 通用备用配置（failover，免费档顶不住时用）
      3. KNOWN_PROVIDERS —— 检测到厂商原生 key 变量时的便捷默认值
    缺少 api_key 或 base_url 的条目直接跳过。
    """
    candidates = [
        ("primary", os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")),
        (
            "fallback",
            os.getenv("LLM_FALLBACK_BASE_URL"),
            os.getenv("LLM_FALLBACK_API_KEY"),
            os.getenv("LLM_FALLBACK_MODEL"),
        ),
    ]
    for key_env, (base_url, model) in KNOWN_PROVIDERS.items():
        candidates.append((key_env, base_url, os.getenv(key_env), model))

    providers = []
    for name, base_url, api_key, model in candidates:
        if not api_key or not base_url or not model:
            continue
        # 同一个 base_url 只保留一次，避免主配置和便捷项重复请求
        if any(p["base_url"] == base_url for p in providers):
            continue
        providers.append({"name": name, "base_url": base_url, "api_key": api_key, "model": model})
    return providers


def build_messages(trending: list) -> list:
    """把 trending.json 压成精简列表塞进 user 消息（去掉无关字段，省 token）"""
    compact = [
        {
            "name": r.get("name", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "stars": r.get("stars", ""),
            "today_stars": r.get("today_stars", ""),
        }
        for r in trending
    ]
    today = datetime.now().strftime("%Y-%m-%d")
    user = (
        f"今天的日期是 {today}。\n\n"
        f"今日 GitHub Trending 仓库列表（共 {len(compact)} 个）：\n\n"
        f"{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
        "注意：上面每个仓库的 description 都是英文原文，只是给你理解用的素材。\n"
        "写入文章时必须译写成简体中文，不要照抄、不要保留整句英文；\n"
        "仓库名、产品名、编程语言和技术缩写按原样保留即可。\n\n"
        "请严格按系统提示的 JSON 格式输出。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def extract_json(text) -> dict:
    """从模型回复中提取 JSON 对象。

    兼容三种情况：纯 JSON、```json 代码围栏、JSON 前后夹带解释文字。
    response_format=json_object 能挡掉大部分脏输出，但不能假设所有免费档都支持，
    所以这里必须兜住。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("模型回复为空（content 为 null 或空字符串），无法解析 JSON")

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型回复中找不到 JSON 对象")
    return json.loads(stripped[start : end + 1])


def validate(article: dict, trending: list) -> None:
    """校验产物。任何一项不过就直接失败，不往下游传脏数据。"""
    if not isinstance(article, dict):
        raise ValueError("article 不是 JSON 对象")
    if not article.get("title"):
        raise ValueError("缺少 title")

    featured = article.get("featured")
    if not isinstance(featured, list) or not featured:
        raise ValueError("featured 为空或不是数组")
    for i, item in enumerate(featured):
        if not item.get("name") or not item.get("url"):
            raise ValueError(f"featured[{i}] 缺少 name 或 url")

    quick = article.get("quick_picks") or []
    if not isinstance(quick, list):
        raise ValueError("quick_picks 不是数组")

    # 交叉校验数据来源：引用的仓库必须都在 trending.json 里。
    # 纯 API 调用理论上不可能编造数据源，但模型可能"记错"仓库名，仍需挡住。
    known = {r.get("name", "") for r in trending}
    used = [i.get("name", "") for i in featured + quick]
    unknown = [n for n in used if n not in known]
    if unknown:
        raise ValueError(f"以下仓库不在 trending.json 中，疑似模型编造：{unknown}")


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


def looks_english(text: str) -> bool:
    """判断一段文案是否「以英文为主」。

    trending.json 里的 description 是英文原文，模型最容易犯的错就是原样搬进文章，
    表现为「The open source coding agent.」这种整句英文。这里只用来提示，不阻断流程：
    语言风格问题不值得让当天的文章开天窗。
    """
    text = (text or "").strip()
    if len(text) < 4:
        return False
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    return cjk == 0 or latin > cjk * 2


def warn_english_fields(article: dict) -> None:
    """把偏英文的字段打成 Actions 警告，方便事后回看当天是不是又照抄了英文原文"""
    fields = [
        ("title", article.get("title")),
        ("intro", article.get("intro")),
        ("summary", article.get("summary")),
    ]
    for key in ("featured", "quick_picks"):
        for i, item in enumerate(article.get(key) or []):
            fields.append((f"{key}[{i}].description", item.get("description")))
            fields.append((f"{key}[{i}].highlight", item.get("highlight")))

    bad = [(name, (text or "").strip()) for name, text in fields if looks_english(text)]
    if not bad:
        return
    print(f"::warning::以下 {len(bad)} 处文案疑似以英文为主，未达到「介绍语句中文为主」的要求：")
    for name, text in bad:
        print(f"::warning::  {name}: {text[:60]}")


def post_once(provider: dict, payload: dict) -> requests.Response:
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    return requests.post(
        url,
        headers={
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )


def describe_http_error(status: int, body: str) -> str:
    """把状态码翻译成人话，免费档最常踩的就那几种"""
    snippet = body.strip()[:300]
    if status in (401, 403):
        return (
            f"HTTP {status}：鉴权失败或被风控拦截。\n"
            f"  免费档常见原因：key 无效/过期，或平台拦截机房 IP（GitHub Actions 就是机房 IP）。\n"
            f"  原始响应：{snippet}"
        )
    if status == 404:
        return f"HTTP 404：端点或模型名不存在，检查 base_url 与 model。原始响应：{snippet}"
    if status == 429:
        return f"HTTP 429：触发限流。原始响应：{snippet}"
    return f"HTTP {status}：{snippet}"


def call_provider(provider: dict, messages: list) -> dict:
    """调用单个 provider，返回解析后的 dict。

    payload 采用「逐级降级」策略：部分免费档对 response_format / max_tokens
    的兼容性不一致，遇到 400 就退一步重试，而不是直接失败。

    整个 provider 受 PROVIDER_DEADLINE 约束：任何一次 sleep 都会被裁剪到剩余额度内，
    额度耗尽即放弃、不再发起新请求，避免个别端点卡死拖垮整条流水线。
    """
    variants = [
        {"response_format": {"type": "json_object"}, "max_tokens": 4096},
        {"max_tokens": 4096},
        {},
    ]

    deadline = time.monotonic() + PROVIDER_DEADLINE

    def remaining() -> float:
        return deadline - time.monotonic()

    def nap(seconds: float) -> bool:
        """睡一小会儿；若剩余额度已不足，返回 False 表示该放弃了"""
        budget = min(seconds, remaining())
        if budget <= 0:
            return False
        time.sleep(budget)
        return True

    last_error = None
    for vi, variant in enumerate(variants):
        if remaining() <= 0:
            break
        payload = {"model": provider["model"], "messages": messages, **variant}
        label = f"变体{vi + 1}/{len(variants)}"
        transport_failed = False
        for attempt in range(MAX_ATTEMPTS):
            if remaining() <= 0:
                last_error = last_error or f"超过单 provider 时限 {PROVIDER_DEADLINE}s"
                break
            try:
                resp = post_once(provider, payload)
            except requests.RequestException as e:
                transport_failed = True
                last_error = f"网络异常：{e}"
                if attempt < MAX_ATTEMPTS - 1 and nap(2 ** attempt * 3):
                    continue
                break

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError) as e:
                    raise ValueError(f"响应结构不符合 OpenAI 规范：{e}\n原始响应：{resp.text[:300]}")

                if not content:
                    # 实测踩到过：OpenRouter 的 openrouter/free 路由器会挑中
                    # 只把内容写进 reasoning 字段、content 留 null 的上游模型。
                    # 这种情况重试比直接失败划算——路由器每次会重新挑上游。
                    last_error = f"响应 content 为空（原始响应：{resp.text[:200]}）"
                    print(f"  {label} 第 {attempt + 1} 次返回空 content，重试")
                    if attempt < MAX_ATTEMPTS - 1 and nap(3):
                        continue
                    raise RuntimeError(last_error)

                return extract_json(content)

            if resp.status_code == 400 and vi < len(variants) - 1:
                # 400 基本是 payload 不被支持，换下一个变体而非重试同一个
                print(f"  {label} 被拒（400），降级重试：{resp.text[:160]}")
                last_error = describe_http_error(resp.status_code, resp.text)
                break

            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS - 1:
                wait = 5 * (2 ** attempt)
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                print(f"  {label} 第 {attempt + 1} 次失败（HTTP {resp.status_code}），{wait}s 后重试")
                if nap(wait):
                    continue
                break

            raise RuntimeError(describe_http_error(resp.status_code, resp.text))

        if transport_failed:
            # 连不上/超时与 payload 无关，换变体也一样连不上，别白等
            break

    raise RuntimeError(last_error or f"单 provider 在 {PROVIDER_DEADLINE}s 时限内未完成")


def generate(messages: list) -> dict:
    """主/备 provider 依次尝试，任一成功即返回"""
    providers = collect_providers()
    if not providers:
        raise RuntimeError(
            "没有可用的 LLM 配置。请至少设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，\n"
            "或设置 OPENROUTER_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY 之一。"
        )

    errors = []
    for provider in providers:
        print(f"[provider] {provider['name']}: {provider['base_url']} -> {provider['model']}")
        started = time.time()
        try:
            article = call_provider(provider, messages)
            print(f"[provider] {provider['name']} 成功，耗时 {time.time() - started:.1f}s")
            return article
        except Exception as e:
            print(f"[provider] {provider['name']} 失败：{e}")
            errors.append(f"{provider['name']}: {e}")

    raise RuntimeError("所有 provider 均失败：\n" + "\n".join(f"  - {e}" for e in errors))


def fallback_enabled() -> bool:
    if "--no-fallback" in sys.argv[1:]:
        return False
    value = (os.getenv("TEMPLATE_FALLBACK") or "").strip().lower()
    return value not in TEMPLATE_FALLBACK_OFF


def parse_count(value) -> int:
    """把 trending.json 里的 star 字符串（"1,234" / "" / None）转成 int"""
    if value is None:
        return 0
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else 0


def template_highlight(item: dict) -> str:
    """模板版 highlight：只陈述 trending.json 里的客观事实。

    刻意不去追求 prompt 里"100-150 字"的要求——模板拼不出那种文案，
    硬凑只会灌水。这里的目标是"信息不缺、不撒谎、读得下去"。
    """
    desc = (item.get("description") or "").strip().rstrip("。.")
    lang = (item.get("language") or "").strip()
    today = parse_count(item.get("today_stars"))
    total = parse_count(item.get("stars"))

    parts = []
    if desc:
        parts.append(desc)
    parts.append(f"今日新增 {today} stars，累计 {total} stars")
    if lang:
        parts.append(f"主要使用 {lang} 开发")

    tail = f"适合关注 {lang} 生态的开发者了解。" if lang else "值得点进去看看。"
    return "，".join(parts) + "。" + tail


def generate_by_template(trending: list) -> dict:
    """第 3 层兜底：完全不用 LLM，纯规则拼一篇文章。

    价值在于"永不失败"——LLM 全挂时也保证当天有文章，避免开天窗。
    排序依据是今日新增 star，其次是累计 star。
    """
    ranked = sorted(
        trending,
        key=lambda r: (parse_count(r.get("today_stars")), parse_count(r.get("stars"))),
        reverse=True,
    )
    # 至少留一个给 quick_picks，避免 featured 把列表吃光
    feature_count = min(3, max(1, len(ranked) - 1))
    top, rest = ranked[:feature_count], ranked[feature_count:]

    today = datetime.now().strftime("%Y-%m-%d")

    def pick(item: dict) -> dict:
        return {
            "name": item.get("name", ""),
            "url": item.get("url", ""),
            "description": (item.get("description") or "").strip() or "暂无简介",
        }

    featured = []
    for item in top:
        entry = pick(item)
        entry["highlight"] = template_highlight(item)
        featured.append(entry)

    return {
        "title": f"{today} GitHub Trending 精选",
        "intro": f"这是 {today} 的 GitHub Trending 榜单精选，共整理出 {len(ranked)} 个值得关注的开源项目。",
        "featured": featured,
        "quick_picks": [pick(i) for i in rest],
        "summary": "以上按今日新增 star 排序，完整榜单见 github.com/trending。",
    }


def run_check() -> int:
    """连通性自检：只验证「能不能调通 + 能不能稳定 parse」，不写 article.json。

    免费档上线前要确认的两件事正是这两个：
      1. 平台是否拦截 GitHub Actions 的机房 IP（表现为 401/403）；
      2. 返回的 JSON 是否能被 extract_json 稳定解析。
    """
    providers = collect_providers()
    if not providers:
        print("未检测到任何 API key，无法自检。")
        print("请设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL（或 OPENROUTER_API_KEY 等）。")
        return 2

    messages = [
        {"role": "system", "content": "只输出 JSON，格式为 {\"ok\": true, \"msg\": \"...\"}"},
        {"role": "user", "content": "请回一句中文问候，放在 msg 字段里。"},
    ]

    failed = 0
    for provider in providers:
        print(f"[check] {provider['name']}: {provider['base_url']} -> {provider['model']}")
        started = time.time()
        try:
            result = call_provider(provider, messages)
            print(f"[check] 成功 {time.time() - started:.1f}s，解析结果：{json.dumps(result, ensure_ascii=False)}")
        except Exception as e:
            print(f"[check] 失败：{e}")
            failed += 1
    return 1 if failed == len(providers) else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_dotenv(BASE_DIR / ".env")

    if "--check" in sys.argv[1:]:
        return run_check()

    if not TRENDING_JSON.exists():
        print(f"{TRENDING_JSON.name} not found. Run fetch_trending.py first.")
        return 1

    trending = json.loads(TRENDING_JSON.read_text(encoding="utf-8"))
    if len(trending) < 3:
        print(f"trending.json 仅 {len(trending)} 个仓库，疑似抓取不完整，中止。")
        return 1

    messages = build_messages(trending)
    print(f"输入 {len(trending)} 个仓库，prompt 约 {len(messages[1]['content'])} 字符")

    used_template = False
    try:
        article = generate(messages)
    except Exception as e:
        if not fallback_enabled():
            print(f"::error::生成失败（模板兜底已禁用）：{e}")
            return 1
        # 降级不静默：Actions 里会显示成黄色警告，方便事后回看当天是不是掉了链子
        print(f"::warning::所有 LLM provider 均失败，降级为模板生成：{e}")
        article = generate_by_template(trending)
        used_template = True

    try:
        validate(article, trending)
    except Exception as e:
        print(f"::error::产物校验失败：{e}")
        return 1

    warn_english_fields(article)

    ARTICLE_JSON.write_text(json.dumps(article, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    used = len(article.get("featured") or []) + len(article.get("quick_picks") or [])
    source = "模板" if used_template else "LLM"
    print(f"article.json 已写入（{source}生成）：{article['title']}（引用 {used} 个仓库）")
    if used_template:
        print("::warning::本次为机械文案，未经过 LLM 润色，建议人工复核后发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
