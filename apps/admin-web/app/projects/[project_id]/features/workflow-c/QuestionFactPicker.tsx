"use client";

import type { KnowledgeQuestionFactView } from "@geo/types/geo";
import { useMemo, useState } from "react";

import baseStyles from "./QuestionWorkspace.module.css";
import responsiveStyles from "./QuestionWorkspaceResponsive.module.css";
import { mergeCssModules } from "./cssModules";

const styles = mergeCssModules(baseStyles, responsiveStyles);

export function QuestionFactPicker({ defaultFactIds, facts }: {
  defaultFactIds: readonly string[];
  facts: readonly KnowledgeQuestionFactView[];
}) {
  const availableIds = useMemo(() => new Set(facts.map((fact) => fact.id)), [facts]);
  const [selectedIds, setSelectedIds] = useState(
    () => new Set(defaultFactIds.filter((id) => availableIds.has(id)))
  );
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredFacts = useMemo(() => normalizedQuery
    ? facts.filter((fact) => `${fact.source_title} ${fact.statement}`
      .toLocaleLowerCase().includes(normalizedQuery))
    : facts, [facts, normalizedQuery]);
  const selectedFacts = facts.filter((fact) => selectedIds.has(fact.id));

  function toggle(id: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return <fieldset className={styles.factPicker}>
    <legend>1. 选择知识来源</legend>
    <p>搜索并勾选直接支撑本次问题的知识。已选条目会随任务冻结，并显示在生成结果中。</p>
    {Array.from(selectedIds).map((id) => <input
      key={id}
      name="fact_candidate_ids"
      type="hidden"
      value={id}
    />)}

    <div className={styles.factToolbar}>
      <label>搜索知识<input
        onChange={(event) => setQuery(event.currentTarget.value)}
        placeholder="输入产品、功能或来源名称"
        type="search"
        value={query}
      /></label>
      <div className={selectedIds.size ? styles.factSelectionReady : styles.factSelectionEmpty}>
        <strong>已选 {selectedIds.size} 条</strong>
        <span>{selectedIds.size ? "只会提交这些来源" : "至少选择一条后才能生成"}</span>
        {selectedIds.size ? <button type="button" onClick={() => setSelectedIds(new Set())}>
          清空
        </button> : null}
      </div>
    </div>

    {selectedFacts.length ? <div className={styles.selectedFacts} aria-label="已选知识来源">
      {selectedFacts.map((fact) => <span key={fact.id}>
        <span><strong>{fact.source_title}</strong><small>{preview(fact.statement, 100)}</small></span>
        <button
          aria-label={`移除 ${fact.source_title}`}
          onClick={() => toggle(fact.id, false)}
          title="移除"
          type="button"
        >×</button>
      </span>)}
    </div> : null}

    <div className={styles.factResults} aria-label="可选知识来源">
      {filteredFacts.length ? filteredFacts.map((fact) => <label className={styles.factRow}
        key={fact.id}>
        <input
          aria-label={`选择 ${fact.source_title}`}
          checked={selectedIds.has(fact.id)}
          onChange={(event) => toggle(fact.id, event.currentTarget.checked)}
          type="checkbox"
        />
        <span><strong>{fact.source_title}</strong><small>{preview(fact.statement, 180)}</small></span>
      </label>) : <p className={styles.noFactResults}>没有匹配的知识来源。</p>}
    </div>
    <small className={styles.factResultCount}>
      显示 {filteredFacts.length} / {facts.length} 条，可在列表内滚动查看
    </small>
  </fieldset>;
}

function preview(value: string, max: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > max ? `${normalized.slice(0, max - 1)}…` : normalized;
}
