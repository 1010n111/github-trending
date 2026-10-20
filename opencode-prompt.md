读取当前目录下的 trending.json 中的 GitHub Trending 仓库列表，用 Write 工具将公众号风格的技术文章数据写入当前目录下的 article.json。

只输出一个 JSON 对象，不要输出 Markdown、HTML 或任何额外解释。JSON 格式必须如下：

{
  "title": "吸引人的标题，带日期（今天的日期）",
  "intro": "开头引言，1-2 句话",
  "featured": [
    {
      "name": "仓库名（owner/repo）",
      "url": "仓库 URL",
      "description": "一句话中文简介，30 字以内",
      "highlight": "100-150 个汉字的中文介绍，突出亮点和用途"
    }
  ],
  "quick_picks": [
    {
      "name": "仓库名（owner/repo）",
      "url": "仓库 URL",
      "description": "15-40 字的中文一句话介绍"
    }
  ],
  "summary": "结尾总结，一句话"
}

语言要求（最高优先级，违反即视为不合格）：
1. 全篇以简体中文为主，title / intro / description / highlight / summary 都必须是中文句子，不允许出现一整句英文。
2. trending.json 里的 description 是英文原文，只能当作理解素材：禁止照抄，禁止整句保留，必须读懂后改写成地道的中文。
3. 英文只允许出现在这些地方：仓库名（owner/repo）、产品名与专有名词（如 opencode、ComfyUI、Claude Code）、编程语言与文件名、通行技术缩写（如 API、SDK、CLI、LLM、RAG、CI/CD）。这些词直接沿用原写法，不要硬译。
4. 不要「英中拼接」，例如「The open source coding agent，一个开源编码助手」这种半句英文半句中文的写法一律不允许。
5. 中文句子使用中文标点（，。：；！？），不要在中文里混用英文逗号句号。
6. 用口语化的技术中文，避免翻译腔：不要连续使用「它是一个……的工具，它能够……」，也不要出现「该项目」「赋能」「一站式解决方案」这类空话。
7. 改写示例（照这个风格写）：
   原文：「The most powerful and modular diffusion model GUI, api and backend with a graph/nodes interface.」
   ✅「用节点图搭 Diffusion 工作流，采样、后处理、插件都能拖拽组装，本地跑起来也快。」
   ❌「The most powerful and modular diffusion model GUI，一个强大的节点式界面。」

内容要求：
1. 标题要吸引人，必须包含今天的日期（YYYY-MM-DD）。
2. featured 精选 3 个最有意思的仓库，每个 highlight 100-150 个汉字，至少说清「解决什么问题」「怎么用」「适合谁」其中的两点，突出亮点和用途。
3. description 是一句话中文简介，30 字以内，说清它是做什么的；页面上已经把仓库名当小标题展示了，不要再用仓库名开头，也不要和 highlight 重复同一句话。
4. quick_picks 放剩下的仓库，每个用 15-40 字的中文一句话点出它的独特之处，不要写成「某某项目」这种没有信息量的短语。
5. description 和 highlight 都不能为空。若原始 description 缺失或信息量太少，就依据仓库名、语言和已知信息写一句克制的说明，不要编造具体功能、数据或荣誉。
6. 风格轻松有趣，适合公众号阅读；featured 的 highlight 可带 1 个 emoji，不要整篇堆 emoji。
7. summary 用一句话收尾，可以带一句轻量互动（例如问问读者最想试哪个项目）。

事实与来源约束：
1. 只能使用 trending.json 列表中的仓库，不得引入列表之外的任何项目。
2. featured 和 quick_picks 中的 name 必须是仓库原始名称，url 必须是仓库原始 URL，不得改动、不得编造。
3. 只允许输出上述字段，不要新增字段。
4. 可以引用列表里的 stars / today_stars 数据，但不得改写、估算或四舍五入数字。

输出前自检（只在心里检查，不要把检查过程写进输出）：
- description / highlight 里还有没有整句英文？有就改写成中文。
- 有没有仓库名写错、URL 编造、字段缺失或多余字段？
- 输出的 JSON 是否可以被直接解析？
