import json
import os
import re
import sys
import zlib
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLE_JSON = BASE_DIR / "article.json"
TRENDING_JSON = BASE_DIR / "trending.json"

BLOG_DIR_ENV = "HEXO_BLOG_DIR"
# 默认与本仓库同级的 Blog 目录；实际取值见 get_posts_dir()（须在 load_dotenv 之后）
DEFAULT_BLOG_DIR = BASE_DIR.parent / "Blog"

def get_blog_dir() -> Path:
    """读取博客目录。必须在 load_dotenv 之后调用，否则 .env 的值不生效。"""
    return Path(os.getenv(BLOG_DIR_ENV) or DEFAULT_BLOG_DIR)


def get_posts_dir() -> Path:
    return get_blog_dir() / "source" / "_posts"


CATEGORIES = ["开源项目", "代码仓库推荐"]

NOISE_LANGS = {"", "star", "built by"}


def sanitize_language(lang: str) -> str | None:
    """清理 trending.json 中可能混入的 HTML 垃圾，只保留干净的编程语言名"""
    if not lang:
        return None
    clean = re.sub(r"<[^>]+>", " ", lang).replace("\n", " ").strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return None
    if clean.lower() in NOISE_LANGS or len(clean) > 40 or "/" in clean:
        return None
    return clean


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def abbrlink_of(title: str) -> str:
    return hex(zlib.crc32(title.encode("utf-8")) & 0xFFFFFFFF)[2:]


def collect_languages(article: dict) -> list:
    """从 trending.json 收集 featured + quick_picks 仓库的开发语言，保持出现顺序去重"""
    if not TRENDING_JSON.exists():
        return []
    repos = json.loads(TRENDING_JSON.read_text(encoding="utf-8"))
    name_to_lang = {}
    for r in repos:
        lang = sanitize_language(r.get("language") or "")
        if lang:
            name_to_lang[r.get("name", "").lower()] = lang

    langs = []
    for item in (article.get("featured", []) or []) + (article.get("quick_picks", []) or []):
        lang = name_to_lang.get(item.get("name", "").lower())
        if lang and lang not in langs:
            langs.append(lang)
    return langs


def build_frontmatter(date_str: str, title: str, langs: list) -> str:
    categories_yaml = "\n".join(f"  - {c}" for c in CATEGORIES)
    tags = ["开源开发"] + langs + ["Github热门仓库"]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    filename = f"{date_str}.github-popular-repositories"
    abbrlink = abbrlink_of(title)
    return f"""---
title: {title}
date: '{date_str}'
categories:
{categories_yaml}
tags:
{tags_yaml}
author: ww
filename: {filename}
abbrlink: {abbrlink}
---
"""


def render_body(article: dict, heading: str = "") -> str:
    """渲染文章正文。

    heading 会作为一级标题输出。fluid 主题的 #seo-header 在非打印时是
    display:none，banner 标题又依赖 typed.js 打字动画，若正文没有真实标题，
    页面上就看不到标题了，因此这里必须输出 # 标题。
    """
    title = article.get("title", "")
    intro = article.get("intro", "")
    featured = article.get("featured", []) or []
    quick_picks = article.get("quick_picks", []) or []
    summary = article.get("summary", "")

    lines = []
    if heading:
        lines.append(f"# {heading}")
        lines.append("")
    if title:
        lines.append(f"> {title}")
        lines.append("")
    if intro:
        lines.append(intro)
        lines.append("")

    n = 0
    if featured:
        lines.append("## 🔥 今日精选")
        lines.append("")
        for item in featured:
            n += 1
            name = item.get("name", "")
            url = item.get("url", "#")
            desc = item.get("description", "")
            highlight = item.get("highlight", "")
            lines.append(f"### {n}. {name}")
            lines.append("")
            lines.append(f"- **仓库 URL**：[{url}]({url})")
            if desc:
                lines.append(f"- **简介**：{desc}")
            if highlight:
                lines.append(f"- **亮点**：{highlight}")
            lines.append("")

    if quick_picks:
        lines.append("## ⚡ 快速浏览")
        lines.append("")
        for item in quick_picks:
            n += 1
            name = item.get("name", "")
            url = item.get("url", "#")
            desc = item.get("description", "")
            lines.append(f"### {n}. {name}")
            lines.append("")
            lines.append(f"- **仓库 URL**：[{url}]({url})")
            if desc:
                lines.append(f"- **简介**：{desc}")
            lines.append("")

    if summary:
        lines.append("---")
        lines.append("")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines).strip()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_dotenv(BASE_DIR / ".env")

    if not ARTICLE_JSON.exists():
        print(f"{ARTICLE_JSON} not found. Run fetch + opencode generation first.")
        return 1

    article = json.loads(ARTICLE_JSON.read_text(encoding="utf-8"))

    date_str = datetime.now().strftime("%Y-%m-%d")
    title = f"{date_str} Github热门仓库"
    extra_title = article.get("title", "")

    langs = collect_languages(article)
    frontmatter = build_frontmatter(date_str, title, langs)
    body = render_body(article, heading=title)

    post_path = get_posts_dir() / f"{date_str} Github热门仓库.md"
    post_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.write_text(frontmatter + "\n" + body + "\n", encoding="utf-8")

    print(f"Hexo post written: {post_path}")
    print(f"  frontmatter title: {title}")
    print(f"  article title: {extra_title}")
    print(f"  tags: {['开源开发'] + langs + ['Github热门仓库']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())