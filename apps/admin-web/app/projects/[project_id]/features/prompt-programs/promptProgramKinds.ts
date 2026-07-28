export const primaryPromptProgramKinds = [
  "generation",
  "claim_extraction",
  "conflict_check",
  "revision",
  "style_judge",
  "arbiter",
  "metric_judge",
  "recommendation"
] as const;

export const auxiliaryPromptProgramKinds = [
  "style_profile",
  "offline_answer"
] as const;

export const workflowPromptProgramKinds = [
  "question_generation",
  "rag_grounding",
  "placement_generation",
  "placement_simulation"
] as const;

export const difyWorkflowPurposes = [
  "knowledge.question_generation",
  "knowledge.rag_grounding",
  "placements.generation",
  "placements.simulation",
  "synthetic_lab.generation",
  "synthetic_lab.claim_extraction",
  "synthetic_lab.conflict_check",
  "synthetic_lab.revision",
  "synthetic_lab.style_profile",
  "recommendations.recommendation"
] as const;

export const difyManagedPromptProgramKinds = [
  ...workflowPromptProgramKinds,
  "generation",
  "claim_extraction",
  "conflict_check",
  "revision",
  "style_profile",
  "recommendation"
] as const;

export const nativeReviewPromptProgramKinds = [
  "style_judge",
  "arbiter",
  "metric_judge",
  "offline_answer"
] as const;

export const reservedPromptProgramKinds = [
  "reference_translation"
] as const;

export const promptProgramKinds = [
  ...primaryPromptProgramKinds,
  ...auxiliaryPromptProgramKinds,
  ...workflowPromptProgramKinds
] as const;
