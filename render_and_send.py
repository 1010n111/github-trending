import json
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLE_JSON = BASE_DIR / "article.json"


def load_dotenv(path: Path) -> None:
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


def render_article(data: dict) -> tuple[str, str]:
    """根据 LLM 返回的数据和本地模板生成 (HTML, Markdown)"""
    title = data.get("title", "GitHub Trending 每日精选")
    intro = data.get("intro", "")
    featured = data.get("featured", []) or []
    quick_picks = data.get("quick_picks", []) or []
    summary = data.get("summary", "")

    md_lines = [f"# {title}", ""]
    if intro:
        md_lines += [intro, ""]
    md_lines.append("## 🔥 今日精选")
    md_lines.append("")
    for item in featured:
        name = item.get("name", "")
        url = item.get("url", "#")
        desc = item.get("description", "")
        highlight = item.get("highlight", "")
        md_lines.append(f"### [{name}]({url})")
        md_lines.append("")
        if desc:
            md_lines.append(f"> {desc}")
            md_lines.append("")
        if highlight:
            md_lines.append(highlight)
            md_lines.append("")
    if quick_picks:
        md_lines.append("## ⚡ 快速浏览")
        md_lines.append("")
        for item in quick_picks:
            name = item.get("name", "")
            url = item.get("url", "#")
            desc = item.get("description", "")
            md_lines.append(f"- [{name}]({url})：{desc}")
        md_lines.append("")
    if summary:
        md_lines.append("---")
        md_lines.append("")
        md_lines.append(summary)
        md_lines.append("")

    md_content = "\n".join(md_lines).strip()

    def repo_card(item: dict, featured: bool = False) -> str:
        name = escape(item.get("name", ""))
        url = escape(item.get("url", "#"), quote=True)
        desc = escape(item.get("description", ""))
        highlight = escape(item.get("highlight", ""))
        tag = "featured" if featured else "quick"
        card = f"""
        <div class="repo-card {tag}">
            <a class="repo-name" href="{url}" target="_blank">{name}</a>
            <div class="repo-desc">{desc}</div>"""
        if highlight:
            card += f'\n            <div class="repo-highlight">{highlight}</div>'
        card += "\n        </div>"
        return card

    featured_html = "\n".join(repo_card(item, True) for item in featured)
    quick_html = "\n".join(repo_card(item, False) for item in quick_picks)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f6f8fa; color: #24292f; margin: 0; padding: 24px; }}
  .container {{ max-width: 720px; margin: 0 auto; background: #ffffff; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); padding: 32px; }}
  .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 24px; color: #fff; margin-bottom: 24px; }}
  .header h1 {{ margin: 0; font-size: 26px; line-height: 1.4; }}
  .intro {{ color: #57606a; font-size: 15px; line-height: 1.7; margin-bottom: 24px; }}
  h2 {{ color: #24292f; border-left: 4px solid #667eea; padding-left: 12px; margin-top: 32px; }}
  .repo-card {{ background: #f6f8fa; border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1px solid #eaeef2; }}
  .repo-card.featured {{ border-left: 4px solid #667eea; }}
  .repo-card.quick {{ border-left: 4px solid #2da44e; }}
  .repo-name {{ font-size: 18px; font-weight: 600; color: #0969da; text-decoration: none; }}
  .repo-name:hover {{ text-decoration: underline; }}
  .repo-desc {{ color: #57606a; margin-top: 6px; font-size: 14px; }}
  .repo-highlight {{ color: #24292f; margin-top: 10px; font-size: 14px; line-height: 1.7; background: #fff; border-radius: 8px; padding: 10px; }}
  .summary {{ margin-top: 24px; padding: 16px; background: #fff8c5; border-radius: 8px; color: #4d3800; }}
  .footer {{ margin-top: 32px; text-align: center; color: #8c959f; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header"><h1>{escape(title)}</h1></div>
  {f'<div class="intro">{escape(intro)}</div>' if intro else ''}
  <h2>🔥 今日精选</h2>
  {featured_html}
  <h2>⚡ 快速浏览</h2>
  {quick_html}
  {f'<div class="summary">{escape(summary)}</div>' if summary else ''}
  <div class="footer">本邮件由 GitHub Trending 每日精选自动生成</div>
</div>
</body>
</html>"""

    return html_content, md_content


def send_email(html_content: str, md_content: str, subject: str, date: str) -> None:
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_to = [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]

    if not all([smtp_server, smtp_user, smtp_pass, email_to]):
        raise ValueError("SMTP configuration incomplete")

    msg = MIMEText(html_content, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(email_to)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, email_to, msg.as_string())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_dotenv(BASE_DIR / ".env")

    if not ARTICLE_JSON.exists():
        print("article.json not found. Run fetch + opencode generation first.")
        return 1

    article_data = json.loads(ARTICLE_JSON.read_text(encoding="utf-8"))
    html_content, md_content = render_article(article_data)

    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"GitHub Trending 每日精选 {today}"

    for attempt in range(3):
        try:
            send_email(html_content, md_content, subject, today)
            print(f"Newsletter sent successfully! ({today})")
            return 0
        except Exception as e:
            if attempt < 2:
                print(f"Email attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                print(f"Email failed after retries: {e}")
                return 1


if __name__ == "__main__":
    sys.exit(main())
