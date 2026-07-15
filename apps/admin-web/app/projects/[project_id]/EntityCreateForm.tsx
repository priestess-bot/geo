"use client";

import { useActionState } from "react";

import { createEntityAction } from "./catalogActions";
import { CatalogActionFeedback } from "./CatalogActionFeedback";
import { entityTypes, initialCatalogActionState } from "./catalogTypes";
import styles from "./Catalog.module.css";

export function EntityCreateForm({ projectId }: { projectId: string }) {
  const [state, action, pending] = useActionState(
    createEntityAction,
    initialCatalogActionState
  );
  return (
    <form action={action} className={styles.form}>
      <input type="hidden" name="project_id" value={projectId} />
      <div className={styles.formGrid}>
        <label>
          <span>实体类型</span>
          <select name="entity_type" defaultValue="brand">
            {entityTypes.map((type) => <option key={type} value={type}>{entityTypeLabel(type)}</option>)}
          </select>
        </label>
        <label>
          <span>规范名称</span>
          <input name="canonical_name" maxLength={300} required />
        </label>
        <label>
          <span>规范 URL</span>
          <input name="canonical_url" type="url" maxLength={2000} placeholder="https://..." />
        </label>
        <label className={styles.wide}>
          <span>扩展属性（JSON object）</span>
          <textarea name="attributes" defaultValue="{}" spellCheck={false} />
        </label>
      </div>
      <div className={styles.formActions}>
        <button type="submit" disabled={pending}>{pending ? "添加中..." : "添加实体"}</button>
      </div>
      <CatalogActionFeedback state={state} />
    </form>
  );
}

function entityTypeLabel(type: string): string {
  if (type === "brand") return "主品牌";
  if (type === "product") return "产品";
  if (type === "competitor") return "竞品";
  return "市场主体";
}
