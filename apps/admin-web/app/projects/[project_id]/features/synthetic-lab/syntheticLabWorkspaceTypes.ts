import type {
  CollectionAuthorization,
  DirectGenerationOptions,
  ManualImportPreview,
  ManualImportPreviewSummary,
  ReviewCase,
  ReviewSuite,
  StyleLoginSecretReference,
  StyleProfile,
  StyleSource,
  SyntheticJob,
  SyntheticLabView,
  SyntheticLoadProblem,
  SyntheticPage,
  SyntheticResourceInventory,
  SyntheticReviewResult,
  SyntheticRuntimeOptions
} from "./syntheticLabTypes";

export type SyntheticWorkspaceData = Readonly<{
  currentView: SyntheticLabView;
  generationDefaults: Readonly<{
    caseId: string | null;
    runtimeId: string | null;
    stylePassThreshold: number;
  }>;
  directOptions: DirectGenerationOptions;
  directOptionsProblem?: SyntheticLoadProblem;
  jobPage: number;
  authorizations: SyntheticPage<CollectionAuthorization>;
  authorizationsProblem?: SyntheticLoadProblem;
  sources: SyntheticPage<StyleSource>;
  sourcesProblem?: SyntheticLoadProblem;
  importPreviews: SyntheticPage<ManualImportPreviewSummary>;
  importPreviewsProblem?: SyntheticLoadProblem;
  selectedImportPreview: ManualImportPreview | null;
  importPreviewProblem?: SyntheticLoadProblem;
  inventory: SyntheticResourceInventory;
  inventoryProblem?: SyntheticLoadProblem;
  runtimeOptions: SyntheticRuntimeOptions;
  runtimeOptionsProblem?: SyntheticLoadProblem;
  loginSecrets: StyleLoginSecretReference[];
  loginSecretsProblem?: SyntheticLoadProblem;
  profiles: SyntheticPage<StyleProfile>;
  profilesProblem?: SyntheticLoadProblem;
  suites: SyntheticPage<ReviewSuite>;
  suitesProblem?: SyntheticLoadProblem;
  selectedSuiteId: string | null;
  selectedCases: SyntheticPage<ReviewCase>;
  casesProblem?: SyntheticLoadProblem;
  jobs: SyntheticPage<SyntheticJob>;
  jobsProblem?: SyntheticLoadProblem;
  selectedJob: SyntheticJob | null;
  jobProblem?: SyntheticLoadProblem;
  selectedResult: SyntheticReviewResult | null;
  resultProblem?: SyntheticLoadProblem;
}>;
