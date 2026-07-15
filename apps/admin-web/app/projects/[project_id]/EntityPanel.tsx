import { EntityCreateForm } from "./EntityCreateForm";
import type { CatalogResource, CatalogEntity } from "./catalogTypes";
import { ResourceProblem } from "./ResourceProblem";
import styles from "./Catalog.module.css";

export function EntityPanel({
  projectId,
  resource
}: {
  projectId: string;
  resource: CatalogResource<CatalogEntity[]>;
}) {
  return (
    <section className={styles.section} id="entities">
      <header className={styles.sectionHeader}>
        <div><p>Subject ownership</p><h2>品牌、产品与竞品实体</h2></div>
        <span className={styles.badge}>{resource.data.length} 个实体</span>
      </header>
      <EntityCreateForm projectId={projectId} />
      {resource.problem ? <ResourceProblem label="实体" problem={resource.problem} /> : null}
      {!resource.problem && !resource.data.length ? <div className={styles.empty}>暂无实体。</div> : null}
      {resource.data.length ? (
        <div className={styles.list}>
          {resource.data.map((entity) => (
            <article className={styles.row} key={entity.id}>
              <div className={styles.rowMain}>
                <strong>{entity.canonical_name}</strong>
                {entity.canonical_url ? <a href={entity.canonical_url}>{entity.canonical_url}</a> : <small>未设置规范 URL</small>}
              </div>
              <div className={styles.rowMeta}><span>{entityTypeLabel(entity.entity_type)}</span><small>{entity.status}</small></div>
              <div className={styles.rowMeta}><code>{entity.id}</code><small>{JSON.stringify(entity.attributes)}</small></div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function entityTypeLabel(type: string): string {
  if (type === "brand") return "品牌";
  if (type === "product") return "产品";
  if (type === "competitor") return "竞品";
  return "市场";
}
