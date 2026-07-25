import type { ManagedMemberRole } from "../../memberTypes";
import {
  PromptBootstrapDraftForm,
  PromptBootstrapEvaluationForm
} from "./PromptBootstrapActions";
import type {
  PromptBootstrapCatalog,
  PromptBootstrapKindPreview
} from "./promptBootstrapTypes";
import type { PromptLoadProblem, PromptProgramKind } from "./promptProgramTypes";
import styles from "./PromptBootstrap.module.css";

export function PromptBootstrapCatalogPanel({
  catalog,
  currentRole,
  problem,
  projectId,
  selectedKind
}: {
  catalog: PromptBootstrapCatalog | null;
  currentRole: ManagedMemberRole | null;
  problem?: PromptLoadProblem;
  projectId: string;
  selectedKind: PromptProgramKind | null;
}) {
  const canManage = !problem && Boolean(catalog)
    && (currentRole === "owner" || currentRole === "admin");
  if (problem) return <CatalogProblem problem={problem} />;
  if (!catalog) {
    return <div className={styles.catalogEmpty}><strong>基线目录未加载</strong><span>没有创建任何草稿。</span></div>;
  }
  const selected = catalog.items.find((item) => item.program_kind === selectedKind)
    || catalog.items[0]
    || null;
  const fixtureCount = catalog.items.reduce((total, item) => total + item.fixtures.length, 0);
  return (
    <section className={styles.catalog} aria-labelledby="prompt-bootstrap-heading">
      <header className={styles.catalogHeader}>
        <div><p>不可变基线预览</p><h3 id="prompt-bootstrap-heading">基线目录（草稿初始化）</h3></div>
        <div className={styles.summary}>
          <span><strong>{catalog.items.length}</strong> 个类型</span>
          <span><strong>{fixtureCount}</strong> 个固定用例</span>
          <span><strong>0</strong> 次模型调用</span>
        </div>
      </header>
      <dl className={styles.catalogFacts}>
        <Fact label="目录版本" value={catalog.catalog_version} />
        <Fact label="目录 SHA-256" value={catalog.catalog_hash} />
        <Fact label="批处理原子性" value={catalog.batch_atomicity} />
        <Fact label="操作边界" value={catalog.action_boundary} />
      </dl>
      <div className={styles.boundaryNotice}>
        <strong>目录不是批准结果</strong>
        <span>预览不写库；批量操作只创建 v1 草稿，仍需人工测试、批准、冻结与绑定。</span>
      </div>
      <div className={styles.desktopCatalogTable}>
        <CatalogTable catalog={catalog} projectId={projectId} selectedKind={selected?.program_kind || null} />
      </div>
      <MobileCatalogNavigator
        catalog={catalog}
        projectId={projectId}
        selectedKind={selected?.program_kind || null}
      />
      {selected ? <KindDetail catalog={catalog} canManage={canManage} item={selected} projectId={projectId} /> : (
        <div className={styles.catalogEmpty}><strong>目录没有可检查的类型</strong></div>
      )}
      <PromptBootstrapDraftForm canManage={canManage} catalogHash={catalog.catalog_hash} projectId={projectId} />
    </section>
  );
}

function MobileCatalogNavigator({
  catalog,
  projectId,
  selectedKind
}: {
  catalog: PromptBootstrapCatalog;
  projectId: string;
  selectedKind: PromptProgramKind | null;
}) {
  return (
    <details className={styles.mobileCatalogNavigator}>
      <summary>选择基线类型</summary>
      <form action={`/projects/${encodeURIComponent(projectId)}`} method="get">
        <input name="tab" type="hidden" value="prompts" />
        <label>
          <span>类型</span>
          <select defaultValue={selectedKind || ""} name="prompt_bootstrap_kind">
            {catalog.items.map((item) => (
              <option key={item.program_kind} value={item.program_kind}>
                {item.program_kind} · {item.purpose}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">查看类型</button>
      </form>
      <details className={styles.mobileCatalogTable}>
        <summary>查看全部类型合同</summary>
        <CatalogTable catalog={catalog} projectId={projectId} selectedKind={selectedKind} />
      </details>
    </details>
  );
}

function CatalogTable({ catalog, projectId, selectedKind }: {
  catalog: PromptBootstrapCatalog;
  projectId: string;
  selectedKind: PromptProgramKind | null;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.catalogTable}>
        <thead><tr><th>类型 / 用途</th><th>规范 SHA-256</th><th>测试集 SHA-256</th><th>门槛</th><th>操作</th></tr></thead>
        <tbody>{catalog.items.map((item) => (
          <tr className={item.program_kind === selectedKind ? styles.activeRow : undefined} key={item.program_kind}>
            <td><strong>{item.program_kind}</strong><span>{item.purpose}</span><small>{item.fixtures.length} 个固定用例 · {item.rubric.length} 项标准</small></td>
            <td><code>{item.spec_hash}</code></td>
            <td><code>{item.test_set_hash}</code><small>{item.test_set_id} · v{item.test_set_version}</small></td>
            <td>{item.minimum_score} / 100</td>
            <td><a href={kindHref(projectId, item.program_kind)}>检查</a></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function KindDetail({ catalog, canManage, item, projectId }: {
  catalog: PromptBootstrapCatalog;
  canManage: boolean;
  item: PromptBootstrapKindPreview;
  projectId: string;
}) {
  return (
    <section className={styles.kindDetail} aria-labelledby="prompt-bootstrap-kind-heading">
      <div className={styles.sectionHeading}>
        <div><p>{item.spec_version}</p><h4 id="prompt-bootstrap-kind-heading">{item.program_kind}</h4></div>
        <span>最低 {item.minimum_score} / 100</span>
      </div>
      <dl className={styles.kindFacts}>
        <Fact label="用途" value={item.purpose} />
        <Fact label="输入 / 输出 Schema" value={`${item.input_schema_version} · ${item.output_schema_version}`} />
        <Fact label="模型策略" value={`${item.model_policy_version} · ${item.model_policy_hash}`} />
        <Fact label="规范 / 测试 SHA-256" value={`${item.spec_hash} · ${item.test_set_hash}`} />
      </dl>
      <details className={styles.disclosure}>
        <summary>评分标准（权重合计 100）</summary>
        <div className={styles.rubricGrid}>{item.rubric.map((criterion) => (
          <article key={criterion.code}>
            <header><strong>{criterion.code}</strong><span>{criterion.weight}</span></header>
            <p>{criterion.description}</p>
            <small>{criterion.blocking ? "阻断项" : "非阻断项"}</small>
          </article>
        ))}</div>
      </details>
      <details className={styles.disclosure}>
        <summary>固定用例（5）</summary>
        <div className={styles.fixtureGrid}>{item.fixtures.map((fixture) => (
          <article key={fixture.fixture_id}>
            <header><strong>{fixture.scenario}</strong><code>{fixture.fixture_id}</code></header>
            <p>{fixture.description}</p>
            <details><summary>冻结输入</summary><pre>{JSON.stringify(fixture.input_value, null, 2)}</pre></details>
          </article>
        ))}</div>
      </details>
      <details className={styles.disclosure}>
        <summary>输出 Schema 与应用规则</summary>
        <pre>{JSON.stringify(item.output_schema, null, 2)}</pre>
        <ol>{item.application_rules.map((rule) => <li key={rule}>{rule}</li>)}</ol>
      </details>
      <PromptBootstrapEvaluationForm
        canManage={canManage}
        catalogHash={catalog.catalog_hash}
        fixtureIds={item.fixtures.map((fixture) => fixture.fixture_id)}
        programKind={item.program_kind}
        projectId={projectId}
        specHash={item.spec_hash}
        testSetHash={item.test_set_hash}
      />
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function CatalogProblem({ problem }: { problem: PromptLoadProblem }) {
  const unavailable = problem.status === 503;
  return (
    <section className={styles.catalogProblem} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{unavailable ? "Prompt 基线目录暂不可用" : "Prompt 基线目录加载失败"}</strong>
      <span>{problem.detail}</span>
      <small>未创建任何草稿；负责人和管理员操作保持关闭。</small>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </section>
  );
}

function kindHref(projectId: string, kind: PromptProgramKind): string {
  const params = new URLSearchParams({ tab: "prompts", prompt_bootstrap_kind: kind });
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}
