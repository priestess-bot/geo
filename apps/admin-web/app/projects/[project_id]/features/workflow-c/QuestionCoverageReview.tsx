"use client";

import type { KnowledgeQuestionCandidateView } from "@geo/types/geo";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ActionForm } from "../../geo/features/geo/ActionForm";
import {
  editQuestionCandidate,
  finalizeQuestionCoveragePack
} from "../../geo/features/geo/question-set-actions";
import baseStyles from "./QuestionReviewWorkspace.module.css";
import responsiveStyles from "./QuestionReviewResponsive.module.css";
import { mergeCssModules } from "./cssModules";

const styles = mergeCssModules(baseStyles, responsiveStyles);

type Props = Readonly<{
  campaignId: string;
  campaignName: string;
  candidates: KnowledgeQuestionCandidateView[];
  factLabels: Readonly<Record<string, string>>;
  generationJobId: string;
  projectId: string;
  predecessor?: Readonly<{ id: string; seriesId: string }>;
  setsHref: string;
}>;

export function QuestionCoverageReview({
  campaignId,
  campaignName,
  candidates,
  factLabels,
  generationJobId,
  predecessor,
  projectId,
  setsHref
}: Props) {
  const router = useRouter();
  const eligible = useMemo(
    () => candidates.filter((item) => item.dedup_status === "unique" || item.was_edited),
    [candidates]
  );
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("all");
  const [topic, setTopic] = useState("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const topics = useMemo(
    () => Array.from(new Set(candidates.map((item) => item.topic_cluster).filter(Boolean))).sort(),
    [candidates]
  );
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("en-AU");
    return candidates.filter((item) => {
      const matchesSearch = !needle || item.query_text.toLocaleLowerCase("en-AU").includes(needle);
      const matchesRole = role === "all" || item.coverage_role === role;
      const matchesTopic = topic === "all" || item.topic_cluster === topic;
      return matchesSearch && matchesRole && matchesTopic;
    });
  }, [candidates, role, search, topic]);
  const readyIds = eligible
    .filter((item) => item.workflow_status !== "rejected")
    .map((item) => item.id);
  const readyCount = readyIds.length;
  const validSelection = candidates.length === 100 && readyCount === 100;

  return <div className={styles.coverageReview}>
    <div className={styles.reviewToolbar}>
      <label className={styles.searchField}>
        <span>搜索问题</span>
        <input
          onChange={(event) => setSearch(event.target.value)}
          placeholder="输入关键词筛选"
          type="search"
          value={search}
        />
      </label>
      <label>
        <span>问题分层</span>
        <select onChange={(event) => setRole(event.target.value)} value={role}>
          <option value="all">全部分层</option>
          <option value="category_benchmark">类别基准</option>
          <option value="product_fit">产品适配（非品牌）</option>
          <option value="brand_control">品牌控制</option>
        </select>
      </label>
      <label>
        <span>主题</span>
        <select onChange={(event) => setTopic(event.target.value)} value={topic}>
          <option value="all">全部主题</option>
          {topics.map((value) => <option key={value || ""} value={value || ""}>
            {topicLabel(value || "")}
          </option>)}
        </select>
      </label>
      <div className={styles.selectionSummary}>
        <strong>{readyCount}/100</strong><span>条可冻结</span>
      </div>
    </div>

    <div className={styles.bulkTools}>
      <span>当前显示 {filtered.length} / {candidates.length} 条</span>
      <small>完整测量库必须冻结 100 条；疑似重复项修改后会在服务端重新执行确定性去重。</small>
    </div>

    <div className={styles.coverageCandidateList}>
      {filtered.map((candidate) => {
        const isEditing = editingId === candidate.id;
        const ready = (candidate.dedup_status === "unique" || candidate.was_edited)
          && candidate.workflow_status !== "rejected";
        return <article className={styles.coverageCandidate}
          data-testid="question-coverage-candidate" key={candidate.id}>
          <div className={ready ? styles.readyLabel : styles.repairLabel}>
            <span>{candidate.ordinal}.</span>
            <strong>{ready ? "可冻结" : "需修改"}</strong>
          </div>
          <div className={styles.coverageCandidateBody}>
            {isEditing ? <ActionForm
              action={editQuestionCandidate}
              onSuccess={() => setEditingId(null)}
              pendingLabel="正在保存..."
              refreshOnSuccess
              submitLabel="保存修改"
            >
              <input name="project_id" type="hidden" value={projectId} />
              <input name="campaign_id" type="hidden" value={campaignId} />
              <input name="candidate_id" type="hidden" value={candidate.id} />
              <label>问题文字
                <textarea autoFocus defaultValue={candidate.query_text} name="query_text" required />
              </label>
              <button className={styles.cancelEdit} onClick={() => setEditingId(null)} type="button">
                取消
              </button>
            </ActionForm> : <>
              <div className={styles.questionLine}>
                <strong>{candidate.query_text}</strong>
                {candidate.was_edited ? <span className={styles.editedBadge}>已修改</span> : null}
              </div>
              <div className={styles.coverageMeta}>
                <span>{roleLabel(candidate.coverage_role)}</span>
                <span>{topicLabel(candidate.topic_cluster || "")}</span>
                <span>{queryKindLabel(candidate.query_kind)}</span>
                <span>{funnelLabel(candidate.funnel)}</span>
                {candidate.dedup_status !== "unique" && !candidate.was_edited
                  ? <span>疑似重复，请修改为语义独立的问题</span> : null}
                {candidate.dedup_status !== "unique" && candidate.was_edited
                  ? <span>已修改，冻结时重新检查</span> : null}
              </div>
              <div className={styles.knowledgeLinks}>
                <b>生成时参考</b>
                {candidate.fact_source_ids.map((id) => <span key={id} title={id}>
                  {factLabels[id] || `知识条目 ${id.slice(0, 8)}`}
                </span>)}
              </div>
            </>}
          </div>
          {!isEditing && (candidate.workflow_status === "pending_review"
            || (candidate.workflow_status === "rejected"
              && candidate.dedup_status === "possible_duplicate"))
            ? <button className={styles.editButton} onClick={() => setEditingId(candidate.id)}
              type="button">编辑</button>
            : null}
        </article>;
      })}
    </div>

    <div className={styles.coverageFinalize}>
      <div>
        <strong>{validSelection ? "准备冻结完整 100 条问题" : `还需修正 ${100 - readyCount} 条问题`}</strong>
        <span>100 条全部通过后形成新版本；类别基准、产品适配与品牌控制继续独立分层。</span>
      </div>
      <ActionForm
        action={finalizeQuestionCoveragePack}
        disabled={!validSelection}
        onSuccess={() => router.push(setsHref)}
        pendingLabel="正在确认并冻结..."
        refreshOnSuccess
        submitLabel="确认并冻结 100 条"
      >
        <input name="project_id" type="hidden" value={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="generation_job_id" type="hidden" value={generationJobId} />
        <input name="name" type="hidden" value={`${campaignName} · 100 题测量清单`} />
        {predecessor ? <>
          <input name="series_id" type="hidden" value={predecessor.seriesId} />
          <input name="previous_version_id" type="hidden" value={predecessor.id} />
        </> : null}
        {readyIds.map((id) => <input
          key={id}
          name="included_candidate_ids"
          type="hidden"
          value={id}
        />)}
      </ActionForm>
    </div>
  </div>;
}

function roleLabel(value: KnowledgeQuestionCandidateView["coverage_role"]): string {
  if (value === "category_benchmark") return "类别基准";
  if (value === "product_fit") return "产品适配";
  if (value === "brand_control") return "品牌控制";
  return "单场景";
}

function topicLabel(value: string): string {
  return ({
    buying_priorities: "购买重点",
    property_fit: "场地适配",
    setup_installation: "安装设置",
    performance: "实际表现",
    navigation_coverage: "导航覆盖",
    safety_control: "安全控制",
    maintenance: "维护保养",
    reliability: "可靠耐用",
    ownership_cost: "持有成本",
    local_support: "本地服务"
  } as Record<string, string>)[value] || value || "未分类";
}

function queryKindLabel(value: KnowledgeQuestionCandidateView["query_kind"]): string {
  return ({ recommendation: "推荐", comparison: "比较", research: "调研", support: "使用支持" })[value];
}

function funnelLabel(value: KnowledgeQuestionCandidateView["funnel"]): string {
  return ({ awareness: "初步了解", consideration: "比较考虑", decision: "购买决策", retention: "使用维护" })[value];
}
