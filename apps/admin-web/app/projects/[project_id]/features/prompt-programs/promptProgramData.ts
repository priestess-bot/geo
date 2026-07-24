import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isPromptBootstrapCatalog,
  type PromptBootstrapCatalog
} from "./promptBootstrapTypes";
import {
  isPromptProgramBindingOptionPage,
  isPromptProgramPage,
  isPromptProgramSummary,
  isPromptReleasePage,
  isPromptTestRuntimeOptionPage,
  type PromptLoadProblem,
  type PromptProgramBindingOptionPage,
  type PromptProgramPage,
  type PromptProgramSummary,
  type PromptReleasePage,
  type PromptTestRuntimeOptionPage,
  type PromptWorkspaceData
} from "./promptProgramTypes";

type SearchParams = { [key: string]: string | string[] | undefined };

const PROGRAM_PAGE_SIZE = 12;
const RELEASE_PAGE_SIZE = 200;
const emptyPrograms: PromptProgramPage = {
  items: [],
  total: 0,
  limit: PROGRAM_PAGE_SIZE,
  offset: 0
};
const emptyReleases: PromptReleasePage = {
  items: [],
  total: 0,
  limit: RELEASE_PAGE_SIZE,
  offset: 0
};
const emptyBindings: PromptProgramBindingOptionPage = {
  items: [],
  total: 0,
  limit: 200,
  offset: 0
};

export async function loadPromptWorkspace(
  projectId: string,
  query: SearchParams
): Promise<PromptWorkspaceData> {
  const page = positivePage(queryValue(query, "prompt_page"));
  const offset = (page - 1) * PROGRAM_PAGE_SIZE;
  const base = `/v1/projects/${encodeURIComponent(projectId)}/prompt-programs`;
  const bootstrapBase = `/v1/projects/${encodeURIComponent(projectId)}/prompt-bootstrap`;
  const runtimesBase = `/v1/projects/${encodeURIComponent(projectId)}/prompt-program-test-options`;
  const bindingsBase = `/v1/projects/${encodeURIComponent(projectId)}/prompt-program-bindings`;
  let [programsResponse, bootstrapResponse, runtimesResponse, bindingsResponse] = await Promise.all([
    runtimeRequest<PromptProgramPage>(base, {
      query: { limit: PROGRAM_PAGE_SIZE, offset }
    }),
    runtimeRequest<PromptBootstrapCatalog>(bootstrapBase),
    runtimeRequest<PromptTestRuntimeOptionPage>(runtimesBase),
    runtimeRequest<PromptProgramBindingOptionPage>(bindingsBase, {
      query: { limit: 200, offset: 0 }
    })
  ]);
  const bootstrap = bootstrapProjection(bootstrapResponse, query);
  const runtimes = runtimeProjection(runtimesResponse);
  const bindings = bindingProjection(bindingsResponse);
  if (
    programsResponse.ok
    && isPromptProgramPage(programsResponse.data)
    && programsResponse.data.total > 0
    && programsResponse.data.items.length === 0
    && offset > 0
  ) {
    const lastOffset = Math.floor((programsResponse.data.total - 1) / PROGRAM_PAGE_SIZE)
      * PROGRAM_PAGE_SIZE;
    programsResponse = await runtimeRequest<PromptProgramPage>(base, {
      query: { limit: PROGRAM_PAGE_SIZE, offset: lastOffset }
    });
  }
  if (!programsResponse.ok || !isPromptProgramPage(programsResponse.data)) {
    return {
      ...bootstrap,
      ...runtimes,
      ...bindings,
      programs: { ...emptyPrograms, offset },
      programsProblem: loadProblem(programsResponse, "Prompt Program 列表加载失败。"),
      releases: emptyReleases,
      selectedProgram: null,
      selectedRelease: null
    };
  }

  const programs = programsResponse.data;
  const requestedProgramId = queryValue(query, "prompt_program_id");
  let selectedProgram = requestedProgramId
    ? programs.items.find((item) => item.id === requestedProgramId) || null
    : programs.items[0] || null;
  let releasesResponse: RuntimeResult<PromptReleasePage> | null = null;
  let selectedProblem: PromptLoadProblem | undefined;

  if (requestedProgramId && !selectedProgram) {
    const [programResponse, response] = await Promise.all([
      runtimeRequest<PromptProgramSummary>(
        `${base}/${encodeURIComponent(requestedProgramId)}`
      ),
      loadReleases(base, requestedProgramId)
    ]);
    releasesResponse = response;
    if (programResponse.ok && isPromptProgramSummary(programResponse.data)) {
      selectedProgram = programResponse.data;
    } else {
      selectedProblem = loadProblem(programResponse, "所选 Prompt Program 加载失败。");
    }
  } else if (selectedProgram) {
    releasesResponse = await loadReleases(base, selectedProgram.id);
  }

  if (!selectedProgram) {
    return {
      ...bootstrap,
      ...runtimes,
      ...bindings,
      programs,
      releases: emptyReleases,
      ...(selectedProblem ? { releasesProblem: selectedProblem } : {}),
      selectedProgram: null,
      selectedRelease: null
    };
  }
  if (!releasesResponse?.ok || !isPromptReleasePage(releasesResponse.data)) {
    return {
      ...bootstrap,
      ...runtimes,
      ...bindings,
      programs,
      releases: emptyReleases,
      releasesProblem: selectedProblem
        || loadProblem(releasesResponse, "Prompt Release 列表加载失败。"),
      selectedProgram,
      selectedRelease: null
    };
  }

  const releases = releasesResponse.data;
  const requestedReleaseId = queryValue(query, "prompt_release_id");
  const selectedRelease = requestedReleaseId
    ? releases.items.find((item) => item.id === requestedReleaseId) || null
    : releases.items[0] || null;
  return {
    ...bootstrap,
    ...runtimes,
    ...bindings,
    programs,
    releases,
    ...(selectedProblem ? { releasesProblem: selectedProblem } : {}),
    selectedProgram,
    selectedRelease
  };
}

function bindingProjection(
  response: RuntimeResult<PromptProgramBindingOptionPage>
): Pick<PromptWorkspaceData, "bindings" | "bindingsProblem"> {
  if (!response.ok || !isPromptProgramBindingOptionPage(response.data)) {
    return {
      bindings: emptyBindings,
      bindingsProblem: loadProblem(response, "当前 Prompt Binding 目录加载失败。")
    };
  }
  return { bindings: response.data };
}

function runtimeProjection(
  response: RuntimeResult<PromptTestRuntimeOptionPage>
): Pick<PromptWorkspaceData, "testRuntimes" | "testRuntimesProblem"> {
  if (!response.ok || !isPromptTestRuntimeOptionPage(response.data)) {
    return {
      testRuntimes: [],
      testRuntimesProblem: loadProblem(response, "已批准 Prompt 测试运行时目录加载失败。")
    };
  }
  return { testRuntimes: response.data.items };
}

function bootstrapProjection(
  response: RuntimeResult<PromptBootstrapCatalog>,
  query: SearchParams
): Pick<PromptWorkspaceData, "bootstrap" | "bootstrapProblem" | "selectedBootstrapKind"> {
  if (!response.ok || !isPromptBootstrapCatalog(response.data)) {
    return {
      bootstrap: null,
      bootstrapProblem: loadProblem(response, "Prompt 基线目录加载失败。"),
      selectedBootstrapKind: null
    };
  }
  const requested = queryValue(query, "prompt_bootstrap_kind");
  const selected = response.data.items.find((item) => item.program_kind === requested)
    || response.data.items[0]
    || null;
  return {
    bootstrap: response.data,
    selectedBootstrapKind: selected?.program_kind || null
  };
}

function loadReleases(
  base: string,
  programId: string
): Promise<RuntimeResult<PromptReleasePage>> {
  return runtimeRequest<PromptReleasePage>(
    `${base}/${encodeURIComponent(programId)}/releases`,
    { query: { limit: RELEASE_PAGE_SIZE, offset: 0 } }
  );
}

function loadProblem(
  response: RuntimeResult<unknown> | null,
  fallback: string
): PromptLoadProblem {
  if (!response) return { status: 502, detail: fallback };
  if (!response.ok) {
    return {
      ...(response.status === undefined ? {} : { status: response.status }),
      detail: response.error || fallback,
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  return {
    status: 502,
    detail: "Prompt Program 接口返回了无法识别的响应。",
    ...(response.response.correlationId
      ? { correlationId: response.response.correlationId }
      : {})
  };
}

function positivePage(value: string | undefined): number {
  const parsed = Number(value || "1");
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1;
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
