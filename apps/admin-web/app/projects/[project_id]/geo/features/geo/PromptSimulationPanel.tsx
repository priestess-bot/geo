import Link from "next/link";
import type { JsonObject, JsonValue, PromptSimulationView } from "@geo/types/geo";
import type { CatalogLoadResult } from "../../../catalogTypes";
import { ActionForm } from "./ActionForm";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import { createPromptSimulation } from "./placement-actions";
import styles from "./GeoWorkspace.module.css";

const DEFAULT_MODEL_POLICY_HASH = "18d6221a72c4f929f2b3e04f089f7c72ec9d32ad811e1e1443cd34dcc8df61b7";

export function PromptSimulationPanel({ projectId, data, catalog }: {
  projectId: string;
  data: GeoWorkspaceData;
  catalog: CatalogLoadResult;
}) {
  const { selection } = data;
  const simulation = data.simulation.data;
  const isLegacySimulation = simulation?.campaign_id === null;
  const editableSimulation = isLegacySimulation ? null : simulation;
  const brands = catalog.entities.data.filter((item) => item.entity_type === "brand");
  const products = catalog.entities.data.filter((item) => item.entity_type === "product");
  const evidence = catalog.evidence.data.filter((item) => item.eligible_for_generation);
  const frozenQuestionItems = data.questionSets.data.flatMap((set) => set.status === "frozen"
    && set.content_hash ? set.items.map((item) => ({ set, item })) : []);
  const selectedQuestionBinding = editableSimulation?.simulation_purpose === "geo_question_test"
    && editableSimulation.question_set_id && editableSimulation.question_set_hash
    && editableSimulation.question_set_item_id
    ? JSON.stringify({
      question_set_id: editableSimulation.question_set_id,
      confirmed_question_set_hash: editableSimulation.question_set_hash,
      question_set_item_id: editableSimulation.question_set_item_id
    }) : "";
  const opportunity = data.opportunities.data.find((item) => item.id === selection.opportunityId);
  const destination = data.destinations.data.find((item) => item.id === opportunity?.destination_id);
  const binding = data.promptBinding.data;
  const output = objectValue(simulation?.artifact_manifest?.output);
  const renderedText = stringValue(output?.rendered_text);
  const claims = output?.claims;
  const canCreate = Boolean(
    selection.campaignId && opportunity && destination && binding?.status === "bound"
    && binding.template_release_id && binding.release_hash
    && brands.length > 0 && products.length > 0 && evidence.length > 0
  );

  return <div className={styles.workspace} data-testid="prompt-simulation-panel">
    <div className={styles.testBanner} role="status">
      <strong>TEST ONLY</strong>
      <span>允许合成消费者身份与评价 · 不可用于正式审查、导出或发布 · publication_eligible=false</span>
    </div>
    <div className={styles.split}>
      <aside className={`${styles.panel} ${styles.sticky}`}>
        <SectionHeader eyebrow="Isolated preview input" title="提示词技术预览" />
        {isLegacySimulation ? <div className={styles.legacyReadOnly} data-testid="legacy-simulation-readonly">
          <div className={styles.testBanner} role="status"><strong>迁移历史 · 只读</strong>
            <span>该记录没有 Campaign / Opportunity 绑定，只允许查看和下载，不能作为新建、审核、导出或发布输入。</span></div>
          {selection.campaignId && opportunity ? <Link className="button secondary"
            href={geoHref(projectId, selection, { simulation_id: undefined, job_id: undefined })}>
            返回当前 Campaign 新建预览
          </Link> : <Empty>先选择当前 Campaign 和渠道任务，才能新建预览。</Empty>}
        </div> : <>
        <ActionForm action={createPromptSimulation} submitLabel="运行 TEST ONLY 预览"
          disabled={!canCreate} key={editableSimulation?.id || "new-simulation"}>
          <HiddenProject projectId={projectId} />
          <input type="hidden" name="campaign_id" value={selection.campaignId || ""} />
          <input type="hidden" name="opportunity_id" value={selection.opportunityId || ""} />
          <input type="hidden" name="prompt_release_binding_id" value={binding?.id || ""} />
          <input type="hidden" name="destination_id" value={destination?.id || ""} />
          <input type="hidden" name="confirmed_release_hash" value={binding?.release_hash || ""} />
          <div className={styles.keyValue}><span>渠道与 Prompt Release</span><strong>{destination
            ? `${destination.publication_channel} · ${destination.destination_key}` : "未选择"}</strong>
            <code>{binding?.template_release_id || "unbound"}</code>
            <code>{binding?.release_hash || "no approved release hash"}</code></div>
          <label>主品牌
            <select name="primary_brand_entity_id" required
              defaultValue={editableSimulation?.primary_brand_entity_id || ""}><option value="" disabled>选择品牌</option>
              {brands.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}
            </select>
          </label>
          <label>产品
            <select name="product_entity_id" required
              defaultValue={editableSimulation?.product_entity_id || ""}><option value="" disabled>选择产品</option>
              {products.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}
            </select>
          </label>
          <label>模拟身份模式
            <select name="authenticity_mode" required
              defaultValue={editableSimulation?.authenticity_mode || "synthetic_testimonial"}>
              <option value="synthetic_testimonial">合成消费者评价</option>
              <option value="fake_persona">虚构消费者身份</option>
              <option value="brand_authored">品牌身份</option>
            </select>
          </label>
          <label>仿真用途<select name="simulation_purpose" required
            defaultValue={editableSimulation?.simulation_purpose || "content_preview"}>
            <option value="content_preview">文案技术预览</option>
            <option value="geo_question_test">GEO 问题内部测试</option>
          </select></label>
          <label>冻结测试问题
            <select name="question_binding" defaultValue={selectedQuestionBinding}>
              <option value="">文案预览不绑定问题</option>
              {frozenQuestionItems.map(({ set, item }) => <option key={item.id} value={JSON.stringify({
                question_set_id: set.id,
                confirmed_question_set_hash: set.content_hash,
                question_set_item_id: item.id
              })}>{set.name} v{set.version_number} · {item.query_text_snapshot}</option>)}
            </select>
          </label>
          <label>治理合格证据（可多选）
            <select className={styles.multiSelect} name="evidence_item_ids" required multiple size={Math.min(Math.max(evidence.length, 3), 8)}>
              {evidence.map((item) => <option key={item.id} value={item.id}>
                {item.item_type} · {item.subject_role} · {evidenceLabel(item.snapshot.text, item.source_id)}
              </option>)}
            </select>
          </label>
          <label>测试目标<select name="intent" defaultValue="product recommendation"><option value="product recommendation">商品推荐</option><option value="product comparison">产品比较</option><option value="buying guide">购买指南</option></select></label>
          <label>模拟受众<input name="audience" defaultValue="Australian consumers" required /></label>
          <label>输出形式<select name="deliverable" defaultValue="channel-specific draft"><option value="channel-specific draft">渠道适配文案</option><option value="short review">短评</option><option value="community post">社区帖子</option></select></label>
          <label className={styles.check}><input type="checkbox" name="public_citations_required" defaultChecked />公开事实需要引用</label>
          <label className={styles.check}><input type="checkbox" name="unsupported_superlatives" />允许无证据最高级表述</label>
          <input type="hidden" name="variables" value="{}" />
          <details>
            <summary>模型设置</summary>
            <div className={styles.formInset}>
              <label>模型<input name="configured_model" defaultValue="deepseek-v4-flash" required /></label>
              <label>总调用预算<input name="model_call_budget" type="number" min="1" max="5" defaultValue="2" required /></label>
              <label>模型策略 Hash<input name="model_policy_hash" defaultValue={DEFAULT_MODEL_POLICY_HASH} pattern="[0-9a-f]{64}" required /></label>
            </div>
          </details>
        </ActionForm>
        {!canCreate ? <Empty>当前 Opportunity 缺少可用 Prompt 绑定、品牌、产品或证据。</Empty> : null}
        </>}
      </aside>
      <div className={styles.workspace}>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Technical preview history" title="预览记录" />
          <ResourceBlock resource={data.simulations}>{(items) => items.length
            ? <SimulationHistory projectId={projectId} data={data} items={items} />
            : <Empty>尚未运行提示词技术预览。</Empty>}</ResourceBlock>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Non-publishable result" title={simulation ? `预览 ${simulation.id.slice(0, 8)}` : "生成结果"}>
            {simulation ? <Status value={simulation.artifact_status} /> : null}
          </SectionHeader>
          {simulation ? <>
            {isLegacySimulation ? <div className={styles.testBanner} role="status">
              <strong>迁移历史 · 只读</strong>
              <span>legacy-v1 · 无 Campaign / Opportunity 绑定 · 仅供审计查看与工件下载</span>
            </div> : null}
            <div className={styles.keyValues}>
              <div><span className={styles.meta}>输入 Hash</span><br /><code>{simulation.input_hash.slice(0, 16)}</code></div>
              <div><span className={styles.meta}>输出 Hash</span><br /><code>{simulation.output_hash?.slice(0, 16) || "pending"}</code></div>
              <div><span className={styles.meta}>Job</span><br /><ShortId value={simulation.generation_job_id} /></div>
              <div><span className={styles.meta}>Prompt binding</span><br />
                <strong>{simulation.prompt_release_binding_version === null
                  ? "legacy-v1" : `v${simulation.prompt_release_binding_version}`}</strong><br />
                <ShortId value={simulation.prompt_release_binding_id} /></div>
              <div><span className={styles.meta}>Release</span><br /><strong>v{simulation.release_version}</strong><br /><code>{simulation.release_hash.slice(0, 16)}</code></div>
            </div>
            <p className={styles.meta}>模拟身份：{simulation.authenticity_mode}</p>
            <div className={styles.testBanner} role="status"><strong>NON-PUBLISHABLE</strong>
              <span>test_only={String(simulation.test_only)} · publication_eligible={String(simulation.publication_eligible)}</span></div>
            {simulation.simulation_purpose === "geo_question_test" ? <div className={styles.keyValues}>
              <div><span>QuestionSet</span><br /><ShortId value={simulation.question_set_id} /></div>
              <div><span>QuestionSet Hash</span><br /><code>{simulation.question_set_hash?.slice(0, 16)}</code></div>
              <div><span>问题项</span><br /><ShortId value={simulation.question_set_item_id} /></div>
            </div> : null}
            {renderedText ? <div className={styles.content}>{renderedText}</div> : <Empty>模型任务完成并 finalize 后显示正文。</Empty>}
            {claims !== undefined ? <details><summary>Claim inventory</summary><pre className={styles.code}>{JSON.stringify(claims, null, 2)}</pre></details> : null}
            {simulation.input_snapshot ? <details><summary>冻结输入快照</summary><pre className={styles.code}>{JSON.stringify(simulation.input_snapshot, null, 2)}</pre></details> : null}
            {simulation.artifact_status === "finalized" ? <Link className="button secondary"
              href={simulationDownloadHref(projectId, simulation)}>下载 TEST ONLY 工件</Link> : null}
          </> : <Empty>选择一条预览记录查看冻结输入和生成结果。</Empty>}
        </div>
      </div>
    </div>
  </div>;
}

function SimulationHistory({ projectId, data, items }: {
  projectId: string;
  data: GeoWorkspaceData;
  items: PromptSimulationView[];
}) {
  const current = items.filter((item) => item.campaign_id !== null);
  const legacy = items.filter((item) => item.campaign_id === null);
  return <div className={styles.historyGroups}>
    {current.length ? <SimulationHistoryGroup
      data={data} items={current} label="当前 Campaign" projectId={projectId} /> : null}
    {legacy.length ? <SimulationHistoryGroup
      data={data} items={legacy} label="迁移历史（只读）" projectId={projectId} legacy /> : null}
  </div>;
}

function SimulationHistoryGroup({ projectId, data, items, label, legacy = false }: {
  projectId: string;
  data: GeoWorkspaceData;
  items: PromptSimulationView[];
  label: string;
  legacy?: boolean;
}) {
  const { selection } = data;
  return <section className={styles.historyGroup}>
    <h3>{label} · {items.length}</h3>
    <div className={styles.list}>{items.map((item) => <Link
      key={item.id}
      className={item.id === selection.simulationId ? styles.selectedRow : styles.row}
      href={geoHref(projectId, selection, {
        simulation_id: item.id,
        job_id: item.campaign_id ? item.generation_job_id : undefined
      })}>
      <span className={styles.rowHeader}><strong>{legacy ? "历史只读" : "TEST ONLY"} · <ShortId value={item.id} /></strong>
        <Status value={item.generation_status} /></span>
      <span className={styles.meta}><span>{destinationName(data, item)}</span>
        <span>{item.simulation_purpose}</span><span>{item.authenticity_mode}</span>
        <span>{item.configured_model}</span><span>{new Date(item.created_at).toLocaleString("zh-CN")}</span></span>
    </Link>)}</div>
  </section>;
}

function simulationDownloadHref(projectId: string, simulation: PromptSimulationView): string {
  const path = `/projects/${encodeURIComponent(projectId)}/simulation-download/${encodeURIComponent(simulation.id)}`;
  return simulation.campaign_id
    ? `${path}?${new URLSearchParams({ campaign_id: simulation.campaign_id }).toString()}`
    : path;
}

function objectValue(value: JsonValue | undefined): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function stringValue(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function evidenceLabel(text: string | null, fallback: string): string {
  const normalized = text?.replace(/\s+/g, " ").trim();
  return normalized ? normalized.slice(0, 72) : fallback;
}

function destinationName(data: GeoWorkspaceData, simulation: PromptSimulationView): string {
  const destination = data.destinations.data.find((item) => item.id === simulation.destination_id);
  return destination ? `${destination.publication_channel} · ${destination.destination_key}` : simulation.destination_id.slice(0, 8);
}
