读取当前目录下的 trending.json 中的 GitHub Trending 仓库列表，用 Write 工具将公众号风格的技术文章数据写入当前目录下的 article.json。

只输出一个 JSON 对象，不要输出 Markdown、HTML 或任何额外解释。JSON 格式必须如下：

{
  "title": "吸引人的标题，带日期（今天的日期）",
  "intro": "开头引言，1-2 句话",
  "featured": [
    {
      "name": "仓库名（owner/repo）",
      "url": "仓库 URL",
      "description": "一句话简介",
      "highlight": "100-150 字详细介绍，突出亮点和用途"
    }
  ],
  "quick_picks": [
    {
      "name": "仓库名（owner/repo）",
      "url": "仓库 URL",
      "description": "一句话介绍"
    }
  ],
  "summary": "结尾总结，一句话"
}

要求：
1. 标题要吸引人，必须包含日期（今天）
2. featured 精选 3 个最有意思的仓库，每个 highlight 100-150 字，突出亮点和用途
3. quick_picks 放剩下的仓库，每个一句话介绍
4. 风格轻松有趣，适合公众号阅读，可在描述中适当使用 emoji
5. 所有字段必须是字符串或对象数组，不要输出额外字段
6. featured 和 quick_picks 中的 name 必须是仓库原始名称，url 必须是仓库 URL