# T06 LiteLLM

- URL：https://docs.litellm.ai/docs/
- 本地快照：`raw_pages/T06_litellm_docs.html`
- 类型：LLM API 网关/代理文档。
- 替代能力：统一调用 GPT-4、Claude、Gemini、Qwen、DeepSeek 等模型的网关层。
- 采用理由：GENO PDF 明示“GPT-4 等 LLM”，实际 SaaS 需要多模型路由、成本记录和失败降级。
- 审计备注：LiteLLM 统一的是模型调用层，不解决 AI 搜索页面采集和引用解析问题。
