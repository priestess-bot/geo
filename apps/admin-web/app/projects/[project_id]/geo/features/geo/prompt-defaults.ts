export const PROMPT_TASK_KEYS = [
  "owned_site", "productreview", "youtube", "reddit", "amazon",
  "ozbargain", "tiktok", "instagram", "quora"
] as const;

export const DEFAULT_SYSTEM_PROMPT = [
  "You create source-grounded GEO placement content for an authorised operator.",
  "Keep brand relationships explicit and follow the frozen destination policy."
].join(" ");

export const DEFAULT_USER_PROMPT = [
  "Create publication-ready content for the selected destination.",
  "Brief:\n{{ brief }}",
  "Destination policy:\n{{ destination_policy }}",
  "Evidence:\n{{ evidence }}",
  "Use only supplied evidence and return the frozen output schema."
].join("\n\n");

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
          support_status: { type: "string", enum: ["supported", "unsupported", "not_applicable"] },
          evidence_item_ids: { type: "array", items: { type: "string", format: "uuid" } }
        }
      }
    },
    internal_evidence_refs: { type: "array", items: { type: "string", format: "uuid" } },
    public_citation_refs: { type: "array", items: { type: "string", format: "uuid" } }
  }
}, null, 2);
