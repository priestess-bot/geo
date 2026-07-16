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
  const brands = catalog.entities.data.filter((item) => item.entity_type === "brand");
  const products = catalog.entities.data.filter((item) => item.entity_type === "product");
  const evidence = catalog.evidence.data.filter((item) => item.eligible_for_generation);
  const destinationReleases = data.destinations.data.flatMap((destination) => data.bindings.data
    .filter((binding) => binding.task_key === destination.publication_channel)
    .map((binding) => ({ destination, binding })));
  const output = objectValue(simulation?.artifact_manifest?.output);
  const renderedText = stringValue(output?.rendered_text);
  const claims = output?.claims;
  const canCreate = destinationReleases.length > 0 && brands.length > 0 && products.length > 0 && evidence.length > 0;

  return <div className={styles.workspace}>
    <div className={styles.testBanner} role="status">
      <strong>TEST ONLY</strong>
      <span>技术预览不可用于正式审查、导出或发布 · publication_eligible=false</span>
    </div>
    <div className={styles.split}>
      <aside className={`${styles.panel} ${styles.sticky}`}>
        <SectionHeader eyebrow="Isolated preview input" title="提示词技术预览" />
        <ActionForm action={createPromptSimulation} submitLabel="运行 TEST ONLY 预览" disabled={!canCreate}>
          <HiddenProject projectId={projectId} />
          <label>渠道与 Prompt Release
            <select name="destination_release" required defaultValue={destinationReleases[0]
              ? `${destinationReleases[0].destination.id}:${destinationReleases[0].binding.template_release_id}` : ""}>
              {destinationReleases.map(({ destination, binding }) => <option
                key={`${destination.id}:${binding.template_release_id}`}
                value={`${destination.id}:${binding.template_release_id}`}>
                {destination.publication_channel} · {destination.destination_key} · Release {binding.template_release_id.slice(0, 8)}
              </option>)}
            </select>
          </label>
          <label>主品牌
            <select name="primary_brand_entity_id" required defaultValue={brands[0]?.id || ""}>
              {brands.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}
            </select>
          </label>
          <label>产品
            <select name="product_entity_id" required defaultValue={products[0]?.id || ""}>
              {products.map((item) => <option key={item.id} value={item.id}>{item.canonical_name}</option>)}
            </select>
          </label>
          <label>治理合格证据（可多选）
            <select className={styles.multiSelect} name="evidence_item_ids" required multiple size={Math.min(Math.max(evidence.length, 3), 8)}>
              {evidence.map((item) => <option key={item.id} value={item.id}>
                {item.item_type} · {item.subject_role} · {evidenceLabel(item.snapshot.text, item.source_id)}
              </option>)}
            </select>
          </label>
          <label>生成目标 JSON<textarea name="goals" required defaultValue={'{"intent":"product recommendation","audience":"Australian consumers","deliverable":"channel-specific draft"}'} /></label>
          <label>约束 JSON<textarea name="constraints" defaultValue={'{"test_only":true,"unsupported_superlatives":false,"public_citations_required":true}'} /></label>
          <label>Prompt 客户变量 JSON<textarea name="variables" defaultValue="{}" /></label>
          <details>
            <summary>模型设置</summary>
            <div className={styles.formInset}>
              <label>模型<input name="configured_model" defaultValue="deepseek-v4-flash" required /></label>
              <label>总调用预算<input name="model_call_budget" type="number" min="1" max="5" defaultValue="2" required /></label>
              <label>模型策略 Hash<input name="model_policy_hash" defaultValue={DEFAULT_MODEL_POLICY_HASH} pattern="[0-9a-f]{64}" required /></label>
            </div>
          </details>
        </ActionForm>
        {!canCreate ? <Empty>需要至少一个渠道 Prompt 绑定、品牌、产品和可生成证据。</Empty> : null}
      </aside>
      <div className={styles.workspace}>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Technical preview history" title="预览记录" />
          <ResourceBlock resource={data.simulations}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link
            key={item.id}
            className={item.id === selection.simulationId ? styles.selectedRow : styles.row}
            href={geoHref(projectId, selection, { simulation_id: item.id, job_id: item.generation_job_id })}>
            <span className={styles.rowHeader}><strong>TEST ONLY · <ShortId value={item.id} /></strong><Status value={item.generation_status} /></span>
            <span className={styles.meta}><span>{destinationName(data, item)}</span><span>{item.configured_model}</span><span>{new Date(item.created_at).toLocaleString("zh-CN")}</span></span>
          </Link>)}</div> : <Empty>尚未运行提示词技术预览。</Empty>}</ResourceBlock>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Non-publishable result" title={simulation ? `预览 ${simulation.id.slice(0, 8)}` : "生成结果"}>
            {simulation ? <Status value={simulation.artifact_status} /> : null}
          </SectionHeader>
          {simulation ? <>
            <div className={styles.keyValues}>
              <div><span className={styles.meta}>输入 Hash</span><br /><code>{simulation.input_hash.slice(0, 16)}</code></div>
              <div><span className={styles.meta}>输出 Hash</span><br /><code>{simulation.output_hash?.slice(0, 16) || "pending"}</code></div>
              <div><span className={styles.meta}>Job</span><br /><ShortId value={simulation.generation_job_id} /></div>
            </div>
            {renderedText ? <div className={styles.content}>{renderedText}</div> : <Empty>模型任务完成并 finalize 后显示正文。</Empty>}
            {claims !== undefined ? <details><summary>Claim inventory</summary><pre className={styles.code}>{JSON.stringify(claims, null, 2)}</pre></details> : null}
            {simulation.input_snapshot ? <details><summary>冻结输入快照</summary><pre className={styles.code}>{JSON.stringify(simulation.input_snapshot, null, 2)}</pre></details> : null}
            {simulation.artifact_status === "finalized" ? <Link className="button secondary" href={`/projects/${projectId}/simulation-download/${simulation.id}`}>下载 TEST ONLY 工件</Link> : null}
          </> : <Empty>选择一条预览记录查看冻结输入和生成结果。</Empty>}
        </div>
      </div>
    </div>
  </div>;
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
