import type { PublicationVerificationAttemptView } from "@geo/types/geo";
import { geoClient } from "../../client";
import { emptyResource, type Resource } from "./model";

export async function loadPublicationVerificationAttempts(
  projectId: string, campaignId: string, submissionId?: string
): Promise<Resource<PublicationVerificationAttemptView[]>> {
  if (!campaignId || !submissionId) return emptyResource([]);
  const result = await (await geoClient()).listSubmissionVerificationAttempts(
    projectId, campaignId, submissionId
  );
  if (result.ok) return emptyResource(result.data);
  return {
    data: [],
    failure: {
      status: result.status,
      code: result.error.code,
      detail: result.error.detail,
      correlationId: result.error.correlation_id || result.response.correlationId,
      retryable: result.error.retryable === true || !result.status || result.status >= 500
    }
  };
}
