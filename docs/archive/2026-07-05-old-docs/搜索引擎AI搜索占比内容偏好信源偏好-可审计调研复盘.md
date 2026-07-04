# 搜索引擎与 AI 搜索占比、内容偏好、信源偏好可审计调研复盘

生成日期：2026-06-08

调研范围：全球、中国、澳大利亚

逐来源资料目录：`docs/research_sources/搜索引擎AI搜索占比内容偏好信源偏好/`

## 1. 结论先行

本次调研要回答三个问题：

1. 国内外目前搜索引擎和 AI 搜索占比。
2. 搜索引擎搜索内容偏好。
3. AI 平台信源偏好。

结论需要先做口径校准：搜索引擎市场份额、AI chatbot 市场份额、AI 原生 App 月活、品牌发现渠道、搜索内容偏好、AI 引用源偏好不是同一种指标，不能直接相加。

### 1.1 全球

截至 2026 年 5 月，传统搜索仍由 Google 主导。StatCounter 显示全球搜索引擎份额为 Google 90.39%、Bing 5.03%、Yahoo 1.40%、Yandex 0.99%、DuckDuckGo 0.71%、Baidu 0.53%。

AI 侧，StatCounter 的 AI chatbot 份额显示 ChatGPT 79.08%、Perplexity 7.67%、Google Gemini 7.03%、Microsoft Copilot 3.23%、Claude 2.98%、DeepSeek 0.01%。但这个指标更接近 AI chatbot web/referral 份额，不等于全量 AI 搜索查询份额，也不覆盖各国 App 内使用。

DataReportal 2026 年中报告给出一个更接近营销渠道的口径：全球 16 岁以上在线成年人中，32.4% 通过搜索引擎发现新品牌、产品和服务；通过 AI 工具发现品牌的比例为 14.8%，尚未进入前 15 个品牌发现来源。

### 1.2 中国

中国不能只看 StatCounter。StatCounter 2026 年 5 月显示中国搜索引擎份额为 Baidu 47.16%、Bing 20.19%、Haosou 15.03%、Yandex 13.97%、Google 1.76%、Sogou 1.70%。这个结果能作为网页侧流量参考，但中国搜索生态大量发生在 App、超级 App、短视频、电商、本地生活和平台内搜索中，StatCounter 覆盖有限。

CNNIC 第 55 次《中国互联网络发展状况统计报告》显示，截至 2024 年 12 月，中国搜索引擎用户规模为 8.78 亿；生成式人工智能产品用户规模为 2.49 亿。

QuestMobile 2026 年一季度 AI 应用洞察显示，截至 2026 年 3 月，中国 AI 原生 App 月活用户规模达到 4.4 亿，其中豆包 3.45 亿、千问 1.66 亿、DeepSeek 1.27 亿。这个口径比 StatCounter 的 AI chatbot 份额更适合判断中国本土 AI 应用格局。

### 1.3 澳大利亚

澳大利亚传统搜索格局非常清晰：StatCounter 2026 年 5 月显示 Google 87.97%、Bing 9.09%、Yahoo 1.57%、DuckDuckGo 0.88%、Ecosia 0.22%、Yandex 0.17%。

AI chatbot 侧，StatCounter 2026 年 5 月澳大利亚数据为 ChatGPT 70.70%、Microsoft Copilot 11.62%、Google Gemini 6.16%、Claude 6.08%、Perplexity 5.44%。

澳大利亚应重点监测 Google Search / AI Overviews / AI Mode。Google 官方澳洲博客显示 AI Mode 已在澳大利亚推出，支持文字、语音、图片等多模态提问。由于 Google 在澳洲搜索市场仍接近 88%，澳洲 GEO 首发不能只盯 ChatGPT，还必须把 Google AI 搜索体验作为第一优先级。

## 2. 数据口径说明

| 口径 | 含义 | 代表来源 | 注意事项 |
| --- | --- | --- | --- |
| 搜索引擎市场份额 | 搜索引擎在网页流量/引用或 StatCounter 网络样本中的占比 | StatCounter | 不等于所有搜索行为；平台内搜索、App 内搜索、社媒搜索常被低估 |
| AI chatbot 市场份额 | AI chatbot 对网页访问或使用的相对份额 | StatCounter | 不等于 AI 搜索查询量；中国本土 App 场景偏差很大 |
| 用户规模/月活 | 某类应用或产品的活跃用户数 | CNNIC、QuestMobile、DataReportal | 与市场份额不同，不可直接与搜索引擎份额相加 |
| 品牌发现渠道 | 用户通过哪些渠道发现品牌/产品 | DataReportal / GWI | 调研口径，反映用户自报行为 |
| 搜索内容偏好 | 用户在搜索中更常寻找哪些内容 | Google Trends、Year in Search、CNNIC、平台报告 | 多数是趋势/类别信号，不是全量占比 |
| AI 信源偏好 | AI 回答中更常引用或依赖哪些来源 | Google/OpenAI/Perplexity/Kimi 官方文档，Semrush/Conductor 等研究 | 平台黑箱，且因 Prompt、语言、地区、时间变化很大 |

## 3. 国内外搜索引擎与 AI 搜索占比

### 3.1 全球搜索引擎占比

| 平台 | 份额 | 时间 | 来源 |
| --- | ---: | --- | --- |
| Google | 90.39% | 2026-05 | StatCounter |
| Bing | 5.03% | 2026-05 | StatCounter |
| Yahoo | 1.40% | 2026-05 | StatCounter |
| Yandex | 0.99% | 2026-05 | StatCounter |
| DuckDuckGo | 0.71% | 2026-05 | StatCounter |
| Baidu | 0.53% | 2026-05 | StatCounter |

判断：全球传统搜索仍是 Google 单极主导。AI 搜索正在改变用户行为，但截至 2026 年 5 月，从搜索引擎市场份额看，Google 仍是绝对入口。

### 3.2 全球 AI chatbot / AI 搜索相关占比

| 平台 | 份额 | 时间 | 来源 |
| --- | ---: | --- | --- |
| ChatGPT | 79.08% | 2026-05 | StatCounter AI Chatbot |
| Perplexity | 7.67% | 2026-05 | StatCounter AI Chatbot |
| Google Gemini | 7.03% | 2026-05 | StatCounter AI Chatbot |
| Microsoft Copilot | 3.23% | 2026-05 | StatCounter AI Chatbot |
| Claude | 2.98% | 2026-05 | StatCounter AI Chatbot |
| DeepSeek | 0.01% | 2026-05 | StatCounter AI Chatbot |

判断：ChatGPT 仍是全球 AI chatbot 份额第一，但 Perplexity、Gemini、Copilot、Claude 已形成多平台格局。对 GEO 来说，不应把 AI 搜索等同于 ChatGPT 单平台。

审计提醒：StatCounter 的 AI Chatbot Market Share 不是“AI 搜索总查询份额”，更不等于 App 内 AI 使用份额。它适合观察 AI chatbot web/referral 侧趋势。

### 3.3 中国搜索引擎占比

| 平台 | 份额 | 时间 | 来源 |
| --- | ---: | --- | --- |
| Baidu | 47.16% | 2026-05 | StatCounter |
| Bing | 20.19% | 2026-05 | StatCounter |
| Haosou | 15.03% | 2026-05 | StatCounter |
| Yandex | 13.97% | 2026-05 | StatCounter |
| Google | 1.76% | 2026-05 | StatCounter |
| Sogou | 1.70% | 2026-05 | StatCounter |

判断：百度仍是中国网页搜索侧的第一入口，但中国搜索行为高度平台化，很多真实搜索发生在抖音、小红书、微信、知乎、淘宝/京东、地图、本地生活、AI App 内部。

审计提醒：Yandex 在中国 StatCounter 数据中占比较高，可能反映样本、代理流量、跨境设备或 StatCounter 网络覆盖结构，不能直接解释为普通中国用户大量使用 Yandex 搜索。

### 3.4 中国 AI 搜索/AI 应用占比

中国 AI 侧应优先采用 CNNIC 和 QuestMobile，而不是只看 StatCounter。

| 指标 | 数据 | 时间 | 来源 |
| --- | ---: | --- | --- |
| 生成式人工智能产品用户规模 | 2.49 亿 | 2024-12 | CNNIC 第 55 次报告 |
| AI 原生 App 月活用户规模 | 4.4 亿 | 2026-03 | QuestMobile |
| 豆包 MAU | 3.45 亿 | 2026-03 | QuestMobile |
| 千问 MAU | 1.66 亿 | 2026-03 | QuestMobile |
| DeepSeek MAU | 1.27 亿 | 2026-03 | QuestMobile |

StatCounter 2026 年 5 月中国 AI chatbot 份额显示 ChatGPT 73.49%、Google Gemini 16.84%、DeepSeek 3.84%、Perplexity 2.27%、Copilot 1.85%、Claude 1.71%。但这个结果明显不能代表中国本土用户的 AI App 格局，因为 ChatGPT、Gemini、Perplexity 在中国大陆的可达性、使用场景和 App 分发都与本土产品不同。

中国真实业务判断应以以下组合为准：

- 官方用户规模：CNNIC。
- 移动 App 月活：QuestMobile。
- 网页搜索份额：StatCounter。
- 实际 GEO 项目监测：按 DeepSeek、豆包、Kimi、文小言/文心、腾讯元宝、千问、纳米 AI 搜索、秘塔 AI 搜索等平台真实采样。

### 3.5 澳大利亚搜索引擎占比

| 平台 | 份额 | 时间 | 来源 |
| --- | ---: | --- | --- |
| Google | 87.97% | 2026-05 | StatCounter |
| Bing | 9.09% | 2026-05 | StatCounter |
| Yahoo | 1.57% | 2026-05 | StatCounter |
| DuckDuckGo | 0.88% | 2026-05 | StatCounter |
| Ecosia | 0.22% | 2026-05 | StatCounter |
| Yandex | 0.17% | 2026-05 | StatCounter |

判断：澳大利亚是典型 Google 主导市场。Bing 有第二入口价值，尤其与 Microsoft Copilot 和 Windows/Edge 分发有关，但 Google 仍是首要监测对象。

### 3.6 澳大利亚 AI chatbot / AI 搜索相关占比

| 平台 | 份额 | 时间 | 来源 |
| --- | ---: | --- | --- |
| ChatGPT | 70.70% | 2026-05 | StatCounter AI Chatbot |
| Microsoft Copilot | 11.62% | 2026-05 | StatCounter AI Chatbot |
| Google Gemini | 6.16% | 2026-05 | StatCounter AI Chatbot |
| Claude | 6.08% | 2026-05 | StatCounter AI Chatbot |
| Perplexity | 5.44% | 2026-05 | StatCounter AI Chatbot |

澳大利亚还需要单独关注 Google AI Mode。Google 澳大利亚官方博客称 AI Mode 已在澳洲推出，支持自然语言、多模态提问。由于 AI Mode 是叠加在 Google Search 上的体验，不能只看 StatCounter 的 AI chatbot 份额来评估澳洲 AI 搜索影响。

## 4. 搜索引擎搜索内容偏好

### 4.1 全球搜索内容偏好

全球搜索内容偏好可以分为七类：

| 类别 | 典型搜索 | 特征 | GEO 含义 |
| --- | --- | --- | --- |
| 导航型 | brand login、company website | 用户已知道目标 | 品牌官网和知识面板要稳定 |
| 信息型 | what is、how to、why、guide | 用户找解释和教程 | 需要 FAQ、指南、定义页 |
| 新闻/趋势型 | election、sports event、celebrity、AI product | 时效性强 | 需要新鲜内容和媒体信源 |
| 商业调研型 | best X、X vs Y、reviews、alternatives | 转化前比较 | 需要评测、对比、第三方口碑 |
| 本地型 | near me、open now、best in city | 地理位置强 | 需要 Google Business Profile、本地评论和地图一致性 |
| 交易型 | price、coupon、buy、shipping | 接近购买 | 需要价格、库存、配送、退换货信息 |
| 多媒体型 | image、video、recipe、tutorial | 图片/视频更有解释力 | 需要 YouTube、图片、短视频、结构化素材 |

DataReportal 2026 年中报告显示，搜索引擎仍是全球在线成年人发现新品牌、产品和服务的第一来源之一，比例为 32.4%。这说明即便 AI 工具增长，搜索引擎仍承载大量品牌发现和商业调研需求。

Google Year in Search 2025 显示，全球搜索趋势覆盖 AI、体育、新闻事件、娱乐、人物、电影、游戏、食物和旅行等类别。这类数据是“趋势上升”口径，不是全年总搜索量口径，但能说明搜索引擎承载的是实时兴趣和社会注意力。

### 4.2 中国搜索内容偏好

中国搜索偏好不能只用“网页搜索”理解。更准确地说，中国用户搜索内容被拆到多个平台：

| 场景 | 主要入口 | 内容偏好 |
| --- | --- | --- |
| 通用网页/官方信息 | 百度、Bing、360/Haosou、搜狗 | 官网、百科、新闻、问答、文库、政策、医疗、教育 |
| 生活方式/消费体验 | 小红书、抖音、B站、知乎 | 真实体验、测评、避坑、教程、城市攻略 |
| 电商购物 | 淘宝、京东、拼多多、抖音电商 | 商品、价格、评价、销量、直播内容 |
| 本地生活 | 高德、百度地图、美团、大众点评 | 附近、路线、店铺评价、团购、营业时间 |
| 知识/文档 | 百度文库、知乎、公众号、Kimi、秘塔 | 摘要、长文、论文、报告、资料整理 |
| AI 问答/总结 | 豆包、DeepSeek、Kimi、文心/文小言、千问、腾讯元宝 | 直接答案、解释、写作、代码、学习、资料汇总 |

CNNIC 显示，截至 2024 年 12 月中国搜索引擎用户规模为 8.78 亿，说明搜索仍是基础工具。但 QuestMobile 的 AI 原生 App 月活达到 4.4 亿，说明“问 AI”正在成为中国用户新的信息获取方式。

中国搜索内容偏好的关键变化：

- 从网页搜索扩展到平台内搜索。
- 从关键词检索扩展到“问答、总结、改写、生成”。
- 从官网信息扩展到社区经验和短视频内容。
- 从单一百度入口扩展到百度、抖音、小红书、知乎、微信、电商、本地生活、AI App 的组合。

### 4.3 澳大利亚搜索内容偏好

澳大利亚搜索内容偏好更接近英语成熟市场：

| 场景 | 主要入口 | 内容偏好 |
| --- | --- | --- |
| 通用信息 | Google | 新闻、官方信息、知识解释、教程 |
| 品牌/产品发现 | Google、YouTube、Instagram、TikTok | 产品介绍、测评、视频、社交内容 |
| 消费评价 | ProductReview、Google Reviews、Reddit、CHOICE、Trustpilot | 真实评论、评分、投诉、独立测评 |
| 本地服务 | Google Maps、Google Business Profile、local directories | 附近、营业时间、电话、路线、评价 |
| 专业/高风险信息 | gov.au、ACCC、ASIC、ATO、TGA、CHOICE | 政府、监管、消费者权益、产品安全 |
| AI 问答 | Google AI Mode、ChatGPT、Perplexity、Gemini、Copilot | 综合答案、比较、推荐、解释、计划 |

DataReportal 2026 Australia 显示，澳大利亚互联网用户约 2620 万，互联网普及率 97.1%；社交媒体用户身份约 2100 万；YouTube 在澳洲的广告触达约 2100 万，Instagram 约 1520 万，TikTok 成年用户约 1090 万。这说明澳大利亚虽然 Google 搜索强势，但视频和社交平台在产品发现、教程和口碑内容中很重要。

Google Australia 的 Year in Search 2025 显示，澳洲搜索趋势覆盖社会热点、人物、娱乐、体育、产品、生活趋势等。对澳洲 GEO 来说，问题集应包含：

- `best [category] in Australia`
- `[brand] reviews Australia`
- `[brand] vs [competitor] Australia`
- `is [brand] legit Australia`
- `[product] ProductReview`
- `[product] CHOICE review`
- `where to buy [product] in Sydney / Melbourne / Brisbane`
- `[category] near me`

## 5. AI 平台信源偏好

### 5.1 先说边界：没有一个统一的 AI 信源偏好

AI 平台信源偏好高度依赖：

- 平台：Google AI Overviews、AI Mode、ChatGPT Search、Perplexity、Gemini、Copilot、Kimi、豆包、DeepSeek 等。
- 查询意图：产品推荐、新闻事实、学术、医疗、法律、本地服务、B2B 软件、消费品。
- 语言和地区：英语、中文、澳洲本地、美国本地、中国大陆。
- 时间：模型版本、索引更新、实时检索状态。
- 是否联网：有些回答来自模型记忆，有些来自实时检索。

因此，任何“AI 最喜欢某一个网站”的结论都要谨慎。可审计做法是按平台、问题集、市场和时间持续采样。

### 5.2 全球 AI 平台信源偏好

| 平台 | 可审计机制 | 常见信源倾向 | 操作性判断 |
| --- | --- | --- | --- |
| Google AI Overviews / AI Mode | Google 官方称 AI 搜索体验植根核心排名和质量系统 | Google 索引中的高质量网页、结构化数据、YouTube、社区讨论、品牌官网、新闻/博客 | 传统 SEO、结构化数据、YouTube 和高质量第三方内容仍重要 |
| ChatGPT Search | OpenAI 官方称提供带相关网页来源链接的及时答案 | Wikipedia、主流媒体、官方文档、品牌官网、实时网页来源 | 适合做官网事实页、媒体稿、权威资料、维基/百科级实体一致性 |
| Perplexity | Perplexity API 文档称使用全球规模检索基础设施，返回引用答案 | 引用密度高，常见 Reddit、YouTube、专业媒体、评测、官方文档、研究资料 | 适合做可引用资料、评测信源、社区口碑和外部证据 |
| Gemini | 与 Google 搜索生态关联强 | Google 搜索索引、YouTube、Google 生态、官方网页 | 和 Google SEO/YouTube/结构化数据强相关 |
| Copilot | 与 Bing/Microsoft 生态相关 | Bing 索引、Microsoft 生态、网页来源 | Bing SEO、企业官网、文档、新闻源有价值 |
| Claude | 取决于是否开启网页/连接器 | 长文、技术、学术、主流媒体、文档型来源 | 对 B2B、技术、研究型内容更友好，但需实际采样 |

第三方 citation 研究的共同结论是：Reddit、Wikipedia、YouTube、LinkedIn、主流媒体、品牌自有网页、评论/评测网站经常出现在 AI 引用中。但不同研究结论存在差异。例如 Semrush 研究强调 Reddit 和 LinkedIn 在多个 AI 平台中靠前；Conductor 研究强调不同平台和意图的 citation 行为差异；Yext 相关研究则认为品牌可控来源占很高比例。

综合判断：GEO 不应只押一个信源。应构建多层信源池：

- 第一层：品牌官网、产品页、FAQ、帮助中心、结构化数据。
- 第二层：新闻媒体、行业报告、权威榜单、百科实体。
- 第三层：社区与真实评价，如 Reddit、Quora、YouTube、论坛、ProductReview。
- 第四层：本地和监管来源，如政府、协会、监管机构、消费者组织。
- 第五层：垂直评测和交易信源，如 G2、Capterra、Trustpilot、电商评价、地图评价。

### 5.3 中国 AI 平台信源偏好

中国 AI 平台信源偏好更受中文互联网生态影响。

| 平台 | 可审计信息 | 推断信源偏好 | 审计等级 |
| --- | --- | --- | --- |
| Kimi | 官方帮助中心称联网搜索基于相关性、权威性、时效性筛选，覆盖主流新闻媒体、政府公告、金融数据平台、学术期刊库等 100+ 可信来源 | 政府官网、权威媒体、学术、财报、专业数据库、网页搜索结果 | 较强 |
| 文心/文小言 | App Store 和百度智能云材料显示其提供多模态搜索，百度千帆开放百度 AI 搜索、百度地图、百度文库、百度网盘等能力 | 百度搜索索引、百度百科/文库/地图、官网、新闻、百度生态内容 | 中等 |
| 豆包 | 公开页面强调信息获取、资料整理、问题拆分，需要结合原始来源交叉验证 | 字节生态内容、公开网页、资讯、视频、文档；具体偏好需项目采样 | 较弱 |
| DeepSeek | 公开 API 文档主要是模型/API 信息，联网搜索信源机制公开不足 | 若开启联网，可能依赖实时网页检索；具体偏好需采样 | 较弱 |
| 千问/通义 | 与阿里生态相关，AI 原生 App 月活高 | 公开网页、阿里生态、电商/企业服务资料、官方文档 | 待采样 |
| 秘塔/纳米 AI 搜索 | 产品定位为 AI 搜索 | 网页、学术/文档、新闻、垂直数据源 | 待采样 |

中国 GEO 的实际信源池建议：

- 官网和品牌百科：官网、百度百科、品牌词条、产品页。
- 百度生态：百度搜索、百度文库、百度知道、百家号、百度地图。
- 内容社区：知乎、小红书、B站、抖音、微信公众号。
- 媒体和行业报告：财新、36氪、钛媒体、证券媒体、艾瑞、QuestMobile 等。
- 交易和评价：天猫、京东、抖音电商、大众点评、美团、黑猫投诉。
- 政府与权威：gov.cn、监管机构、行业协会、标准文件。

### 5.4 澳大利亚 AI 平台信源偏好

澳大利亚 AI 信源偏好不能直接套中国，也不能只套美国。澳洲 GEO 应优先建设以下信源：

| 信源层 | 澳洲代表 | 为什么重要 |
| --- | --- | --- |
| 官方/监管 | gov.au、ACCC、ASIC、ATO、TGA、ACMA、state government sites | AI 回答高风险事实、消费者权益、金融、医疗、税务、本地服务时需要权威来源 |
| 品牌自有 | `.com.au` 官网、AU landing page、FAQ、shipping/returns、pricing AUD、store locator | 让 AI 明确品牌在澳洲是否服务、价格、配送、售后 |
| 消费评价 | ProductReview.com.au、Google Reviews、Trustpilot、Reddit AU threads | 澳大利亚用户购买前高度依赖评论和真实体验 |
| 独立评测 | CHOICE、Canstar、Finder、WhistleOut、Mozo 等 | 消费品、金融、保险、电信、家电等领域的重要第三方证据 |
| 本地媒体 | ABC、SBS、The Guardian Australia、SMH/The Age、AFR、news.com.au | 新闻、品牌事件、社会可信度 |
| 视频/社交 | YouTube、TikTok、Instagram、Facebook groups | 教程、产品体验、生活方式、UGC 口碑 |
| 本地目录 | Google Business Profile、Yellow Pages、local directories | 本地服务、门店、路线、营业时间、电话 |

ProductReview 自述为澳大利亚较早且综合的消费者意见网站，拥有大量澳大利亚消费者评论、月访问和 Google 展示数据。CHOICE 则是澳大利亚消费者组织，覆盖产品测试、购买指南和消费者权益内容。这两类信源在澳洲消费品、家居、金融、保险、电信、健康和零售类 GEO 中应重点监测。

但要注意：目前没有公开证据证明 ChatGPT、Gemini、Perplexity 在澳洲一定优先引用 ProductReview 或 CHOICE。更准确的做法是：把它们设为澳洲 SourceGraph 的重点候选信源，通过 Prompt 采样验证引用频率。

## 6. 澳大利亚单独落地建议

### 6.1 平台优先级

澳洲首发建议监测权重：

| 层级 | 平台 | 建议优先级 |
| --- | --- | --- |
| P0 | Google Search、Google AI Overviews、Google AI Mode | 最高 |
| P0 | ChatGPT Search | 最高 |
| P1 | Bing / Microsoft Copilot | 高 |
| P1 | Perplexity | 高 |
| P1 | Gemini | 高 |
| P2 | Claude | 中 |
| P2 | Reddit、YouTube、ProductReview、CHOICE、Google Reviews | 作为信源池重点监测 |

### 6.2 澳洲问题集必须本地化

建议第一批问题集至少覆盖：

- `best [category] in Australia`
- `best [category] in Sydney`
- `best [category] in Melbourne`
- `[brand] reviews Australia`
- `[brand] vs [competitor] Australia`
- `is [brand] legit in Australia`
- `[brand] complaints Australia`
- `[category] ProductReview`
- `[category] CHOICE review`
- `where to buy [product] in Australia`
- `[brand] shipping Australia`
- `[brand] returns Australia`
- `[product] price AUD`

### 6.3 澳洲知识库字段

澳洲品牌知识库应增加：

- `market = AU`
- `language = en-AU`
- `currency = AUD`
- `GST included`
- `shipping_regions`
- `returns_policy_AU`
- `warranty_AU`
- `support_hours_Australia`
- `local_phone`
- `store_locations`
- `ProductReview_url`
- `CHOICE_url_if_any`
- `Google_Business_Profile_url`
- `ABN/ACN_if_relevant`

### 6.4 澳洲信源图谱

澳洲 SourceGraph 建议按以下类型建表：

| 类型 | 示例字段 |
| --- | --- |
| 官方信源 | gov.au / regulator / association / official brand AU site |
| 评论信源 | ProductReview / Google Reviews / Trustpilot / Reddit |
| 评测信源 | CHOICE / Canstar / Finder / WhistleOut / comparison sites |
| 媒体信源 | ABC / SBS / Guardian AU / SMH / AFR / News.com.au |
| 视频信源 | YouTube / TikTok / Instagram |
| 本地信源 | Google Business Profile / Maps / local directory |

## 7. 需要避免的误读

1. 不要把 AI chatbot 份额当作 AI 搜索份额。

   StatCounter AI Chatbot 份额很有参考价值，但不是全量 AI 搜索查询，也不覆盖所有 App 内行为。

2. 不要把中国 StatCounter AI 份额当作中国本土 AI 应用份额。

   中国应优先看 CNNIC 和 QuestMobile，再通过实际平台采样补足。

3. 不要把“搜索内容偏好”理解成固定百分比。

   搜索内容偏好通常只能通过趋势榜、调研、平台报告和实际关键词/Prompt 数据推断。

4. 不要假设所有 AI 平台引用同一套来源。

   ChatGPT、Google AI、Perplexity、Kimi、豆包的检索架构和来源偏好不同。

5. 不要直接照搬美国信源到澳洲。

   澳洲要强化 `.com.au` 官网、本地评论、ProductReview、CHOICE、本地监管和本地媒体。

## 8. 可审计来源摘要

| 编号 | 来源 | 用途 | 口径 |
| --- | --- | --- | --- |
| H01 | StatCounter 全球搜索引擎份额 | 全球搜索占比 | 2026-05 搜索引擎份额 |
| H02 | StatCounter 中国搜索引擎份额 | 中国网页搜索占比 | 2026-05 搜索引擎份额 |
| H03 | StatCounter 澳大利亚搜索引擎份额 | 澳洲搜索占比 | 2026-05 搜索引擎份额 |
| H04 | StatCounter 全球 AI chatbot 份额 | 全球 AI chatbot 参考 | 2026-05 AI chatbot 份额 |
| H05 | StatCounter 中国 AI chatbot 份额 | 中国网页侧 AI chatbot 参考 | 不代表国内 AI App |
| H06 | StatCounter 澳大利亚 AI chatbot 份额 | 澳洲 AI chatbot 参考 | 2026-05 |
| H07 | CNNIC 第 55 次报告 | 中国搜索/生成式 AI 用户规模 | 官方统计 |
| H08 | QuestMobile 2026 Q1 AI 应用洞察 | 中国 AI 原生 App 月活 | 移动应用监测 |
| H09 | DataReportal 2026 Mid-Year | 全球品牌发现渠道 | 调研/估算 |
| H10 | DataReportal Digital 2026 Australia | 澳洲互联网和社交平台规模 | 调研/估算 |
| H11 | Google Year in Search 2025 | 全球/澳洲搜索内容趋势 | 趋势口径 |
| H12 | Google AI Mode Australia | 澳洲 Google AI 搜索产品状态 | 官方博客 |
| H13 | Google Search Central 生成式 AI 搜索优化 | Google AI 搜索信源机制 | 官方文档 |
| H14 | OpenAI ChatGPT Search | ChatGPT Search 来源机制 | 官方发布 |
| H15 | Perplexity API / Search API | Perplexity 检索与引用机制 | 官方帮助 |
| H16 | Kimi 联网搜索帮助 | 中国 AI 搜索信源机制 | 官方帮助 |
| H17 | 百度文心 / 文小言与百度千帆 | 百度 AI 搜索能力线索 | 官方/应用商店 |
| H18 | Semrush AI citation study | AI 引用源研究 | 第三方研究 |
| H19 | Conductor AI citation study | 平台 citation 行为差异 | 第三方研究 |
| H20 | ProductReview About Us | 澳洲消费者评论信源 | 平台自述 |
| H21 | CHOICE About Us | 澳洲独立消费者评测信源 | 组织自述 |

## 9. 最终判断

全球层面，传统搜索仍然是品牌发现和高意图需求的主入口，AI 搜索正在增长但尚未整体替代搜索引擎。中国层面，百度等网页搜索仍有基础规模，但真实搜索行为已被短视频、电商、社区、本地生活和 AI 原生 App 拆分。澳大利亚层面，Google 搜索仍是绝对核心入口，同时 ChatGPT、Copilot、Gemini、Claude、Perplexity 构成 AI 问答层。

对澳洲首发 GENO/GEO 产品，技术上应采用：

1. Google Search / AI Mode 第一优先。
2. ChatGPT Search 第二优先。
3. Bing/Copilot、Perplexity、Gemini 并行监测。
4. ProductReview、CHOICE、Google Reviews、Reddit、YouTube、本地媒体和 gov.au 建为重点信源池。
5. 以问题集和答案快照做真实采样，不依赖单一第三方“AI 信源偏好”结论。
