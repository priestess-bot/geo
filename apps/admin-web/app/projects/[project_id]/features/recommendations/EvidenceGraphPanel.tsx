import type {
  EvidenceGraph,
  InputVersion,
  Recommendation,
  VersionedEvidenceRef
} from "./recommendationTypes";
import styles from "./Recommendations.module.css";

type EvidenceGroup = Readonly<{
  key: string;
  label: string;
  items: readonly VersionedEvidenceRef[];
}>;

export function EvidenceGraphPanel({ recommendation }: { recommendation: Recommendation }) {
  const graph = recommendation.evidence;
  const groups: EvidenceGroup[] = [
    { key: "observations", label: "真实观测 / 投影", items: graph.observations },
    { key: "metric-comparisons", label: "统计比较", items: graph.metric_comparisons },
    { key: "facts", label: "批准事实", items: graph.facts },
    { key: "rules", label: "规则版本", items: graph.rules },
    { key: "prompt-releases", label: "Prompt 发布版本", items: graph.prompt_releases },
    { key: "model-calls", label: "模型调用", items: graph.model_calls },
    { key: "contents", label: "内容版本", items: graph.contents },
    { key: "questions", label: "问题版本", items: graph.questions },
    { key: "surfaces", label: "界面发布版本", items: graph.surfaces }
  ];
  const referenceCount = groups.reduce((total, group) => total + group.items.length, 0);
  return (
    <section className={styles.evidenceSection} aria-labelledby="recommendation-evidence-heading">
      <div className={styles.sectionHeading}>
        <div>
          <p>冻结溯源</p>
          <h3 id="recommendation-evidence-heading">证据图与输入版本</h3>
        </div>
        <span>{referenceCount} 条证据 · {recommendation.input_versions.length} 个输入</span>
      </div>

      <HashSummary recommendation={recommendation} />
      <ScopeView graph={graph} />
      <DecisionView graph={graph} />

      <div className={styles.evidenceGroups}>
        {groups.map((group) => <EvidenceGroupView group={group} key={group.key} />)}
      </div>

      <InputVersions inputs={recommendation.input_versions} />
    </section>
  );
}

function HashSummary({ recommendation }: { recommendation: Recommendation }) {
  return (
    <dl className={styles.hashGrid}>
      <Value label="证据图谱 SHA-256" value={recommendation.evidence_graph_hash} />
      <Value label="输入指纹" value={recommendation.input_fingerprint} />
      <Value label="建议 ID" value={recommendation.id} />
      <Value label="适用版本" value={recommendation.evidence.scope.applicable_version} />
    </dl>
  );
}

function ScopeView({ graph }: { graph: EvidenceGraph }) {
  const scope = graph.scope;
  return (
    <details className={styles.detailDisclosure} open>
      <summary>证据作用域</summary>
      <dl className={styles.scopeGrid}>
        <Value label="项目" value={scope.project_id} />
        <Value label="Campaign" value={scope.campaign_id || "未限定"} />
        <Value label="问题 / 聚类" value={scope.question_or_cluster_ref || "未限定"} />
        <Value label="界面" value={scope.surface_ref || "未限定"} />
        <Value label="内容资产" value={scope.content_asset_ref || "未限定"} />
        <Value label="URL" value={scope.url_ref || "未限定"} />
      </dl>
    </details>
  );
}

function DecisionView({ graph }: { graph: EvidenceGraph }) {
  const decision = graph.decision;
  return (
    <details className={styles.detailDisclosure} open>
      <summary>可解释决策</summary>
      <dl className={styles.decisionGrid}>
        <TextValue label="风险" value={decision.risk} />
        <TextValue label="工作量" value={decision.effort} />
        <TextValue label="业务价值" value={decision.business_value} />
        <TextValue label="置信度" value={decision.confidence} />
      </dl>
      <div className={styles.decisionLists}>
        <StringList label="影响链" values={decision.impact_chain} />
        <StringList label="反证" values={decision.counterevidence} empty="无已登记反证" />
        <StringList label="验证计划" values={decision.validation_plan} />
        <StringList label="失效条件" values={decision.stale_conditions} />
      </div>
    </details>
  );
}

function EvidenceGroupView({ group }: { group: EvidenceGroup }) {
  return (
    <details className={styles.evidenceGroup}>
      <summary><span>{group.label}</span><strong>{group.items.length}</strong></summary>
      {group.items.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.evidenceTable}>
            <thead><tr><th>资源 / 版本</th><th>有效性</th><th>SHA-256</th><th>定位与属性</th></tr></thead>
            <tbody>{group.items.map((item, index) => (
              <tr key={`${item.resource_id}:${item.version}:${index}`}>
                <td><code>{item.resource_id}</code><small>v {item.version}</small></td>
                <td><span className={item.valid ? styles.validEvidence : styles.invalidEvidence}>{item.valid ? "有效" : "无效"}</span></td>
                <td><code>{item.sha256}</code></td>
                <td><EvidenceMetadata item={item} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className={styles.inlineEmpty}>此证据图未引用该类别。</p>}
    </details>
  );
}

function EvidenceMetadata({ item }: { item: VersionedEvidenceRef }) {
  const metadata = Object.entries(item as unknown as Record<string, unknown>)
    .filter(([key]) => !["project_id", "resource_id", "version", "sha256", "valid", "locator"].includes(key));
  return (
    <div className={styles.metadata}>
      {metadata.map(([key, value]) => (
        <span key={key}><strong>{humanize(key)}</strong>{displayValue(value)}</span>
      ))}
      <details><summary>定位信息</summary><pre>{JSON.stringify(item.locator, null, 2)}</pre></details>
    </div>
  );
}

function InputVersions({ inputs }: { inputs: readonly InputVersion[] }) {
  return (
    <details className={styles.detailDisclosure} open>
      <summary>冻结输入版本（{inputs.length}）</summary>
      {inputs.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.inputTable}>
            <thead><tr><th>类型</th><th>资源</th><th>版本</th><th>SHA-256</th></tr></thead>
            <tbody>{inputs.map((input) => (
              <tr key={`${input.kind}:${input.resource_id}`}>
                <td>{humanize(input.kind)}</td>
                <td><code>{input.resource_id}</code></td>
                <td><code>{input.version}</code></td>
                <td><code>{input.sha256}</code></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className={styles.inlineEmpty}>没有冻结输入版本。</p>}
    </details>
  );
}

function Value({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function TextValue({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function StringList({ label, values, empty = "无" }: { label: string; values: readonly string[]; empty?: string }) {
  return (
    <section><h4>{label}</h4>{values.length
      ? <ol>{values.map((value, index) => <li key={`${value}:${index}`}>{value}</li>)}</ol>
      : <p>{empty}</p>}</section>
  );
}

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "[]";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value === null || value === undefined) return "空";
  return String(value);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
