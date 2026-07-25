"use client";

import { useActionState, useState } from "react";

import {
  admitStyleCollectionAction,
  cancelSyntheticJobAction,
  enqueueApprovedCorpusAction,
  enqueueCandidateCorpusAction,
  enqueueOfflineExperimentAction,
  enqueueReviewCaseRunAction,
  enqueueStyleProfileBuildAction
} from "./syntheticLabJobActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import {
  initialSyntheticActionState,
  type CollectionAuthorization,
  type ReviewCase,
  type ReviewSuite,
  type StyleLoginSecretReference,
  type StyleProfile,
  type StyleSource,
  type SyntheticJob,
  type SyntheticResourceInventory,
  type SyntheticRuntimeOption
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

const PROFILE_PURPOSE = "synthetic_lab.style_profile";
const OFFLINE_PURPOSE = "synthetic_lab.offline_answer";
const REVIEW_PURPOSES = [
  "synthetic_lab.generation",
  "synthetic_lab.claim_extraction",
  "synthetic_lab.conflict_check",
  "synthetic_lab.revision",
  "synthetic_lab.style_judge",
  "synthetic_lab.arbiter"
] as const;

export function StyleProfileBuildForm({
  canContribute,
  commandKey,
  inventory,
  profile,
  projectId,
  runtimes
}: {
  canContribute: boolean;
  commandKey: string;
  inventory: SyntheticResourceInventory;
  profile: StyleProfile;
  projectId: string;
  runtimes: SyntheticRuntimeOption[];
}) {
  const [state, action, pending] = useActionState(
    enqueueStyleProfileBuildAction, initialSyntheticActionState
  );
  const facts = inventory.fact_snapshots.filter((item) => item.status === "ready");
  const eligibleRuntimes = runtimes.filter((item) => item.capture_method === "provider_api"
    && item.allowed_purposes.includes(PROFILE_PURPOSE)
    && item.allowed_search_modes.includes(null));
  const blocked = profile.status !== "draft" || profile.approved_sample_count < 200
    || facts.length === 0 || eligibleRuntimes.length === 0;
  return (
    <details className={styles.inlineDetails}>
      <summary>构建 Profile</summary>
      <form action={action} className={styles.writeForm}>
        <CommandFields commandKey={commandKey} projectId={projectId} />
        <input name="profile_version_id" type="hidden" value={profile.id} />
        <fieldset disabled={!canContribute || pending || blocked}>
          <legend>冻结样本、Fact、Prompt 与模型后构建</legend>
          <div className={styles.formGridThree}>
            <OptionSelect label="事实快照" name="fact_snapshot_id" options={facts} />
            <RuntimeSelect name="runtime_selection_id" options={eligibleRuntimes} />
            <p className={styles.formNote}>服务端将冻结创建 Profile 时保存的 {profile.approved_sample_count} 条样本 manifest。</p>
            <button type="submit">{pending ? "排队中..." : "构建 Profile"}</button>
          </div>
        </fieldset>
        {blocked ? <p className={styles.formNote}>blocked · draft / persisted 200-sample manifest / Fact / approved Provider API runtime required</p> : null}
        <SyntheticActionFeedback state={state} />
      </form>
    </details>
  );
}

export function ReviewCaseRunForm({
  canContribute,
  cases,
  commandKey,
  projectId,
  runtimes,
  suite
}: {
  canContribute: boolean;
  cases: ReviewCase[];
  commandKey: string;
  projectId: string;
  runtimes: SyntheticRuntimeOption[];
  suite: ReviewSuite;
}) {
  const [state, action, pending] = useActionState(
    enqueueReviewCaseRunAction, initialSyntheticActionState
  );
  const eligibleRuntimes = runtimes.filter((item) => item.capture_method === "provider_api"
    && item.allowed_search_modes.includes(null)
    && REVIEW_PURPOSES.every((purpose) => item.allowed_purposes.includes(purpose)));
  const blocked = suite.status !== "frozen" || cases.length === 0 || eligibleRuntimes.length === 0;
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields commandKey={commandKey} projectId={projectId} />
      <input name="suite_version_id" type="hidden" value={suite.id} />
      <fieldset disabled={!canContribute || pending || blocked}>
          <legend>运行一个冻结测评用例</legend>
        <div className={styles.formGridThree}>
          <OptionSelect label="测评用例" name="case_id" options={cases.map((item) => ({ id: item.id, label: `${item.ordinal} · ${item.case_key}` }))} />
          <RuntimeSelect name="runtime_selection_id" options={eligibleRuntimes} />
          <label><span>风格通过阈值</span><input defaultValue="4.2" max="5" min="0" name="style_pass_threshold" required step="0.1" type="number" /></label>
          <button type="submit">{pending ? "排队中..." : "运行用例"}</button>
        </div>
      </fieldset>
      {blocked ? <p className={styles.formNote}>已阻断 · 需要冻结的测评套件 / 用例 / 支持六种用途的 Provider API 运行时</p> : null}
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function CorpusOfflineExperimentForms({
  canApprove,
  canContribute,
  commandKeys,
  inventory,
  projectId,
  runtimes
}: {
  canApprove: boolean;
  canContribute: boolean;
  commandKeys: Readonly<{ candidate: string; approve: string; experiment: string }>;
  inventory: SyntheticResourceInventory;
  projectId: string;
  runtimes: SyntheticRuntimeOption[];
}) {
  const [candidateState, candidateAction, candidatePending] = useActionState(
    enqueueCandidateCorpusAction, initialSyntheticActionState
  );
  const [approvalState, approvalAction, approvalPending] = useActionState(
    enqueueApprovedCorpusAction, initialSyntheticActionState
  );
  const [experimentState, experimentAction, experimentPending] = useActionState(
    enqueueOfflineExperimentAction, initialSyntheticActionState
  );
  const eligibleRuntimes = runtimes.filter((item) => item.capture_method === "provider_api"
    && item.allowed_search_modes.includes(null)
    && item.allowed_purposes.includes(OFFLINE_PURPOSE));
  const experimentBlocked = inventory.question_sets.length === 0
    || inventory.candidate_corpora.length === 0
    || inventory.approved_corpora.length === 0
    || eligibleRuntimes.length === 0;
  return (
    <div className={styles.selectedSuite}>
      <form action={candidateAction} className={styles.writeForm}>
        <CommandFields commandKey={commandKeys.candidate} projectId={projectId} />
        <fieldset disabled={!canContribute || candidatePending || inventory.review_jobs.length === 0}>
          <legend>从通过或 Warning 的 Review 结果冻结候选 Corpus</legend>
          <div className={styles.formGridThree}>
            <label><span>已完成测评任务</span><select multiple name="review_job_ids" required size={Math.min(8, Math.max(3, inventory.review_jobs.length))}>{inventory.review_jobs.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            <button type="submit">{candidatePending ? "排队中..." : "冻结候选 Corpus"}</button>
          </div>
        </fieldset>
        <SyntheticActionFeedback state={candidateState} />
      </form>
      <form action={approvalAction} className={styles.writeForm}>
        <CommandFields commandKey={commandKeys.approve} projectId={projectId} />
        <fieldset disabled={!canApprove || approvalPending || inventory.candidate_corpora.length === 0}>
          <legend>批准候选 Corpus</legend>
          <div className={styles.formGridThree}>
            <OptionSelect label="候选语料" name="source_corpus_job_id" options={inventory.candidate_corpora} />
            <button type="submit">{approvalPending ? "排队中..." : "批准并冻结"}</button>
          </div>
        </fieldset>
        <SyntheticActionFeedback state={approvalState} />
      </form>
      <form action={experimentAction} className={styles.writeForm}>
        <CommandFields commandKey={commandKeys.experiment} projectId={projectId} />
        <fieldset disabled={!canContribute || experimentPending || experimentBlocked}>
          <legend>运行 baseline / current / candidate 三臂配对实验</legend>
          <div className={styles.formGridThree}>
            <OptionSelect label="问题集" name="question_set_id" options={inventory.question_sets} />
            <OptionSelect label="当前已批准语料" name="current_corpus_job_id" options={inventory.approved_corpora} />
            <OptionSelect label="候选语料" name="candidate_corpus_job_id" options={inventory.candidate_corpora} />
            <RuntimeSelect name="runtime_selection_id" options={eligibleRuntimes} />
            <label><span>最小有效配对比例</span><input defaultValue="0.8" max="1" min="0.01" name="minimum_valid_pair_ratio" required step="0.01" type="number" /></label>
            <button type="submit">{experimentPending ? "排队中..." : "运行三臂实验"}</button>
          </div>
        </fieldset>
        <SyntheticActionFeedback state={experimentState} />
      </form>
    </div>
  );
}

export function StyleCollectionAdmissionForm({
  authorizations,
  canContribute,
  commandKey,
  loginSecrets,
  projectId,
  sources
}: {
  authorizations: CollectionAuthorization[];
  canContribute: boolean;
  commandKey: string;
  loginSecrets: StyleLoginSecretReference[];
  projectId: string;
  sources: StyleSource[];
}) {
  const [state, action, pending] = useActionState(
    admitStyleCollectionAction, initialSyntheticActionState
  );
  const liveSources = sources.filter((item) => item.status === "active"
    && item.access_mode !== "manual_import");
  const [sourceId, setSourceId] = useState(liveSources[0]?.id || "");
  const source = liveSources.find((item) => item.id === sourceId) || liveSources[0];
  const adapters = authorizations.filter((item) => item.channel === source?.channel
    && item.effective_state === "approved"
    && item.allowed_purposes.includes("style_collection"));
  const secrets = loginSecrets.filter((item) => item.purpose
    === `style_collection_login.${source?.channel || ""}`);
  const blocked = !source || adapters.length === 0
    || (source.access_mode === "authenticated" && secrets.length === 0);
  return (
    <form action={action} className={styles.writeForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      <fieldset disabled={!canContribute || pending || blocked}>
        <legend>澳洲英文 Style Collection</legend>
        <div className={styles.formGridThree}>
          <label><span>风格来源</span><select name="style_source_revision_id" onChange={(event) => setSourceId(event.target.value)} value={source?.id || ""}>{liveSources.map((item) => <option key={item.id} value={item.id}>{item.channel} · r{item.revision_number} · {item.access_mode}</option>)}</select></label>
          <label><span>已批准适配器</span><select name="adapter_release">{adapters.map((item) => <option key={item.id} value={item.adapter_release}>{item.adapter_release}</option>)}</select></label>
          <label><span>登录密钥引用</span><select name="login_secret_reference_id" required={source?.access_mode === "authenticated"}><option value="">无需密钥</option>{secrets.map((item) => <option key={item.reference_id} value={item.reference_id}>{item.purpose} · v{item.current_version}</option>)}</select></label>
          <button disabled={!canContribute || pending || blocked} type="submit">{pending ? "排队中..." : "批准并排队采集"}</button>
        </div>
      </fieldset>
      {blocked ? <p className={styles.formNote}>blocked · source / authorization / login secret admission incomplete</p> : null}
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function SelectedJobControls({
  canContribute,
  commandKey,
  job,
  projectId
}: {
  canContribute: boolean;
  commandKey: string;
  job: SyntheticJob;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(cancelSyntheticJobAction, initialSyntheticActionState);
  const terminal = ["succeeded", "failed", "dead_lettered", "cancelled"].includes(job.status);
  return (
    <form action={action} className={styles.jobControlForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      <input name="job_id" type="hidden" value={job.id} />
      <input name="expected_version" type="hidden" value={job.version} />
      <button className="danger" disabled={!canContribute || pending || terminal} type="submit">{pending ? "取消中..." : "取消任务"}</button>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

function CommandFields({ commandKey, projectId }: { commandKey: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}

function OptionSelect({
  label,
  name,
  options
}: {
  label: string;
  name: string;
  options: ReadonlyArray<{ id: string; label: string }>;
}) {
  return <label><span>{label}</span><select name={name} required>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>;
}

function RuntimeSelect({ name, options }: { name: string; options: SyntheticRuntimeOption[] }) {
  return <label><span>已批准模型运行时</span><select name={name} required>{options.map((option) => <option key={option.selection_id} value={option.selection_id}>{option.provider} · {option.configured_model} · {option.model_release_id}</option>)}</select></label>;
}
