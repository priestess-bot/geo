"use client";

import { useActionState } from "react";

import {
  approveRecommendationAction,
  expireRecommendationAction,
  prepareRecommendationDraftAction,
  reconcileRecommendationStaleAction,
  rejectRecommendationAction,
  reviewRecommendationAction,
  submitRecommendationAction
} from "./recommendationActions";
import { RecommendationActionFeedback } from "./RecommendationActionFeedback";
import {
  initialRecommendationActionState,
  inputChangeReasons,
  type InputChangeReason,
  type LinkedDraft,
  type Recommendation
} from "./recommendationTypes";
import styles from "./Recommendations.module.css";

export type RecommendationCommandKeys = Readonly<{
  submit: string;
  review: string;
  approve: string;
  reject: string;
  expire: string;
  reconcile: string;
  drafts: Readonly<Record<string, string>>;
}>;

export function RecommendationCommands({
  actorIdentityId,
  canApprove,
  canContribute,
  commandKeys,
  drafts,
  projectId,
  recommendation
}: {
  actorIdentityId: string;
  canApprove: boolean;
  canContribute: boolean;
  commandKeys: RecommendationCommandKeys;
  drafts: readonly LinkedDraft[];
  projectId: string;
  recommendation: Recommendation;
}) {
  const [submitState, submitAction, submitPending] = useActionState(
    submitRecommendationAction,
    initialRecommendationActionState
  );
  const [reviewState, reviewAction, reviewPending] = useActionState(
    reviewRecommendationAction,
    initialRecommendationActionState
  );
  const [approveState, approveAction, approvePending] = useActionState(
    approveRecommendationAction,
    initialRecommendationActionState
  );
  const [rejectState, rejectAction, rejectPending] = useActionState(
    rejectRecommendationAction,
    initialRecommendationActionState
  );
  const [expireState, expireAction, expirePending] = useActionState(
    expireRecommendationAction,
    initialRecommendationActionState
  );
  const [reconcileState, reconcileAction, reconcilePending] = useActionState(
    reconcileRecommendationStaleAction,
    initialRecommendationActionState
  );
  const status = recommendation.status;
  const canSubmit = canContribute && status === "draft";
  const canReview = canApprove && status === "in_review";
  const selfOwned = actorIdentityId === recommendation.created_by;
  const canApproveCurrent = canApprove && status === "in_review" && !selfOwned;
  const canReject = canApprove && (status === "draft" || status === "in_review");
  const canExpire = canApprove
    && (status === "draft" || status === "in_review" || status === "approved");
  const canReconcile = canContribute && status === "approved";

  return (
    <section className={styles.commandsSection} aria-labelledby="recommendation-actions-heading">
      <div className={styles.sectionHeading}>
        <div><p>Human gate</p><h3 id="recommendation-actions-heading">审核与失效控制</h3></div>
        <StatusPill value={status} />
      </div>

      <div className={styles.boundaryNotice}>
        <strong>动作边界</strong>
        <span>批准只创建未启动草稿；系统不会自动排队、执行或发布。草稿进入后续流程前必须再次校验来源版本。</span>
      </div>

      <div className={styles.commandGrid}>
        <section className={styles.commandBlock} aria-labelledby="recommendation-submit-heading">
          <header><h4 id="recommendation-submit-heading">提交审核</h4><span>Contributor</span></header>
          <p>将 Draft 交给 Owner 或 Admin 进行独立证据审核。</p>
          <form action={submitAction}>
            <CommandFields idempotencyKey={commandKeys.submit} projectId={projectId} recommendation={recommendation} />
            <button disabled={!canSubmit || submitPending} title={submitReason(canContribute, status)} type="submit">
              {submitPending ? "提交中..." : "提交审核"}
            </button>
          </form>
          <RecommendationActionFeedback state={submitState} />
        </section>

        <section className={styles.commandBlock} aria-labelledby="recommendation-review-heading">
          <header><h4 id="recommendation-review-heading">证据审核</h4><span>Owner / Admin</span></header>
          <form action={reviewAction} className={styles.stackedForm}>
            <CommandFields idempotencyKey={commandKeys.review} projectId={projectId} recommendation={recommendation} />
            <label><span>审核记录</span><textarea disabled={!canReview || reviewPending} maxLength={20_000} name="notes" required /></label>
            <button disabled={!canReview || reviewPending} title={reviewReason(canApprove, status)} type="submit">
              {reviewPending ? "记录中..." : "记录当前证据审核"}
            </button>
          </form>
          <RecommendationActionFeedback state={reviewState} />
        </section>

        <section className={styles.commandBlock} aria-labelledby="recommendation-approve-heading">
          <header><h4 id="recommendation-approve-heading">批准</h4><span>四眼原则</span></header>
          <p>批准前后端都会重验当前输入；创建者不能自批。</p>
          <form action={approveAction}>
            <CommandFields idempotencyKey={commandKeys.approve} projectId={projectId} recommendation={recommendation} />
            <button disabled={!canApproveCurrent || approvePending} title={approveReason(canApprove, status, selfOwned)} type="submit">
              {approvePending ? "批准中..." : "批准并创建草稿"}
            </button>
          </form>
          <RecommendationActionFeedback state={approveState} />
        </section>

        <section className={styles.commandBlock} aria-labelledby="recommendation-reject-heading">
          <header><h4 id="recommendation-reject-heading">拒绝</h4><span>终态</span></header>
          <form action={rejectAction} className={styles.stackedForm}>
            <CommandFields idempotencyKey={commandKeys.reject} projectId={projectId} recommendation={recommendation} />
            <label><span>拒绝原因</span><textarea disabled={!canReject || rejectPending} maxLength={5000} name="reason" required /></label>
            <button className="danger" disabled={!canReject || rejectPending} title={rejectReason(canApprove, status)} type="submit">
              {rejectPending ? "拒绝中..." : "拒绝 Recommendation"}
            </button>
          </form>
          <RecommendationActionFeedback state={rejectState} />
        </section>
      </div>

      <details className={styles.invalidationSection}>
        <summary>过期与输入变化处理</summary>
        <div className={styles.commandGrid}>
          <section className={styles.commandBlock} aria-labelledby="recommendation-expire-heading">
            <header><h4 id="recommendation-expire-heading">标记过期</h4><span>同步阻断草稿</span></header>
            <form action={expireAction} className={styles.stackedForm}>
              <CommandFields idempotencyKey={commandKeys.expire} projectId={projectId} recommendation={recommendation} />
              <label><span>过期原因</span><textarea disabled={!canExpire || expirePending} maxLength={5000} name="reason" required /></label>
              <button className="danger" disabled={!canExpire || expirePending} title={expireReason(canApprove, status)} type="submit">
                {expirePending ? "处理中..." : "过期并阻断未启动草稿"}
              </button>
            </form>
            <RecommendationActionFeedback state={expireState} />
          </section>

          <section className={styles.commandBlock} aria-labelledby="recommendation-reconcile-heading">
            <header><h4 id="recommendation-reconcile-heading">核对当前输入</h4><span>Approved only</span></header>
            <form action={reconcileAction} className={styles.stackedForm}>
              <CommandFields idempotencyKey={commandKeys.reconcile} projectId={projectId} recommendation={recommendation} />
              <ChangeReason disabled={!canReconcile || reconcilePending} />
              <p>当前证据版本由服务端在同一项目事务中重新解析。</p>
              <button disabled={!canReconcile || reconcilePending} title={reconcileReason(canContribute, status)} type="submit">
                {reconcilePending ? "核对中..." : "核对并同步 stale 状态"}
              </button>
            </form>
            <RecommendationActionFeedback state={reconcileState} />
          </section>
        </div>
      </details>

      <DraftPreparationList
        canContribute={canContribute}
        commandKeys={commandKeys.drafts}
        drafts={drafts}
        projectId={projectId}
        recommendation={recommendation}
      />
    </section>
  );
}

function DraftPreparationList({
  canContribute,
  commandKeys,
  drafts,
  projectId,
  recommendation
}: {
  canContribute: boolean;
  commandKeys: Readonly<Record<string, string>>;
  drafts: readonly LinkedDraft[];
  projectId: string;
  recommendation: Recommendation;
}) {
  if (!drafts.length) return <p className={styles.inlineEmpty}>当前没有关联草稿。批准 actionable Recommendation 后才会创建草稿。</p>;
  return (
    <div className={styles.draftCommands}>
      <div className={styles.subheading}><h4>关联草稿执行前复核</h4><span>{drafts.length} 个草稿</span></div>
      {drafts.map((draft) => (
        <DraftPreparation
          canContribute={canContribute}
          idempotencyKey={commandKeys[draft.id] || `missing-command-key-${draft.id}`}
          key={draft.id}
          projectId={projectId}
          recommendation={recommendation}
          draft={draft}
        />
      ))}
    </div>
  );
}

function DraftPreparation({
  canContribute,
  draft,
  idempotencyKey,
  projectId,
  recommendation
}: {
  canContribute: boolean;
  draft: LinkedDraft;
  idempotencyKey: string;
  projectId: string;
  recommendation: Recommendation;
}) {
  const [state, action, pending] = useActionState(
    prepareRecommendationDraftAction,
    initialRecommendationActionState
  );
  const canPrepare = canContribute
    && recommendation.status === "approved"
    && draft.status === "draft";
  return (
    <details className={styles.draftCommand}>
      <summary>
        <span><strong>{draftKindLabel(draft.kind)}</strong><code>{draft.id}</code></span>
        <StatusPill value={draft.status} />
      </summary>
      <form action={action} className={styles.stackedForm}>
        <CommandFields idempotencyKey={idempotencyKey} projectId={projectId} recommendation={recommendation} />
        <input name="draft_id" type="hidden" value={draft.id} />
        <ChangeReason disabled={!canPrepare || pending} />
        <p>执行前由服务端重新解析 Fact、观测、规则和 Prompt 当前版本。</p>
        <button disabled={!canPrepare || pending} title={prepareReason(canContribute, recommendation.status, draft.status)} type="submit">
          {pending ? "复核中..." : "执行前复核来源"}
        </button>
      </form>
      <RecommendationActionFeedback state={state} />
    </details>
  );
}

function CommandFields({
  idempotencyKey,
  projectId,
  recommendation
}: {
  idempotencyKey: string;
  projectId: string;
  recommendation: Recommendation;
}) {
  return (
    <>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="recommendation_id" type="hidden" value={recommendation.id} />
      <input name="expected_version" type="hidden" value={recommendation.version} />
      <input name="idempotency_key" type="hidden" value={idempotencyKey} />
    </>
  );
}

function ChangeReason({ disabled }: { disabled: boolean }) {
  return (
    <label><span>输入变化原因</span><select disabled={disabled} name="change_reason" required>
      {inputChangeReasons.map((reason) => <option key={reason} value={reason}>{changeReasonLabel(reason)}</option>)}
    </select></label>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{value}</span>;
}

function submitReason(allowed: boolean, status: string): string {
  if (!allowed) return "当前角色不能提交 Recommendation";
  return status === "draft" ? "" : "仅 Draft 可以提交审核";
}

function reviewReason(allowed: boolean, status: string): string {
  if (!allowed) return "仅 Owner 或 Admin 可以审核";
  return status === "in_review" ? "" : "仅 In Review 状态可以登记审核";
}

function approveReason(allowed: boolean, status: string, selfOwned: boolean): string {
  if (!allowed) return "仅 Owner 或 Admin 可以批准";
  if (selfOwned) return "Recommendation 创建者不能自批";
  return status === "in_review" ? "" : "仅已审核的 In Review Recommendation 可以批准";
}

function rejectReason(allowed: boolean, status: string): string {
  if (!allowed) return "仅 Owner 或 Admin 可以拒绝";
  return status === "draft" || status === "in_review" ? "" : "仅 Draft 或 In Review 可以拒绝";
}

function expireReason(allowed: boolean, status: string): string {
  if (!allowed) return "仅 Owner 或 Admin 可以标记过期";
  return ["draft", "in_review", "approved"].includes(status) ? "" : "当前状态不能进入 Expired";
}

function reconcileReason(allowed: boolean, status: string): string {
  if (!allowed) return "当前角色不能核对输入";
  return status === "approved" ? "" : "仅 Approved Recommendation 可以核对 stale 条件";
}

function prepareReason(allowed: boolean, recommendationStatus: string, draftStatus: string): string {
  if (!allowed) return "当前角色不能复核草稿来源";
  if (recommendationStatus !== "approved") return "来源 Recommendation 已失效，草稿被阻断";
  return draftStatus === "draft" ? "" : "仅未启动 Draft 可以进行执行前复核";
}

function changeReasonLabel(value: InputChangeReason): string {
  return value.replaceAll("_", " ");
}

function draftKindLabel(value: string): string {
  return value.replaceAll("_", " ");
}
