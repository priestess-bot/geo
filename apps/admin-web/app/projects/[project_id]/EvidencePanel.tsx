import { EvidenceCreateForm } from "./EvidenceCreateForm";
import type { CatalogEntity, CatalogResource, EvidenceItem } from "./catalogTypes";
import { ResourceProblem } from "./ResourceProblem";
import styles from "./Catalog.module.css";

export function EvidencePanel({
  entities,
  projectId,
  resource
}: {
  entities: CatalogEntity[];
  projectId: string;
  resource: CatalogResource<EvidenceItem[]>;
}) {
  return (
    <section className={styles.section} id="evidence">
      <header className={styles.sectionHeader}>
        <div><p>证据治理</p><h2>事实与消费者使用描述</h2></div>
        <span className={styles.badge}>{resource.data.length} 条证据</span>
      </header>
      <EvidenceCreateForm
        entities={entities.map(({ id, entity_type, canonical_name }) => ({ id, entity_type, canonical_name }))}
        projectId={projectId}
      />
      {resource.problem ? <ResourceProblem label="证据" problem={resource.problem} /> : null}
      {!resource.problem && !resource.data.length ? <div className={styles.empty}>暂无证据。</div> : null}
      {resource.data.length ? (
        <div className={styles.list}>
          {resource.data.map((item) => (
            <article className={styles.row} key={item.id}>
              <div className={styles.rowMain}>
                <strong>{evidenceLabel(item.item_type)}</strong>
                <p className={styles.snapshot}>{item.snapshot.text || item.snapshot.uri || "无快照"}</p>
              </div>
              <div className={styles.rowMeta}>
                <span>{item.subject_role}</span>
                <span>{item.usage_rights} · {item.confidentiality}</span>
                <small>修订版本：{item.source_revision.kind} / {item.source_revision.value}</small>
              </div>
              <div className={styles.rowMeta}>
                <div className={styles.badges}>
                  <span className={styles.badge}>生成：{item.eligible_for_generation ? "可用" : "阻断"}</span>
                  <span className={styles.badge}>发布：{item.eligible_for_publication ? "可用" : "阻断"}</span>
                </div>
                <code>{item.id}</code>
                <small>SHA-256: {item.snapshot.sha256}</small>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function evidenceLabel(type: string): string {
  return type === "consumer_experience" ? "真实消费者使用描述" : type;
}
