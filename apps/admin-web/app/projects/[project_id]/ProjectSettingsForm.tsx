"use client";

import { useActionState } from "react";

import { updateProjectAction } from "./catalogActions";
import { CatalogActionFeedback } from "./CatalogActionFeedback";
import { initialCatalogActionState } from "./catalogTypes";
import type { CatalogProject } from "../projectTypes";
import styles from "./Catalog.module.css";

export function ProjectSettingsForm({ project }: { project: CatalogProject }) {
  const [state, action, pending] = useActionState(
    updateProjectAction,
    initialCatalogActionState
  );
  return (
    <form action={action} className={styles.form}>
      <input type="hidden" name="project_id" value={project.id} />
      <div className={styles.formGrid}>
        <label className={styles.wide}>
          <span>项目名称</span>
          <input name="name" defaultValue={project.name} maxLength={200} required />
        </label>
        <label>
          <span>项目状态</span>
          <select name="status" defaultValue={project.status}>
            <option value="active">运行中</option>
            <option value="paused">已暂停</option>
            <option value="archived">已归档</option>
          </select>
        </label>
      </div>
      <div className={styles.formActions}>
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存项目"}</button>
      </div>
      <CatalogActionFeedback state={state} />
    </form>
  );
}
