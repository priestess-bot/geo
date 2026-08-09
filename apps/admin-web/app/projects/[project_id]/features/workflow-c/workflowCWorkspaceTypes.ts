import type { QuestionStep, QuestionWorkspaceData } from "./questionWorkspaceData";
import type {
  AdmissionPolicyPage,
  AdmissionRuntimeOptionPage,
  AlertPage,
  BrowserCaptureInventory,
  BrowserCaptureReadiness,
  ComparisonFamily,
  ComparisonFamilyPage,
  DriftReport,
  DriftReportPage,
  ManualEvidenceImportPage,
  NotificationProjection,
  Resource,
  SamplingRun,
  SamplingRunDetail,
  SamplingRunPage,
  SamplingSuite,
  SamplingSuiteInputOptionPage,
  SamplingSuitePage,
  SemanticMetricSnapshot,
  SemanticMetricSnapshotPage,
  SurfaceParserReleasePage,
  WorkflowView
} from "./workflowCTypes";
import type {
  MetricProtocolPage,
  StatisticalProtocolPage,
  WorkflowCReportPage
} from "./workflowCControlTypes";

export type WorkflowCWorkspaceData = Readonly<{
  actorId: string;
  currentIdentityId: string | null;
  currentRole: "owner" | "admin" | "analyst" | "viewer" | null;
  activeView: WorkflowView;
  selection: Readonly<{
    embedded: boolean;
    suiteId?: string;
    runId?: string;
    snapshotHash?: string;
    familyHash?: string;
    driftHash?: string;
    alertId?: string;
    policyId?: string;
    campaignId?: string;
    questionGenerationJobId?: string;
    questionStep?: QuestionStep;
  }>;
  questionWorkspace: QuestionWorkspaceData | null;
  suite: Resource<SamplingSuite>;
  run: Resource<SamplingRunDetail>;
  metrics: Resource<SemanticMetricSnapshot>;
  metricSnapshots: Resource<SemanticMetricSnapshotPage>;
  metricProtocols: Resource<MetricProtocolPage>;
  statisticalProtocols: Resource<StatisticalProtocolPage>;
  comparisons: Resource<ComparisonFamily>;
  comparisonFamilies: Resource<ComparisonFamilyPage>;
  drift: Resource<DriftReport>;
  driftReports: Resource<DriftReportPage>;
  alerts: Resource<AlertPage>;
  admissionPolicies: Resource<AdmissionPolicyPage>;
  admissionRuntimeOptions: Resource<AdmissionRuntimeOptionPage>;
  suiteInputOptions: Resource<SamplingSuiteInputOptionPage>;
  suites: Resource<SamplingSuitePage>;
  runs: Resource<SamplingRunPage>;
  manualEvidence: Resource<ManualEvidenceImportPage>;
  surfaceParserReleases: Resource<SurfaceParserReleasePage>;
  browserCaptureReadiness: Resource<BrowserCaptureReadiness>;
  browserCaptureInventory: Resource<BrowserCaptureInventory>;
  workflowCReports: Resource<WorkflowCReportPage>;
  notifications: Resource<NotificationProjection[]>;
}>;
