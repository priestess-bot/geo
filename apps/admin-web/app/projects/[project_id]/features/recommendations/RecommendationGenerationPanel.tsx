"use client";

import { useActionState, useState } from "react";

import { enqueueRecommendationGenerationAction } from "./recommendationGenerationAction";
import {
  initialGenerationActionState,
  type RecommendationGenerationCatalog,
  type RecommendationModelRuntimeOption,
  type RecommendationPromptBindingOption
} from "./recommendationGenerationTypes";
import type { Recommendation } from "./recommendationTypes";
import styles from "./Recommendations.module.css";

export function RecommendationGenerationPanel({
  canContribute,
  catalog,
  idempotencyKey,
  projectId,
  recommendation
}: {
  canContribute: boolean;
  catalog: RecommendationGenerationCatalog;
  idempotencyKey: string;
  projectId: string;
  recommendation: Recommendation;
}) {
  const [state, action, pending] = useActionState(
    enqueueRecommendationGenerationAction,
    initialGenerationActionState
  );
  const [primaryRuntimeRequest, setPrimaryRuntimeRequest] = useState("");
  const [arbiterRuntimeRequest, setArbiterRuntimeRequest] = useState("");
  const [arbiterEnabled, setArbiterEnabled] = useState(false);
  const selectors = evidenceSelectors(recommendation);
  const primaryRuntimes = runtimesFor(catalog.runtimes, catalog.recommendationPrompts);
  const arbiterRuntimes = runtimesFor(catalog.runtimes, catalog.arbiterPrompts);
  const primaryRuntime = selectedRuntime(primaryRuntimes, primaryRuntimeRequest);
  const arbiterRuntime = selectedRuntime(arbiterRuntimes, arbiterRuntimeRequest);
  const primaryReady = catalog.recommendationPrompts.length > 0
    && primaryRuntime !== null
    && selectors.length > 0;
  const disabled = !canContribute || pending;
  return (
    <section className={styles.commandsSection} aria-labelledby="recommendation-generation-heading">
      <div className={styles.sectionHeading}>
        <div><p>Durable Job</p><h3 id="recommendation-generation-heading">重新生成建议</h3></div>
        <span>{selectors.length} 个证据引用</span>
      </div>

      <CatalogProblems catalog={catalog} />
      {!primaryReady ? (
        <div className={styles.blockedNotice} role="status">
          <strong>当前没有完整的已批准生成运行时</strong>
          <span>{primaryBlockReason(catalog, primaryRuntimes, selectors.length)}</span>
        </div>
      ) : null}

      <form action={action} className={styles.stackedForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="idempotency_key" type="hidden" value={idempotencyKey} />
        <input name="scope" type="hidden" value={JSON.stringify(recommendation.evidence.scope)} />
        <input name="evidence_selectors" type="hidden" value={JSON.stringify(selectors)} />
        <div className={styles.generationGrid}>
          <PromptSelect
            disabled={disabled || catalog.recommendationPrompts.length === 0}
            label="Recommendation Prompt"
            name="prompt_binding_id"
            options={catalog.recommendationPrompts}
          />
          <RuntimeSelect
            disabled={disabled || primaryRuntimes.length === 0}
            label="批准的模型运行时"
            name="model_runtime_selection_id"
            onChange={setPrimaryRuntimeRequest}
            options={primaryRuntimes}
            value={primaryRuntime?.selection_id || ""}
          />
          <SearchModeSelect
            disabled={disabled || !primaryRuntime}
            name="model_search_mode"
            runtime={primaryRuntime}
          />
          <label>
            <span>有效期（ISO 8601）</span>
            <input defaultValue={recommendation.valid_until} disabled={disabled} name="valid_until" required />
          </label>
          <label>
            <span>最少真实观测数</span>
            <input defaultValue={3} disabled={disabled} max={1000} min={1} name="minimum_real_observations" type="number" />
          </label>
        </div>
        {primaryRuntime ? <RuntimeLineage runtime={primaryRuntime} /> : null}

        <details className={styles.detailDisclosure}>
          <summary>独立仲裁</summary>
          <label className={styles.toggleField}>
            <input
              checked={arbiterEnabled}
              disabled={disabled}
              name="arbiter_enabled"
              onChange={(event) => setArbiterEnabled(event.target.checked)}
              type="checkbox"
            />
            <span>启用独立仲裁模型</span>
          </label>
          {arbiterEnabled && (!catalog.arbiterPrompts.length || !arbiterRuntime) ? (
            <div className={styles.blockedNotice} role="status">
              <strong>独立仲裁不可用</strong>
              <span>需要至少一个最新冻结的 Arbiter Prompt 和一个允许 arbiter 用途的批准运行时。</span>
            </div>
          ) : null}
          <div className={styles.generationGrid}>
            <PromptSelect
              disabled={disabled || !arbiterEnabled || catalog.arbiterPrompts.length === 0}
              label="Arbiter Prompt"
              name="arbiter_prompt_binding_id"
              options={catalog.arbiterPrompts}
            />
            <RuntimeSelect
              disabled={disabled || !arbiterEnabled || arbiterRuntimes.length === 0}
              label="批准的仲裁运行时"
              name="arbiter_runtime_selection_id"
              onChange={setArbiterRuntimeRequest}
              options={arbiterRuntimes}
              value={arbiterRuntime?.selection_id || ""}
            />
            <SearchModeSelect
              disabled={disabled || !arbiterEnabled || !arbiterRuntime}
              name="arbiter_search_mode"
              runtime={arbiterRuntime}
            />
          </div>
          {arbiterEnabled && arbiterRuntime ? <RuntimeLineage runtime={arbiterRuntime} /> : null}
        </details>
        <button
          disabled={disabled || !primaryReady
            || (arbiterEnabled && (!catalog.arbiterPrompts.length || !arbiterRuntime))}
          type="submit"
        >
          {pending ? "入队中..." : "创建生成任务"}
        </button>
      </form>
      {state.kind !== "idle" ? (
        <div className={state.kind === "error" ? styles.loadError : styles.boundaryNotice} role={state.kind === "error" ? "alert" : "status"}>
          <strong>{state.message}</strong>
          {state.job ? <code>{state.job.id} · {state.job.status} · {state.job.model.provider}/{state.job.model.configured_model}</code> : null}
          {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
        </div>
      ) : null}
    </section>
  );
}

function PromptSelect({ disabled, label, name, options }: {
  disabled: boolean;
  label: string;
  name: string;
  options: RecommendationPromptBindingOption[];
}) {
  return (
    <label>
      <span>{label}</span>
      <select disabled={disabled} name={name} required>
        {!options.length ? <option value="">无最新冻结 Prompt</option> : null}
        {options.map((item) => (
          <option key={item.id} value={item.id}>
            {item.purpose} · Release v{item.release_version} · Binding v{item.binding_version}
          </option>
        ))}
      </select>
    </label>
  );
}

function RuntimeSelect({ disabled, label, name, onChange, options, value }: {
  disabled: boolean;
  label: string;
  name: string;
  onChange: (value: string) => void;
  options: RecommendationModelRuntimeOption[];
  value: string;
}) {
  return (
    <label>
      <span>{label}</span>
      <select
        disabled={disabled}
        name={name}
        onChange={(event) => onChange(event.target.value)}
        required
        value={value}
      >
        {!options.length ? <option value="">无已批准运行时</option> : null}
        {options.map((item) => (
          <option key={item.selection_id} value={item.selection_id}>
            {item.provider} · {item.configured_model} · {captureLabel(item.capture_method)}
          </option>
        ))}
      </select>
    </label>
  );
}

function SearchModeSelect({ disabled, name, runtime }: {
  disabled: boolean;
  name: string;
  runtime: RecommendationModelRuntimeOption | null;
}) {
  return (
    <label>
      <span>搜索模式</span>
      <select disabled={disabled} name={name} required>
        {(runtime?.allowed_search_modes || []).map((mode) => (
          <option key={mode || "__none__"} value={mode || "__none__"}>
            {mode || "不启用搜索"}
          </option>
        ))}
        {!runtime ? <option value="">先选择批准运行时</option> : null}
      </select>
    </label>
  );
}

function RuntimeLineage({ runtime }: { runtime: RecommendationModelRuntimeOption }) {
  return (
    <details className={styles.lineageDisclosure}>
      <summary>查看冻结运行时身份</summary>
      <dl className={styles.factGrid}>
        <div><dt>Selection</dt><dd><code>{runtime.selection_id}</code></dd></div>
        <div><dt>Manifest</dt><dd><code>{runtime.manifest_id}</code></dd></div>
        <div><dt>Adapter Release</dt><dd><code>{runtime.adapter_release_id}</code></dd></div>
        <div><dt>Model Release</dt><dd><code>{runtime.model_release_id}</code></dd></div>
      </dl>
    </details>
  );
}

function CatalogProblems({ catalog }: { catalog: RecommendationGenerationCatalog }) {
  const messages = [
    catalog.recommendationPromptProblem,
    catalog.arbiterPromptProblem,
    catalog.runtimeProblem
  ].filter((item): item is string => Boolean(item));
  return messages.length ? (
    <div className={styles.loadError} role="alert">
      <strong>生成目录未完整加载</strong>
      {messages.map((message) => <span key={message}>{message}</span>)}
    </div>
  ) : null;
}

function selectedRuntime(
  runtimes: RecommendationModelRuntimeOption[],
  requested: string
): RecommendationModelRuntimeOption | null {
  return runtimes.find((item) => item.selection_id === requested) || runtimes[0] || null;
}

function runtimesFor(
  runtimes: RecommendationModelRuntimeOption[],
  prompts: RecommendationPromptBindingOption[]
): RecommendationModelRuntimeOption[] {
  const purposes = new Set(prompts.map((item) => item.purpose));
  return runtimes.filter((item) => item.allowed_purposes.some((purpose) => purposes.has(purpose)));
}

function primaryBlockReason(
  catalog: RecommendationGenerationCatalog,
  runtimes: RecommendationModelRuntimeOption[],
  selectorCount: number
): string {
  if (!catalog.recommendationPrompts.length) {
    return "请先批准、冻结并绑定 Recommendation Prompt Release。";
  }
  if (!runtimes.length) {
    return "请先批准项目模型运行时，并允许所选 Prompt 的精确用途。";
  }
  if (!selectorCount) return "当前 Recommendation 没有可重新解析的证据选择器。";
  return "生成目录尚未满足入队门禁。";
}

function captureLabel(value: string): string {
  return value === "proxy_grounded_api" ? "Grounded API" : "Provider API";
}

function evidenceSelectors(recommendation: Recommendation) {
  const evidence = recommendation.evidence;
  return [
    ...evidence.observations.map((item) => ({ kind: "observation", resource_id: item.resource_id })),
    ...evidence.metric_comparisons.map((item) => ({ kind: "metric_comparison", resource_id: item.resource_id })),
    ...evidence.facts.map((item) => ({ kind: "fact", resource_id: item.resource_id })),
    ...evidence.rules.map((item) => ({ kind: "rule", resource_id: item.resource_id })),
    ...evidence.contents.map((item) => ({ kind: "content", resource_id: item.resource_id })),
    ...evidence.questions.map((item) => ({ kind: "question", resource_id: item.resource_id })),
    ...evidence.surfaces.map((item) => ({ kind: "surface", resource_id: item.resource_id }))
  ];
}
