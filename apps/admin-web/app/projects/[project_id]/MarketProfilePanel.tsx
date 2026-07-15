import { MarketProfileCreateForm } from "./MarketProfileCreateForm";
import type { CatalogResource, MarketProfile } from "./catalogTypes";
import { ResourceProblem } from "./ResourceProblem";
import styles from "./Catalog.module.css";

export function MarketProfilePanel({
  projectId,
  resource
}: {
  projectId: string;
  resource: CatalogResource<MarketProfile[]>;
}) {
  return (
    <section className={styles.section} id="markets">
      <header className={styles.sectionHeader}>
        <div><p>Regional rules</p><h2>市场配置</h2></div>
        <span className={styles.badge}>{resource.data.length} 个市场</span>
      </header>
      <MarketProfileCreateForm projectId={projectId} />
      {resource.problem ? <ResourceProblem label="市场配置" problem={resource.problem} /> : null}
      {!resource.problem && !resource.data.length ? <div className={styles.empty}>暂无市场配置。</div> : null}
      {resource.data.length ? (
        <div className={styles.list}>
          {resource.data.map((market) => (
            <article className={styles.row} key={market.id}>
              <div className={styles.rowMain}><strong>{market.market_code}</strong><small>{market.id}</small></div>
              <div className={styles.rowMeta}><span>{market.locale}</span><span>{market.timezone}</span></div>
              <div className={styles.rowMeta}><small>{JSON.stringify(market.rules)}</small><small>{market.status}</small></div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
