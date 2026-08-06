import type {
  CampaignView,
  KnowledgeQuestionCandidateView,
  KnowledgeQuestionFactView,
  KnowledgeQuestionGenerationView,
  KnowledgeQuestionSetView,
  MonitoringProtocolView
} from "@geo/types/geo";
import type { RuntimeHttpResult } from "@geo/api-client/transport";

import { geoClient } from "../../geo/client";
import {
  emptyResource,
  type Resource
} from "../../geo/features/geo/model";

export const questionSteps = ["generate", "review", "sets"] as const;
export type QuestionStep = (typeof questionSteps)[number];

export type QuestionWorkspaceSelection = Readonly<{
  campaignId?: string;
  questionGenerationJobId?: string;
  questionStep?: QuestionStep;
}>;

export type QuestionWorkspaceData = Readonly<{
  selection: QuestionWorkspaceSelection;
  campaigns: Resource<CampaignView[]>;
  protocols: Resource<MonitoringProtocolView[]>;
  questionFacts: Resource<KnowledgeQuestionFactView[]>;
  questionGenerations: Resource<KnowledgeQuestionGenerationView[]>;
  questionCandidates: Resource<KnowledgeQuestionCandidateView[]>;
  questionSets: Resource<KnowledgeQuestionSetView[]>;
}>;

export async function loadQuestionWorkspace(
  projectId: string,
  requested: QuestionWorkspaceSelection
): Promise<QuestionWorkspaceData> {
  const client = await geoClient();
  const [campaignResult, factResult] = await Promise.all([
    client.listCampaigns(projectId),
    client.listKnowledgeQuestionFacts(projectId)
  ]);
  const campaigns = resource(campaignResult, []);
  const questionFacts = resource(factResult, []);
  const activeCampaigns = campaigns.data.filter((item) => item.status === "active");
  const requestedCampaign = requested.campaignId
    ? campaigns.data.find((item) => item.id === requested.campaignId)
    : undefined;
  const campaignId = requestedCampaign?.id
    || (!requested.campaignId && activeCampaigns.length === 1 ? activeCampaigns[0]?.id : undefined);

  if (!campaignId) {
    return {
      selection: {},
      campaigns,
      protocols: emptyResource([]),
      questionFacts,
      questionGenerations: emptyResource([]),
      questionCandidates: emptyResource([]),
      questionSets: emptyResource([])
    };
  }

  const [protocolResult, generationResult, setResult] = await Promise.all([
    client.listProtocols(projectId, campaignId),
    client.listKnowledgeQuestionGenerations(projectId, campaignId),
    client.listKnowledgeQuestionSets(projectId, campaignId)
  ]);
  const protocols = resource(protocolResult, []);
  const questionGenerations = resource(generationResult, []);
  const questionSets = resource(setResult, []);
  const requestedJob = requested.questionGenerationJobId
    ? questionGenerations.data.find((item) => item.job_id === requested.questionGenerationJobId)
    : undefined;
  const questionGenerationJobId = requestedJob?.job_id
    || (!requested.questionGenerationJobId ? questionGenerations.data[0]?.job_id : undefined);
  const questionCandidates = questionGenerationJobId
    ? resource(
      await client.listKnowledgeQuestionCandidates(
        projectId,
        campaignId,
        questionGenerationJobId
      ),
      []
    )
    : emptyResource<KnowledgeQuestionCandidateView[]>([]);

  return {
    selection: {
      campaignId,
      ...(questionGenerationJobId ? { questionGenerationJobId } : {}),
      ...(requested.questionStep ? { questionStep: requested.questionStep } : {})
    },
    campaigns,
    protocols,
    questionFacts,
    questionGenerations,
    questionCandidates,
    questionSets
  };
}

function resource<T>(result: RuntimeHttpResult<T>, fallback: T): Resource<T> {
  if (result.ok) return emptyResource(result.data);
  return {
    data: fallback,
    failure: {
      status: result.status,
      code: result.error.code,
      detail: result.error.detail,
      correlationId: result.error.correlation_id || result.response.correlationId,
      retryable: result.error.retryable === true || !result.status || result.status >= 500
    }
  };
}
