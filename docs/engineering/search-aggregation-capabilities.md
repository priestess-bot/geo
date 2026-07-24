# Search Aggregation 原型能力与路线图

> 状态：`PROTOTYPE_ONLY`。本模块是受保护的 Internal API 开发探索能力，
> 不是 B. 连接器与归因或消费者 UI Sampling 的完成证据。
> 最后更新：2026-07-24

---

## 0. 适用边界与阻断项

本原型提供 SerpAPI 和 OpenRouter 的即时查询与结构化展示，方便开发期检查第三方返回的形状。它不创建 Campaign Monitoring Observation，不保存不可变工件，不进入 Customer 投影，也不代表澳大利亚消费者实际看见的页面。

### 0.1 最小可用原型定义

在上述边界内，本模块可用于工程人员以明确的供应商响应验证 parser 的候选实现，或为后续 Surface Release 准备 fixture。它输出的是“第三方 API/模型返回的归一化结果”，而不是对 Google、Bing 或任何消费者 UI 的事实主张。

下列规则是该原型的不可突破边界：

- `ai_overview`、`bing_copilot` 和 OpenRouter/Perplexity 返回必须保留各自来源身份；不得把 SerpAPI、OpenRouter 或模型 API 重命名为消费者浏览器采集。
- `gl`、`hl`、`location`、`google_domain` 仅是上游请求提示，不能记录为 AU egress、澳洲消费者结果或地域验证。
- 普通 Google `answer_box`、featured snippet、knowledge panel 和传统 Bing SERP 不是 AI surface；在没有独立 surface detector 与页面证据前，不能作为 AIO/Copilot 成功案例或 fixture 正例。
- mock、缺失凭据、未授权、空回答、解析失败和上游异常均不是真实成功、有效缺失或可用于验收的样本。
- `/v1/search/*-raw` 仅是尚待治理的诊断面，不能被复制到 Customer、导出、日志、工件或推荐证据；其响应不具有留存许可或脱敏保证。

本文件只冻结产品定位和阻断项，不将现有即时路由提升为 production-ready。正式化必须按下列 checklist 逐项完成并经独立验证。

下列项全部关闭前，任何 `/v1/search/*` 返回都必须保持 `prototype/debug` 定位，不得作为 B 的 Adapter Release、Sampling Attempt、eligible Observation、统计分母、告警输入或 Recommendation 证据：

- [ ] `B-SEARCH-PROTOTYPE-01` 将 SerpAPI 与 OpenRouter 凭据迁入 Secret Store，仅以版本化 Secret Reference 在命令中传递；完成项目范围访问、轮换、撤销和审计。
- [ ] `B-SEARCH-PROTOTYPE-02` 移除生产路径的 mock 成功回退。缺少凭据、授权或真实回答时必须明确失败或产生 ineligible/insufficient-evidence，不得返回伪造 Overview。
- [ ] `B-SEARCH-PROTOTYPE-03` 删除或以受限、脱敏、审计的 artifact viewer 替代 raw 调试接口；不得向 API 返回未分类第三方原始响应。
- [ ] `B-SEARCH-PROTOTYPE-04` 接入 Project/Campaign 角色、预算、速率限制、幂等和模型/供应商调用审计，禁止任意 Internal 身份消耗共享供应商额度。
- [ ] `B-SEARCH-PROTOTYPE-05` 建立 Surface Release、授权 A/B 轨、Browser Profile、澳洲 proxy/gateway sticky lease、pre/target/post egress verification，以及隔离 Browser Worker。`gl`、`hl`、`location` 和 `google_domain` 只是供应商请求参数，不是澳洲出口证明。
- [ ] `B-SEARCH-PROTOTYPE-06` 将执行接入现有 Durable Job、lease/fencing、outbox、MinIO raw-first artifact、Attempt/Observation 及 SourceStratum 合同；重试不得改变 planned denominator。
- [ ] `B-SEARCH-PROTOTYPE-07` 实现 Google AI Mode，并以独立 Surface Release 验收 Google AI Overviews、Google AI Mode、Bing Copilot；SerpAPI/模型 API 不得冒充消费者 UI capture。
- [ ] `B-SEARCH-PROTOTYPE-08` 以冻结的官方 Provider/Grounded API adapter 补齐 OpenAI、Gemini、Perplexity、Microsoft Grounding with Bing 和 Kimi；OpenRouter 代理回答不能替代对应官方 Adapter 的真实 canary。
- [ ] `B-SEARCH-PROTOTYPE-09` 移除将 `answer_box` 回退解释为 AI Overview 的 parser 行为；分别以 AIO、传统 SERP、有效缺失和阻断页面 fixture 验证，传统结果误标必须为 0。

## 1. 已实现原型能力

### 1.1 Google AI Overview

| 项目 | 状态 |
|------|------|
| 结构化 AI 概览 | ✅ 已实现 |
| 原始 SerpAPI 响应（调试） | ✅ 已实现 |
| 地区/语言/域名模拟 | ✅ 已实现 |
| Admin Web 搜索框 | ❌ 已移除（仅保留后端能力） |

**后端接口：**

- `POST /v1/search/google-ai-overview`
- `POST /v1/search/google-raw`

**支持的地区参数：**

- `location`：完整地理位置字符串，如 `New York, NY, United States`
- `gl`：两位国家代码，如 `us`、`uk`、`au`
- `hl`：语言代码，如 `en`、`zh-cn`
- `google_domain`：Google 域名，如 `google.com`、`google.co.uk`

**实现位置：**

- Adapter：`packages/geo_core/geo_core/search_aggregation/serpapi_adapter.py`
- Routes：`apps/api/geo_api/search_aggregation_routes.py`

### 1.2 Bing Copilot

| 项目 | 状态 |
|------|------|
| 结构化 Copilot 回答 | ✅ 已实现 |
| 原始 SerpAPI 响应（调试） | ✅ 已实现 |
| 地区/语言模拟 | ✅ 已实现（通过 SerpAPI `cc`/`setlang`） |
| Admin Web 入口 | ❌ 已移除（仅保留后端能力） |

**后端接口：**

- `POST /v1/search/bing-copilot`
- `POST /v1/search/bing-copilot-raw`

**实现位置：**

- Adapter：`packages/geo_core/geo_core/search_aggregation/serpapi_bing_copilot_adapter.py`
- Routes：`apps/api/geo_api/search_aggregation_routes.py`

### 1.3 OpenRouter OpenAI Web Search

| 项目 | 状态 |
|------|------|
| 结构化 AI 回答 | ✅ 已实现 |
| 原始 OpenRouter 响应（调试） | ✅ 已实现 |
| Admin Web 入口 | ❌ 已移除（仅保留后端能力） |

**后端接口：**

- `POST /v1/search/openrouter-openai-web`
- `POST /v1/search/openrouter-openai-web-raw`

**实现位置：**

- Adapter：`packages/geo_core/geo_core/search_aggregation/openrouter_adapter.py`
- Routes：`apps/api/geo_api/search_aggregation_routes.py`

**命名说明：**

`openrouter_openai_web_search` 代表 **OpenRouter 代理 OpenAI 模型 + OpenRouter `web_search` server tool**。它**不等同于** ChatGPT 网页端 Search，也**不是** OpenAI 官方 Responses API 的 `web_search`。OpenRouter 在这里只是模型/API 网关，网页搜索工具由 OpenRouter 提供。

**环境变量：**

- `GEO_OPENROUTER_API_KEY_FILE`：OpenRouter API key 文件路径，默认 `./openrouter_key.txt`
- `GEO_OPENROUTER_MODEL`：模型名称，默认 `openai/gpt-5.5`
- `GEO_OPENROUTER_HTTP_REFERER`：HTTP-Referer header，默认 `https://geo.local`
- `GEO_OPENROUTER_APP_TITLE`：X-Title header，默认 `GEO Search Demo`

### 1.4 接口认证与 Swagger Authorize

所有 `/v1/search/*` 接口都属于 GEO Internal API 的受保护端点，调用时需要提供开发身份头：

- `X-GEO-Actor-ID`：开发 actor UUID
- `X-GEO-Tenant-ID`：开发 tenant UUID

Swagger 不会持久保存授权信息。开发调试使用 curl、Postman 或已有的 Internal API 认证流程；原型搜索接口不为开发便利改变全局 OpenAPI 安全模型。

**示例 curl：**

```bash
curl -X POST http://localhost:8000/v1/search/google-ai-overview \
  -H "Content-Type: application/json" \
  -H "X-GEO-Actor-ID: 30000000-0000-4000-8000-000000000003" \
  -H "X-GEO-Tenant-ID: 10000000-0000-4000-8000-000000000001" \
  -d '{"query":"除草剂"}'
```

> 注意：这里认证的是 GEO Internal API 的接口访问权限，不是 SerpAPI/OpenRouter 本身。SerpAPI/OpenRouter 只认各自的 API key。

### 1.5 Perplexity via OpenRouter

| 项目 | 状态 |
|------|------|
| 结构化 AI 回答 | ✅ 已实现 |
| 原始 OpenRouter/Perplexity 响应（调试） | ✅ 已实现 |
| Admin Web 入口 | ❌ 已移除（仅保留后端能力） |

**后端接口：**

- `POST /v1/search/perplexity`
- `POST /v1/search/perplexity-raw`

**实现位置：**

- Adapter：`packages/geo_core/geo_core/search_aggregation/perplexity_adapter.py`
- Routes：`apps/api/geo_api/search_aggregation_routes.py`

**实现说明：**

Perplexity 通过 **OpenRouter 代理**接入，复用同一个 OpenRouter API key 和 endpoint。与 OpenAI Web Search 不同，Perplexity 模型**内置联网搜索能力**，调用时不需要传 `tools` 参数。

OpenRouter 上可用的 Perplexity 模型包括 `perplexity/sonar`、`perplexity/sonar-pro`、`perplexity/sonar-pro-search`、`perplexity/sonar-reasoning` 等。默认模型为 `perplexity/sonar`。

**环境变量：**

- `GEO_OPENROUTER_API_KEY_FILE`：OpenRouter API key 文件路径，默认 `./openrouter_key.txt`
- `GEO_PERPLEXITY_MODEL`：Perplexity 模型名称，默认 `perplexity/sonar`
- `GEO_OPENROUTER_HTTP_REFERER`：HTTP-Referer header，默认 `https://geo.local`
- `GEO_OPENROUTER_APP_TITLE`：X-Title header，默认 `GEO Search Demo`

**引用提取：**

Perplexity 通过 OpenRouter 返回的引用位于 `choices[0].message.annotations` 中，格式为 `type: "url_citation"`（与 OpenAI Web Search 一致）。Adapter 会从中去重提取为 `AiOverviewReference`。同时保留对原生 Perplexity API 顶层 `citations` 数组的兼容。

---

## 2. 未实现能力

### 2.1 Brave Search

| 项目 | 状态 |
|------|------|
| 传统搜索排名 | ❌ 未实现 |
| AI 回答（Answer with AI） | ❌ 未实现 |
| Admin Web 入口 | ❌ 未实现 |

**可行性：** Brave 提供官方 Search API，技术集成成本较低。主要价值在于隐私导向的独立搜索索引，可作为传统搜索排名的补充验证。

**当前未做的原因：**

Brave Search API 注册付费账户需要**美国银行卡或 Visa 卡**进行绑定，当前团队暂不具备该条件。

**建议：**

在具备美国银行卡、Visa 卡或找到合规支付方式后，再考虑接入 Brave Search API。其返回的传统搜索排名结构（title、url、description、position）与当前搜索聚合模型兼容，预计集成成本较低。

**优先级：** 中（受支付条件阻塞）

### 2.2 Microsoft Bing Web Search API（官方）

| 项目 | 状态 |
|------|------|
| 传统搜索排名 | ❌ 未实现 |
| Bing Copilot 回答 | ❌ 不通过此 API 提供 |

**说明：** 当前 Bing Copilot 通过 SerpAPI 实现。Microsoft 官方 Bing Web Search API 只返回传统搜索结果，不包含 Copilot AI 回答。如果需要纯 Bing 搜索排名，可单独申请 Azure Bing Search v7 API。

**优先级：** 低（当前 SerpAPI 已覆盖 Bing Copilot）

### 2.3 DuckDuckGo / Yahoo

| 项目 | 状态 |
|------|------|
| 任何搜索能力 | ❌ 未实现 |

**说明：** DuckDuckGo 没有官方 API，只有非官方爬虫/封装，稳定性差、易被封禁。Yahoo 搜索结果主要来自 Bing。两者不建议投入。

**优先级：** 低 / 不考虑

---

## 3. 已解决：Perplexity

| 项目 | 状态 |
|------|------|
| Perplexity API 集成 | ✅ 已通过 OpenRouter 代理实现 |

**说明：**

Perplexity 原本需要直接申请 Perplexity API 并绑定美国银行账户付费。现在改为通过 **OpenRouter 代理**接入后：

- 不需要单独的 Perplexity API 账号
- 不需要美国银行账户
- 计费走 OpenRouter，复用现有 `openrouter_key.txt`
- 返回结构（answer + citations）与现有 `AiOverviewResult` 模型兼容

具体实现见第 1.5 节。原“受支付条件阻塞”问题已解决。

---

## 4. 架构扩展建议

新增搜索引擎时，推荐遵循以下模式：

```text
packages/geo_core/geo_core/search_aggregation/
  ├── ports.py                    # SearchProvider Protocol（不变）
  ├── serpapi_adapter.py          # Google
  ├── serpapi_bing_copilot_adapter.py  # Bing Copilot
  ├── openrouter_adapter.py       # OpenRouter OpenAI Web Search
  └── perplexity_adapter.py       # Perplexity via OpenRouter
```

API 路径规范：

```text
POST /v1/search/{engine}-overview
POST /v1/search/{engine}-raw
```

Admin Web 搜索框已移除，搜索能力仅通过 FastAPI 后端接口提供。

---

## 5. 当前产品定位

Search Aggregation 在 GEO Platform 中的定位是**开发期监测辅助验证原型**：

- 帮助工程人员检查供应商返回的结构和 parser 行为
- 快速确认某个关键词是否收到第三方 API 声称的 AI 回答
- 不模拟、更不证明真实用户搜索环境、消费者 UI、澳洲出口或内容被引用
- 当前不保存查询记录，不进入 Campaign Monitoring 主链，也不产生验收证据

后续只能按第 0 节阻断项接入 B 的受治理采样链；不能将本原型“一键保存”成 `monitoring.query` 后即视为真实追踪。
