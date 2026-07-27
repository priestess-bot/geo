import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isDifyWorkflowRuntimePage,
  type DifyWorkflowRuntimePage,
  type PromptLoadProblem,
  type PromptWorkspaceData
} from "./promptProgramTypes";

type SearchParams = { [key: string]: string | string[] | undefined };

const emptyWorkflowRuntimes: DifyWorkflowRuntimePage = {
  runtime_backend: "native",
  items: [],
  total: 0
};

export async function loadPromptWorkspace(
  projectId: string,
  _query: SearchParams
): Promise<PromptWorkspaceData> {
  const response = await runtimeRequest<DifyWorkflowRuntimePage>(
    `/v1/projects/${encodeURIComponent(projectId)}/dify-workflows`
  );
  const valid = response.ok && isDifyWorkflowRuntimePage(response.data);
  return {
    flows: { items: [], total: 0 },
    selectedFlow: null,
    selectedReleaseDetail: null,
    testRuns: { items: [], total: 0 },
    bootstrap: null,
    selectedBootstrapKind: null,
    testRuntimes: [],
    workflowRuntimes: valid ? response.data : emptyWorkflowRuntimes,
    ...(!valid ? {
      workflowRuntimesProblem: loadProblem(response, "Dify 工作流状态加载失败。")
    } : {}),
    bindings: { items: [], total: 0, limit: 200, offset: 0 },
    programs: { items: [], total: 0, limit: 200, offset: 0 },
    releases: { items: [], total: 0, limit: 200, offset: 0 },
    selectedProgram: null,
    selectedRelease: null
  };
}

function loadProblem(
  response: RuntimeResult<unknown>,
  fallback: string
): PromptLoadProblem {
  if (!response.ok) {
    return {
      ...(response.status === undefined ? {} : { status: response.status }),
      detail: response.error || fallback,
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  return { status: 502, detail: fallback };
}
