# GENO 四阶闭环技术栈与开源替代调研来源索引

生成日期：2026-06-08  
主报告：`../../智推时代GENO四阶闭环技术栈与开源替代-可审计调研复盘.md`  
本地 PDF 摘录：`local_extracts/PDF_GENO四阶闭环与技术实现摘录.txt`  
网页快照目录：`raw_pages/`

## 审计口径

- `local_extracts/` 保存本地 PDF 的相关页文本摘录，用于复核 GENO 方法论和 PDF 原文。
- `raw_pages/` 保存外部网页的命令行抓取 HTML。部分现代文档站依赖前端渲染，HTML 快照不一定等于浏览器完整渲染页。
- 本 README 记录每个网页的 URL、落盘文件、用途和审计备注。
- “开源替代”不等于所有组件都可无条件商用。部分项目是 source-available、开权模型、AGPL、SUL、ELv2 或研究许可证，正式选型前必须逐项核查许可证。

## 下载异常记录

| 编号 | 情况 | 处理 |
| --- | --- | --- |
| T11 | `https://milvus.io/docs/overview.md` 命令行抓取时发生重定向/写入异常，没有形成有效文件 | 改用官方 GitHub 仓库快照 `T11_milvus_github.html` |
| T40 | `https://superset.apache.org/docs/intro/` 返回 313 字节的小文件，不足以作为有效快照 | 改用官方 GitHub 仓库快照 `T40_superset_github.html` |

## 来源清单

| 编号 | 来源 | URL | 落盘文件 | 用途 |
| --- | --- | --- | --- | --- |
| T00 | 本地 PDF 摘录 | `/home/ymm/ym/gz/20260608-geo/docs/智推时代-全球GEO业务介绍.pdf` | `local_extracts/PDF_GENO四阶闭环与技术实现摘录.txt` | GENO 四阶闭环、产品架构、四大系统 |
| T01 | Scrapy 文档 | https://docs.scrapy.org/en/latest/ | `raw_pages/T01_scrapy_docs.html` | 通用网页抓取替代 |
| T02 | Playwright 文档 | https://playwright.dev/docs/intro | `raw_pages/T02_playwright_docs.html` | 浏览器自动化、动态页面采集 |
| T03 | Crawlee 文档 | https://crawlee.dev/docs/introduction | `raw_pages/T03_crawlee_docs.html` | JS/TS 爬虫和浏览器采集 |
| T04 | SearXNG 文档 | https://docs.searxng.org/ | `raw_pages/T04_searxng_docs.html` | 开源聚合搜索、搜索基线 |
| T05 | SerpBear 文档 | https://docs.serpbear.com/ | `raw_pages/T05_serpbear_docs.html` | 搜索排名监控原型 |
| T06 | LiteLLM 文档 | https://docs.litellm.ai/docs/ | `raw_pages/T06_litellm_docs.html` | 多模型 API 网关 |
| T07 | LangChain 文档 | https://docs.langchain.com/oss/python/langchain/overview | `raw_pages/T07_langchain_docs.html` | LLM 应用编排和 Agent/RAG |
| T08 | LlamaIndex 文档 | https://docs.llamaindex.ai/en/stable/ | `raw_pages/T08_llamaindex_docs.html` | RAG、知识库索引 |
| T09 | pgvector GitHub | https://github.com/pgvector/pgvector | `raw_pages/T09_pgvector_github.html` | PostgreSQL 向量检索 |
| T10 | Qdrant 文档 | https://qdrant.tech/documentation/ | `raw_pages/T10_qdrant_docs.html` | 向量数据库 |
| T11 | Milvus GitHub | https://github.com/milvus-io/milvus | `raw_pages/T11_milvus_github.html` | 向量数据库 |
| T12 | Neo4j 文档 | https://neo4j.com/docs/ | `raw_pages/T12_neo4j_docs.html` | 知识图谱/property graph |
| T13 | Apache Jena 文档 | https://jena.apache.org/documentation/ | `raw_pages/T13_apache_jena_docs.html` | RDF/SPARQL/语义网 |
| T14 | RDFLib 文档 | https://rdflib.readthedocs.io/en/stable/ | `raw_pages/T14_rdflib_docs.html` | Python RDF 处理 |
| T15 | Microsoft GraphRAG | https://github.com/microsoft/graphrag | `raw_pages/T15_microsoft_graphrag.html` | 图谱增强 RAG |
| T16 | BERTopic 文档 | https://maartengr.github.io/BERTopic/ | `raw_pages/T16_bertopic_docs.html` | 主题建模、意图聚类 |
| T17 | Sentence Transformers | https://sbert.net/ | `raw_pages/T17_sentence_transformers.html` | 文本向量和语义相似 |
| T18 | spaCy 文档 | https://spacy.io/usage | `raw_pages/T18_spacy_docs.html` | NLP 管线、实体/文本处理 |
| T19 | KeyBERT GitHub | https://github.com/MaartenGr/KeyBERT | `raw_pages/T19_keybert_github.html` | 关键词提取 |
| T20 | OpenSearch 文档 | https://docs.opensearch.org/latest/ | `raw_pages/T20_opensearch_docs.html` | 搜索和日志分析 |
| T21 | Meilisearch 文档 | https://www.meilisearch.com/docs | `raw_pages/T21_meilisearch_docs.html` | 轻量搜索引擎 |
| T22 | Hugging Face Transformers | https://huggingface.co/docs/transformers/index | `raw_pages/T22_transformers_docs.html` | 开源模型调用基础库 |
| T23 | vLLM 文档 | https://docs.vllm.ai/en/latest/ | `raw_pages/T23_vllm_docs.html` | 高吞吐 LLM 推理服务 |
| T24 | Ollama GitHub | https://github.com/ollama/ollama | `raw_pages/T24_ollama_github.html` | 本地 LLM 运行 |
| T25 | llama.cpp GitHub | https://github.com/ggml-org/llama.cpp | `raw_pages/T25_llamacpp_github.html` | C/C++ 本地推理 |
| T26 | Qwen GitHub | https://github.com/QwenLM/Qwen3 | `raw_pages/T26_qwen_github.html` | 开权 LLM 候选 |
| T27 | DeepSeek-R1 GitHub | https://github.com/deepseek-ai/DeepSeek-R1 | `raw_pages/T27_deepseek_github.html` | 开权推理模型候选 |
| T28 | Diffusers 文档 | https://huggingface.co/docs/diffusers/index | `raw_pages/T28_diffusers_docs.html` | 图像/视频扩散模型 |
| T29 | ComfyUI GitHub | https://github.com/comfyanonymous/ComfyUI | `raw_pages/T29_comfyui_github.html` | 多模态生成工作流 |
| T30 | Whisper GitHub | https://github.com/openai/whisper | `raw_pages/T30_whisper_github.html` | 语音识别 |
| T31 | Piper GitHub | https://github.com/rhasspy/piper | `raw_pages/T31_piper_github.html` | TTS |
| T32 | n8n 文档 | https://docs.n8n.io/ | `raw_pages/T32_n8n_docs.html` | 自动化工作流；需核查许可证 |
| T33 | Airflow 文档 | https://airflow.apache.org/docs/ | `raw_pages/T33_airflow_docs.html` | 工作流调度 |
| T34 | Temporal 文档 | https://docs.temporal.io/ | `raw_pages/T34_temporal_docs.html` | durable workflow |
| T35 | Langfuse 文档 | https://langfuse.com/docs | `raw_pages/T35_langfuse_docs.html` | LLM observability |
| T36 | promptfoo 文档 | https://www.promptfoo.dev/docs/intro/ | `raw_pages/T36_promptfoo_docs.html` | Prompt/LLM 回归评测 |
| T37 | Ragas 文档 | https://docs.ragas.io/en/stable/ | `raw_pages/T37_ragas_docs.html` | RAG 评估 |
| T38 | OpenTelemetry 文档 | https://opentelemetry.io/docs/ | `raw_pages/T38_opentelemetry_docs.html` | 服务观测 |
| T39 | Metabase 文档 | https://www.metabase.com/docs/latest/ | `raw_pages/T39_metabase_docs.html` | BI 看板 |
| T40 | Superset GitHub | https://github.com/apache/superset | `raw_pages/T40_superset_github.html` | BI/数据可视化 |
| T41 | ClickHouse 文档 | https://clickhouse.com/docs | `raw_pages/T41_clickhouse_docs.html` | 事件分析数据库 |
| T42 | PostHog 文档 | https://posthog.com/docs | `raw_pages/T42_posthog_docs.html` | 产品分析 |
| T43 | FastAPI 文档 | https://fastapi.tiangolo.com/ | `raw_pages/T43_fastapi_docs.html` | 后端 API |
| T44 | Next.js 文档 | https://nextjs.org/docs | `raw_pages/T44_nextjs_docs.html` | 前端框架 |
| T45 | PostgreSQL 文档 | https://www.postgresql.org/docs/current/ | `raw_pages/T45_postgresql_docs.html` | 主数据库 |
| T46 | Redis 文档 | https://redis.io/docs/latest/ | `raw_pages/T46_redis_docs.html` | 缓存/队列；需注意新许可 |
| T47 | GEO 论文 | https://arxiv.org/abs/2311.09735 | `raw_pages/T47_geo_arxiv.html` | GEO 学术定义和优化策略背景 |
| T48 | Schema.org | https://schema.org/docs/documents.html | `raw_pages/T48_schema_org.html` | 结构化数据词汇 |
| T49 | Docker 文档 | https://docs.docker.com/ | `raw_pages/T49_docker_docs.html` | 容器化 |
| T50 | Kubernetes 文档 | https://kubernetes.io/docs/home/ | `raw_pages/T50_kubernetes_docs.html` | 容器编排 |
| T51 | Prometheus 文档 | https://prometheus.io/docs/introduction/overview/ | `raw_pages/T51_prometheus_docs.html` | 指标监控 |
| T52 | Grafana 文档 | https://grafana.com/docs/grafana/latest/ | `raw_pages/T52_grafana_docs.html` | 指标可视化 |
| T53 | Matomo 文档 | https://matomo.org/guide/ | `raw_pages/T53_matomo_docs.html` | 开源 Web analytics |
| T54 | Airbyte 文档 | https://docs.airbyte.com/ | `raw_pages/T54_airbyte_docs.html` | 数据同步/ELT |
| T55 | OSI Open Source AI Definition | https://opensource.org/ai/open-source-ai-definition | `raw_pages/T55_osi_ai_definition.html` | 开源 AI 口径边界 |
| T56 | scikit-learn 文档 | https://scikit-learn.org/stable/user_guide.html | `raw_pages/T56_scikit_learn_docs.html` | 传统机器学习、聚类/分类 |
| T57 | Valkey 文档 | https://valkey.io/docs/ | `raw_pages/T57_valkey_docs.html` | Redis 替代缓存 |
| T58 | Node-RED 文档 | https://nodered.org/docs/ | `raw_pages/T58_node_red_docs.html` | 低代码流程自动化 |
| T59 | Huginn GitHub | https://github.com/huginn/huginn | `raw_pages/T59_huginn_github.html` | 事件监控和自动化代理 |
| T60 | MinIO 文档 | https://min.io/docs/minio/linux/index.html | `raw_pages/T60_minio_docs.html` | 对象存储 |
| T61 | Traefik 文档 | https://doc.traefik.io/traefik/ | `raw_pages/T61_traefik_docs.html` | 网关/反向代理 |
| T62 | Keycloak 文档 | https://www.keycloak.org/documentation | `raw_pages/T62_keycloak_docs.html` | 身份认证与权限 |
| T63 | Wav2Lip GitHub | https://github.com/Rudrabha/Wav2Lip | `raw_pages/T63_wav2lip_github.html` | 数字人口型同步研究项目 |
| T64 | SadTalker GitHub | https://github.com/OpenTalker/SadTalker | `raw_pages/T64_sadtalker_github.html` | 数字人/说话头像研究项目 |
| T65 | Strapi 文档 | https://docs.strapi.io/ | `raw_pages/T65_strapi_docs.html` | Headless CMS |
| T66 | Directus 文档 | https://docs.directus.io/ | `raw_pages/T66_directus_docs.html` | Headless CMS/数据平台 |
| T67 | Google OR-Tools | https://developers.google.com/optimization | `raw_pages/T67_ortools_docs.html` | 信源组合/预算优化求解 |
| T68 | Apache Tika | https://tika.apache.org/ | `raw_pages/T68_apache_tika_docs.html` | 文档解析 |
| T69 | Unstructured 文档 | https://docs.unstructured.io/open-source/introduction/overview | `raw_pages/T69_unstructured_docs.html` | 非结构化文档解析 |

## 对应主报告章节

| 主报告章节 | 主要来源 |
| --- | --- |
| PDF 证据和 GENO 四阶闭环 | T00 |
| AI 平台采集与搜索监控 | T01-T06、T33-T35 |
| 意图分析 | T16-T21、T56 |
| RAG 和知识图谱 | T08-T15、T45、T48、T68-T69 |
| LLM 和多模态生成 | T06、T22-T31、T55 |
| 分发和自动化 | T32-T34、T58-T60、T65-T66 |
| 评分、评测和看板 | T35-T42、T51-T53 |
| SaaS 基建 | T43-T46、T49-T50、T57、T60-T62 |
