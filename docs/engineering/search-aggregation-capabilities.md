# Search Aggregation 能力现状与路线图

> 本文档记录 GEO Platform 当前支持的搜索引擎/AI 搜索聚合能力，以及后续可扩展方向。
> 最后更新：2026-07-23

---

## 1. 已实现能力

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

本地开发模式下，Swagger UI（`/docs`）顶部会出现 **Authorize** 按钮。填入上面两个 UUID 后，Swagger 会自动为每个请求带上对应 header，并且配置会持久保存（通过 `swagger_ui_parameters={"persistAuthorization": True}` 实现）。

这个 Swagger Authorize 入口是在 `3c2d3d4`（接入 OpenRouter OpenAI Web Search）时加入的，目的是方便本地调试。在此之前，调用搜索接口需要通过 curl/Postman 等方式手动添加两个 header。

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

Search Aggregation 在 GEO Platform 中的定位是**监测辅助验证入口**：

- 帮助运营/投放人员模拟真实用户搜索环境
- 快速查看某个关键词下，Google/Bing 是否返回 AI 回答
- 验证我们投放/发布的内容是否被搜索引擎或 AI 引用
- 当前不保存查询记录，不进入 Campaign Monitoring 主链

未来如需系统化追踪，可考虑把查询一键保存为 `monitoring.query`，由后台定期复测。
