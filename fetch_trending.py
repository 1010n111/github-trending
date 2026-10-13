import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
TRENDING_JSON = BASE_DIR / "trending.json"


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


class TrendingParser(HTMLParser):
    """纯 Python 解析 GitHub Trending，无 C 扩展依赖"""
    def __init__(self):
        super().__init__()
        self.repos = []
        self._in_article = False
        self._article_depth = 0
        self._current_repo = {}
        self._in_h2 = False
        self._in_desc = False
        self._in_lang = False
        self._href = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")

        if tag == "article" and "Box-row" in classes:
            self._in_article = True
            self._article_depth = 0
            self._current_repo = {"name": "", "description": "", "stars": "0", "today_stars": "0", "language": ""}
            self._text_parts = []

        if self._in_article:
            self._article_depth += 1
            if tag == "h2":
                self._in_h2 = True
                self._href = None
            if tag == "a" and self._in_h2 and "href" in attrs_dict:
                self._href = attrs_dict["href"].strip("/")
            if tag == "p" and "col-9" in classes:
                # 描述段之前 _text_parts 已累积了仓库名与 Star/Sponsor 按钮文本，
                # 必须在此清空，否则 description 会带上 "Star owner/repo" 前缀
                self._text_parts = []
                self._in_desc = True
            if tag == "span" and "programmingLanguage" in attrs_dict.get("itemprop", ""):
                self._in_lang = True

    def handle_endtag(self, tag):
        if self._in_article:
            self._article_depth -= 1

            if tag == "h2" and self._in_h2:
                self._in_h2 = False
                if self._href:
                    self._current_repo["name"] = self._href
                    self._current_repo["url"] = f"https://github.com/{self._href}"

            if tag == "p" and self._in_desc:
                self._in_desc = False
                desc = " ".join(self._text_parts).strip()
                self._current_repo["description"] = re.sub(r"\s+", " ", desc)
                self._text_parts = []

            if tag == "span" and self._in_lang:
                self._in_lang = False
                self._current_repo["language"] = "".join(self._text_parts).strip()
                self._text_parts = []

            if tag == "article":
                full_text = "".join(self._text_parts)
                star_match = re.search(r"([\d,]+)\s+stars\s+today", full_text)
                if star_match:
                    self._current_repo["today_stars"] = star_match.group(1)

                link_texts = re.findall(r"[\d,]+", full_text)
                if link_texts:
                    self._current_repo["stars"] = link_texts[0]

                if self._current_repo["name"]:
                    self.repos.append(self._current_repo.copy())
                self._in_article = False
                self._text_parts = []

    def handle_data(self, data):
        if self._in_article:
            self._text_parts.append(data)


def get_proxies() -> dict | None:
    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if not http_proxy and not https_proxy:
        return None
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies or None


def fetch_github_trending() -> list:
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=60, proxies=get_proxies())
            resp.raise_for_status()

            parser = TrendingParser()
            parser.feed(resp.text)
            return parser.repos
        except Exception as e:
            if attempt < 2:
                print(f"Fetch attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                raise


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_dotenv(BASE_DIR / ".env")
    repos = fetch_github_trending()
    TRENDING_JSON.write_text(json.dumps(repos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fetched {len(repos)} repos -> {TRENDING_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
