export const PROMPT_TASK_KEYS = [
  "owned_site", "productreview", "youtube", "reddit", "amazon",
  "ozbargain", "tiktok", "instagram", "quora"
] as const;

export const DEFAULT_OUTPUT_SCHEMA = JSON.stringify({
  type: "object",
  additionalProperties: false,
  required: ["content_json", "rendered_text", "claims", "internal_evidence_refs", "public_citation_refs"],
  properties: {
    content_json: { type: "object" },
    rendered_text: { type: "string" },
    claims: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["text", "kind", "support_status", "evidence_item_ids"],
        properties: {
          text: { type: "string" },
          kind: { type: "string", enum: ["factual", "comparative", "experience", "non_factual"] },
          support_status: { type: "string", enum: ["supported", "unsupported", "conflict", "not_required"] },
          evidence_item_ids: { type: "array", items: { type: "string", format: "uuid" } }
        }
      }
    },
    internal_evidence_refs: { type: "array", items: { type: "string", format: "uuid" } },
    public_citation_refs: { type: "array", items: { type: "string", format: "uuid" } }
  }
}, null, 2);
