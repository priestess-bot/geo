"use client";

import { useActionState } from "react";

import { createMarketProfileAction } from "./catalogActions";
import { CatalogActionFeedback } from "./CatalogActionFeedback";
import { initialCatalogActionState } from "./catalogTypes";
import styles from "./Catalog.module.css";

export function MarketProfileCreateForm({ projectId }: { projectId: string }) {
  const [state, action, pending] = useActionState(
    createMarketProfileAction,
    initialCatalogActionState
  );
  return (
    <form action={action} className={styles.form}>
      <input type="hidden" name="project_id" value={projectId} />
      <div className={styles.formGrid}>
        <label><span>市场代码</span><input name="market_code" pattern="[A-Za-z]{2}" maxLength={2} placeholder="AU" required /></label>
        <label><span>区域语言</span><input name="locale" placeholder="en-AU" required /></label>
        <label><span>时区</span><input name="timezone" placeholder="Australia/Sydney" required /></label>
        <label className={styles.wide}>
          <span>市场规则（JSON object）</span>
          <textarea name="rules" defaultValue="{}" spellCheck={false} />
        </label>
      </div>
      <div className={styles.formActions}>
        <button type="submit" disabled={pending}>{pending ? "添加中..." : "添加市场配置"}</button>
      </div>
      <CatalogActionFeedback state={state} />
    </form>
  );
}
