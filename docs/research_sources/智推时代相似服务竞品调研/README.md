# 智推时代相似服务与竞争企业调研来源索引

生成日期：2026-06-08  
主报告：`../../智推时代相似服务与竞争企业-可审计调研复盘.md`  
本地 PDF 摘录：`local_extracts/PDF_智推时代服务与GENO竞品对照摘录.txt`  
逐来源摘要：`来源摘要卡片.md`  
网页快照目录：`raw_pages/`

## 审计口径

- 本次调研以智推时代 PDF 中公开披露的 GENO 能力为基线：AI 搜索监测、意图分析、品牌知识库/知识图谱、内容结构化与分发、AI 可见性评分和持续迭代。
- “竞争企业”分为三类：直接 GEO/AI Search Visibility SaaS，传统 SEO 平台向 AI 可见性延伸的相邻竞品，国内及跨境 GEO 全案服务商。
- `raw_pages/` 保存本次访问到的网页 HTML 快照；现代前端站点可能依赖 JS 渲染，命令行 HTML 不一定等于浏览器完整展示。
- `来源摘要卡片.md` 对每一个 Vxx 来源逐条记录 URL、落盘文件、关键线索、证明力和审计备注。
- 官网和官方文档可证明“企业如何自述产品能力”；媒体稿、榜单稿、转载稿主要用于发现竞品和市场叙事，不能单独证明客户数量、融资、效果或排名真实性。

## 下载异常记录

| 编号 | 情况 | 处理 |
| --- | --- | --- |
| V05 | `https://otterly.ai/` 两次抓取均返回 202 且仅 169 字节 | 保留异常快照，使用 Otterly 官方帮助站 V06/V48 作为有效证据 |
| V18 | 初次抓取 Writesonic GEO 文档时未形成文件 | 已重抓成功，使用 `V18_writesonic_geo_docs.html` |
| V37 | 初次抓取 GeoLift 官网时未形成文件 | 已重抓成功，使用 `V37_geolift.html` |
| V49 | Writesonic 博客 URL 返回 404 但生成较大 HTML | 不作为核心证据，核心使用 V18/V19 |
| V51 | 质安华 GNA 子路径 `/geoyouhua/` 未形成文件 | 改用根域名 `V51_gna_home.html` 和内容页 `V62_gna_news_strategy.html` |
| V61 | 质安华 GNA 新闻子路径 `/news/318.html` 未形成文件 | 保留异常记录，不纳入核心证据 |
| V35 | 博搜科技快照文本有效信息较少，主要保留标题级线索 | 在主报告中仅作为低证明力国内相似服务线索 |

## 来源清单

| 编号 | 来源 | URL | 落盘文件 | 用途 |
| --- | --- | --- | --- | --- |
| V00 | 本地 PDF 摘录 | `/home/ymm/ym/gz/20260608-geo/docs/智推时代-全球GEO业务介绍.pdf` | `local_extracts/PDF_智推时代服务与GENO竞品对照摘录.txt` | 智推时代能力基线 |
| V01 | Profound AI Instructions | https://www.tryprofound.com/ai-instructions | `raw_pages/V01_profound_ai_instructions.html` | 海外直接竞品、AEO/GEO 自述 |
| V02 | Profound Agent Analytics docs | https://docs.tryprofound.com/agent-analytics/overview | `raw_pages/V02_profound_agent_analytics_docs.html` | AI crawler/agent analytics |
| V03 | Peec AI | https://peec.ai/ | `raw_pages/V03_peec_home.html` | AI search analytics 直接竞品 |
| V04 | Peec Actions | https://peec.ai/product-actions | `raw_pages/V04_peec_actions.html` | 行动建议与信源机会 |
| V05 | OtterlyAI home | https://otterly.ai/ | `raw_pages/V05_otterly_home.html` | 异常快照 |
| V06 | OtterlyAI monitoring interval | https://help.otterly.ai/monitoring-interval | `raw_pages/V06_otterly_monitoring_interval.html` | 日频监测证据 |
| V07 | AthenaHQ | https://athenahq.ai/ | `raw_pages/V07_athenahq_home.html` | AI search/GEO 平台竞品 |
| V08 | Scrunch | https://scrunch.com/ | `raw_pages/V08_scrunch_home.html` | AI customer experience/visibility |
| V09 | Scrunch Query API | https://developers.scrunch.com/api-reference/query/overview | `raw_pages/V09_scrunch_api_query.html` | 聚合 AI 可见性指标 API |
| V10 | Evertune Brand Monitoring | https://www.evertune.ai/products/brand-monitoring | `raw_pages/V10_evertune_brand_monitoring.html` | AI brand monitoring |
| V11 | Brandlight | https://www.brandlight.ai/ | `raw_pages/V11_brandlight_home.html` | 企业级 AI visibility |
| V12 | Gumshoe | https://www.gumshoe.ai/ | `raw_pages/V12_gumshoe_home.html` | persona-driven GEO 平台 |
| V13 | Gumshoe methodology | https://www.gumshoe.ai/resources/gumshoe-methodology | `raw_pages/V13_gumshoe_methodology.html` | 抽样、非确定性、API 采集方法 |
| V14 | Bluefish AI | https://www.bluefishai.com/ | `raw_pages/V14_bluefish_home.html` | Enterprise AI marketing/GEO |
| V15 | Bluefish about | https://www.bluefishai.com/about | `raw_pages/V15_bluefish_about.html` | 团队和定位 |
| V16 | Bluefish PRNewswire | https://www.prnewswire.com/news-releases/bluefish-raises-43-million-series-b-to-power-agentic-marketing-for-the-fortune-500-302741124.html | `raw_pages/V16_bluefish_prnewswire.html` | 融资和企业级定位 |
| V17 | ZipTie.dev | https://ziptie.dev/ | `raw_pages/V17_ziptie_home.html` | AI Overview/ChatGPT/Perplexity 追踪 |
| V18 | Writesonic GEO docs | https://docs.writesonic.com/docs/geo-getting-started | `raw_pages/V18_writesonic_geo_docs.html` | GEO 产品文档 |
| V19 | Writesonic features | https://writesonic.com/features?via=official-writesonic | `raw_pages/V19_writesonic_features.html` | AI search growth engine |
| V20 | Semrush AI Visibility data | https://www.semrush.com/kb/1607-semrush-ai-visibility-data | `raw_pages/V20_semrush_ai_visibility_data.html` | 数据来源和区域覆盖 |
| V21 | Semrush AI Visibility getting started | https://www.semrush.com/kb/1496-getting-started-with-ai-visibility-toolkit | `raw_pages/V21_semrush_ai_visibility_getting_started.html` | AI Visibility Toolkit 流程 |
| V22 | Ahrefs Brand Radar | https://ahrefs.com/brand-radar | `raw_pages/V22_ahrefs_brand_radar.html` | AI visibility 数据库 |
| V23 | Ahrefs Brand Radar methodology | https://ahrefs.com/blog/brand-radar-methodology/ | `raw_pages/V23_ahrefs_brand_radar_methodology.html` | prompt/response 采集方法 |
| V24 | BrightEdge AI Catalyst | https://www.brightedge.com/ai-catalyst | `raw_pages/V24_brightedge_ai_catalyst.html` | 企业 SEO 平台 AI 搜索模块 |
| V25 | Conductor Intelligence | https://www.conductor.com/platform/intelligence/ | `raw_pages/V25_conductor_intelligence.html` | AEO/SEO 统一平台 |
| V26 | HubSpot AI Search Grader | https://www.hubspot.com/company-news/from-seo-to-lmo-hubspot-launches-the-first-free-tool-for-ai-discovery | `raw_pages/V26_hubspot_ai_search_grader.html` | 免费 AI discovery 工具 |
| V27 | 泓动数据 | https://www.hongdongshuju.com/ | `raw_pages/V27_hongdong_data.html` | 国内 GEO 全案服务 |
| V28 | 百付科技 GEO | https://www.baifukeji.cn/ | `raw_pages/V28_baifu_keji.html` | 悟空 GEO 系统 |
| V29 | 百付科技关于页 | https://www.baifuai.com/about/ | `raw_pages/V29_baifuai_about.html` | 公司背景 |
| V30 | 百搜 GEO | https://www.ai-geo.cn/ | `raw_pages/V30_baisou_geo.html` | 国内 GEO 服务商 |
| V31 | 趣搜科技 | https://www.qusougeo.com/ | `raw_pages/V31_qusou_geo.html` | GEO 智能中台和培训 |
| V32 | 冠一 GEO | https://www.guanyigeo.com/ | `raw_pages/V32_guanyi_geo.html` | 国内 GEO 平台/服务 |
| V33 | 源易 GEO | https://www.ggseo.cn/geo/ | `raw_pages/V33_yuanyi_geo.html` | 传统 SEO 公司转 GEO |
| V34 | 智鸥 GEO | https://www.zhiougeo.com/ | `raw_pages/V34_zhiou_geo.html` | SeaGEO 系统 |
| V35 | 博搜科技 | https://www.bosougeo.com/ | `raw_pages/V35_bosou_geo.html` | 低信息量国内线索 |
| V36 | 智搜未来 | https://www.zsaigeo.com/ | `raw_pages/V36_zhisou_future.html` | GEO+Agent 代运营 |
| V37 | GeoLift | https://geolift.cn/ | `raw_pages/V37_geolift.html` | 国内 GEO 服务流程 |
| V38 | 森辰 GEO | https://www.senchengeo.cn/sc/ | `raw_pages/V38_senchen_geo.html` | B2B/制造业 GEO 线索 |
| V39 | 光引 GEO | https://www.guangyinai.com/ | `raw_pages/V39_guangyin_geo.html` | GEO2.0 与监测 |
| V40 | Global Gravity GEO | https://www.global-gravity.com/services/geo | `raw_pages/V40_global_gravity_geo.html` | 多语种/国际 GEO |
| V41 | GEO-Star | https://www.geo-star.com/ | `raw_pages/V41_geo_star.html` | 国内 GEO 诊断/服务 |
| V42 | 搜优宝 GEO | https://www.soyobao.com/ | `raw_pages/V42_soyobao_geo.html` | AI 品牌监控与全链路系统 |
| V43 | IT之家 TOP5 | https://www.ithome.com/0/949/870.htm | `raw_pages/V43_ithome_top5_949870.html` | 国内服务商榜单线索 |
| V44 | IT之家 TOP10 | https://www.ithome.com/0/958/527.htm | `raw_pages/V44_ithome_top10_958527.html` | 国内竞争格局线索 |
| V45 | 界面新闻转载 | https://m.jiemian.com/article/14520914.html | `raw_pages/V45_jiemian_vendor_selection.html` | 智推时代及竞品线索 |
| V46 | XOOER TOP5 | https://www.xooer.com/zh-CN/resources/Top-5-Domestic-GEO-Generative-Engine-Optimization-Companies-in-2026 | `raw_pages/V46_xooer_top5_geo.html` | 国内/跨境榜单线索 |
| V47 | 商赢网络 | https://www.geo.gz.cn/ | `raw_pages/V47_geo_cn_service.html` | 国内 GEO 服务商 |
| V48 | OtterlyAI help home | https://help.otterly.ai/ | `raw_pages/V48_otterly_docs_home.html` | Otterly 功能索引 |
| V49 | Writesonic GEO blog | https://writesonic.com/blog/generative-engine-optimization | `raw_pages/V49_writesonic_geo_blog.html` | 返回 404，低证明力 |
| V50 | XOOER 官网 | https://www.xooer.com/zh-CN | `raw_pages/V50_xooer_home.html` | 跨境 GEO 直接竞品 |
| V51 | 质安华 GNA 官网 | https://www.gnagroup.cn/ | `raw_pages/V51_gna_home.html` | SEO+GEO 服务商 |
| V52 | 百分点 Generforce | https://www.generforce.cn/product.html | `raw_pages/V52_generforce.html` | AI 搜索洞察与优化平台 |
| V53 | Geopher.ai | https://www.geopher.ai/ | `raw_pages/V53_geopher.html` | 东南亚 AI visibility 平台 |
| V54 | Geostar.ai | https://www.geostar.ai/ | `raw_pages/V54_geostar_ai.html` | GEO SaaS/managed service |
| V55 | SHEEP-GEO | https://global.sheepgeo.com/ | `raw_pages/V55_sheep_geo.html` | 中国团队出海 GEO 平台 |
| V56 | 百原科技 | https://www.baiyuan.io/about.html | `raw_pages/V56_baiyuan_about.html` | 企业 AI 知识库/GEO 辅助服务 |
| V57 | AIPO GEO | https://www.aipogeo.com/ | `raw_pages/V57_aipo_geo.html` | AI visibility audit 闭环 |
| V58 | GEOly | https://www.geoly.ai/ | `raw_pages/V58_geoly_ai.html` | DTC/e-commerce GEO 平台 |
| V59 | Meikai | https://www.meikai.ai/ | `raw_pages/V59_meikai_ai.html` | 企业 GEO 平台 |
| V60 | Visibiliti | https://www.visibiliti.ai/ | `raw_pages/V60_visibiliti_ai.html` | 南非/全球 AI visibility 平台 |
| V62 | 质安华策略文章 | https://www.gnagroup.cn/news/367.html | `raw_pages/V62_gna_news_strategy.html` | 平台差异化 GEO 策略 |

## 主报告对应章节

| 主报告章节 | 主要来源 |
| --- | --- |
| 智推时代能力基线 | V00 |
| 海外直接 GEO/AI visibility 竞品 | V01-V19、V48-V60 |
| 传统 SEO 平台相邻竞品 | V20-V26 |
| 国内直接/相似服务商 | V27-V47、V50-V52、V62 |
| 国内榜单和二手市场叙事 | V43-V46 |
| 澳大利亚首发技术竞争判断 | V01-V26、V40、V53-V60 |
