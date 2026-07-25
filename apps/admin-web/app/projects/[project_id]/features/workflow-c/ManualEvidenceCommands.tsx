"use client";

import { useActionState, useState } from "react";

import {
  approveManualEvidenceAction,
  importManualEvidenceAction,
  rejectManualEvidenceAction
} from "./samplingActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  initialWorkflowCActionState,
  type ManualEvidenceImport,
  type SamplingSourceStratum,
  type SamplingTask,
  type SurfaceParserRelease,
  type SurfaceParseSummary
} from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export function ManualEvidenceCommands({
  actorId,
  canOperate,
  canReview,
  capturedAt,
  commandKey,
  imports,
  projectId,
  releases,
  runId,
  source,
  tasks
}: {
  actorId: string;
  canOperate: boolean;
  canReview: boolean;
  capturedAt: string;
  commandKey: string;
  imports: ManualEvidenceImport[];
  projectId: string;
  releases: SurfaceParserRelease[];
  runId: string | null;
  source: SamplingSourceStratum | null;
  tasks: SamplingTask[];
}) {
  const [importState, importAction, importPending] = useActionState(importManualEvidenceAction, initialWorkflowCActionState);
  const [approveState, approveAction, approvePending] = useActionState(approveManualEvidenceAction, initialWorkflowCActionState);
  const [rejectState, rejectAction, rejectPending] = useActionState(rejectManualEvidenceAction, initialWorkflowCActionState);
  const manualTasks = tasks.filter((task) => task.capture_method === "manual_ui" && task.status === "planned");
  const pending = imports.filter((item) => item.status === "pending_review");
  const uploadDisabled = !canOperate || importPending || !runId || !manualTasks.length;
  const matchingReleases = source?.capture_method === "manual_ui"
    ? releases.filter((release) => releaseMatchesSource(release, source))
    : [];
  const [parserReleaseId, setParserReleaseId] = useState("");
  const [evidenceKind, setEvidenceKind] = useState("screenshot");

  return (
    <section className={styles.commandBand} aria-labelledby="manual-evidence-heading">
      <div className={styles.sectionHeading}>
        <div><p>受治理导入</p><h3 id="manual-evidence-heading">手工 UI 证据</h3></div>
        <span>{pending.length} 条待复核</span>
      </div>
      <div className={styles.scopeNotice} data-tone="warning">
        <strong>测试夹具 / 手工解析器</strong>
        <span>非实时证据 · 不具备澳大利亚出口证明</span>
      </div>
      <form action={importAction} className={styles.commandForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="run_id" type="hidden" value={runId || ""} />
        <input name="idempotency_key" type="hidden" value={`${commandKey}-import`} />
        <label><span>待采集任务</span><select disabled={uploadDisabled} name="task_ref" required><option value="">选择任务</option>{manualTasks.map((task) => <option key={task.id} value={`${task.id}:${task.version}`}>{task.question_id} · 第 {task.repetition} 次重复</option>)}</select></label>
        <label><span>页面解析器发布版本</span><select disabled={uploadDisabled || !matchingReleases.length} name="surface_parser_release_id" onChange={(event) => { const value = event.currentTarget.value; setParserReleaseId(value); if (value) setEvidenceKind("transcript_export"); }} title="仅用于测试夹具或受治理的人工文本解析；不能证明实时采集或出口来源。" value={parserReleaseId}><option value="">通用人工证据（不解析页面类型）</option>{matchingReleases.map((release) => <option key={release.id} value={release.id}>{surfaceLabel(release.surface)} · {release.release_version}</option>)}</select></label>
        <label><span>证据类型</span><select disabled={uploadDisabled} name="evidence_kind" onChange={(event) => { const value = event.currentTarget.value; setEvidenceKind(value); if (value !== "transcript_export") setParserReleaseId(""); }} value={evidenceKind}><option value="screenshot">截图</option><option value="html_export">HTML 导出</option><option value="transcript_export">文本记录导出</option></select></label>
        <label><span>文件</span><input accept={parserReleaseId ? "application/json,.json" : ".html,.htm,.json,.txt,image/jpeg,image/png,image/webp"} disabled={uploadDisabled} name="artifact" required type="file" /></label>
        <label><span>截图已脱敏</span><input disabled={uploadDisabled} name="pre_redacted_attestation" type="checkbox" /></label>
        <label><span>设备</span><select disabled={uploadDisabled} name="device"><option value="desktop">桌面端</option><option value="mobile">移动端</option><option value="tablet">平板设备</option></select></label>
        <label><span>区域语言</span><input defaultValue="en-AU" disabled={uploadDisabled} maxLength={100} name="locale" required /></label>
        <label><span>采集时间</span><input defaultValue={capturedAt} disabled={uploadDisabled} name="captured_at" required type="datetime-local" /></label>
        <button disabled={uploadDisabled} type="submit">{importPending ? "导入中..." : "导入并提交复核"}</button>
      </form>
      <WorkflowCActionFeedback state={importState} />

      {pending.map((item) => {
        const makerCannotReview = item.submitted_by === actorId;
        const reviewDisabled = !canReview || makerCannotReview;
        return (
          <article className={styles.reviewItem} key={item.id}>
            {item.surface_parse ? <ParseSummary summary={item.surface_parse} /> : null}
            <div className={styles.commandGrid}>
              <form action={approveAction} className={styles.commandForm}>
                <ReviewIdentity commandKey={`${commandKey}-approve-${item.id}`} item={item} projectId={projectId} />
                <strong>{item.evidence_kind} · {item.locale}</strong>
                <code>{item.artifact_manifest_hash}</code>
                <label><span>批准原因</span><input disabled={reviewDisabled || approvePending} maxLength={1000} name="reason" required /></label>
                <button disabled={reviewDisabled || approvePending} type="submit">批准并入队</button>
              </form>
              <form action={rejectAction} className={styles.commandForm}>
                <ReviewIdentity commandKey={`${commandKey}-reject-${item.id}`} item={item} projectId={projectId} />
                <strong>{item.submitted_by}</strong>
                <code>{item.artifact_content_hash}</code>
                <label><span>拒绝原因</span><input disabled={reviewDisabled || rejectPending} maxLength={1000} name="reason" required /></label>
                <button disabled={reviewDisabled || rejectPending} type="submit">拒绝</button>
              </form>
            </div>
          </article>
        );
      })}
      <WorkflowCActionFeedback state={approveState} />
      <WorkflowCActionFeedback state={rejectState} />
    </section>
  );
}

function ParseSummary({ summary }: { summary: SurfaceParseSummary }) {
  return (
    <div className={styles.parseSummary}>
      <div className={styles.badgeRow}>
        <span>{surfaceLabel(summary.surface)}</span>
        <span>{summary.capture_kind}</span>
        <span>非实时</span>
        <span data-status={summary.content_eligible ? "eligible" : "blocked"}>{summary.outcome}</span>
      </div>
      <dl>
        <div><dt>回答字符数</dt><dd>{summary.answer_character_count}</dd></div>
        <div><dt>引用数</dt><dd>{summary.citation_count}</dd></div>
        <div><dt>阻断原因</dt><dd>{summary.block_reason || "-"}</dd></div>
        <div><dt>发布版本 SHA-256</dt><dd><code>{summary.parser_release_hash}</code></dd></div>
        <div><dt>摘要 SHA-256</dt><dd><code>{summary.summary_hash}</code></dd></div>
      </dl>
    </div>
  );
}

function releaseMatchesSource(
  release: SurfaceParserRelease,
  source: SamplingSourceStratum
): boolean {
  const platform = source.platform.trim().toLowerCase().replaceAll("-", "_");
  const surface = source.surface.trim().toLowerCase().replaceAll("-", "_");
  if (surface === release.surface || platform === release.surface) return true;
  const aliases: Record<SurfaceParserRelease["surface"], string[]> = {
    google_ai_overviews: ["google:ai_overviews", "google_search:ai_overviews"],
    google_ai_mode: ["google:ai_mode", "google_search:ai_mode"],
    bing_copilot: ["bing:copilot", "bing_search:copilot"]
  };
  return aliases[release.surface].includes(`${platform}:${surface}`);
}

function surfaceLabel(surface: SurfaceParserRelease["surface"]): string {
  return {
    google_ai_overviews: "Google AI Overviews",
    google_ai_mode: "Google AI Mode",
    bing_copilot: "Bing Copilot"
  }[surface];
}

function ReviewIdentity({ commandKey, item, projectId }: { commandKey: string; item: ManualEvidenceImport; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="import_id" type="hidden" value={item.id} /><input name="expected_version" type="hidden" value={item.aggregate_version} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}
