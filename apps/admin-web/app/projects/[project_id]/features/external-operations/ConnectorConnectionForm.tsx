"use client";

import { useState } from "react";

import { ActionForm } from "../../geo/features/geo/ActionForm";
import { externalOperation } from "./externalOperationsActions";
import type { ConnectorDefinition } from "./externalOperationsTypes";
import styles from "./ExternalOperations.module.css";

const SECRET_PURPOSE_BY_KIND: Record<string, string> = {
  google_search_console: "connector.gsc",
  google_analytics_4: "connector.ga4"
};

export function ConnectorConnectionForm({
  approved, projectId
}: { approved: ConnectorDefinition[]; projectId: string }) {
  const [definitionId, setDefinitionId] = useState(approved[0]?.id || "");
  const selectedDefinition = approved.find((item) => item.id === definitionId) || approved[0];
  const secretPurpose = selectedDefinition
    ? SECRET_PURPOSE_BY_KIND[selectedDefinition.kind] || ""
    : "";

  return <ActionForm action={externalOperation} submitLabel="创建连接" disabled={!approved.length}>
    <input name="project_id" type="hidden" value={projectId} />
    <input name="command" type="hidden" value="create_connection" />
    <label>已批准定义<select
      name="definition_id"
      required
      value={selectedDefinition?.id || ""}
      onChange={(event) => setDefinitionId(event.target.value)}
      data-testid="connector-definition-select"
    >{approved.map((item) => <option key={item.id} value={item.id}>{connectorLabel(item.kind)}</option>)}</select></label>
    <label>连接名称<input name="name" required /></label>
    <label>密钥引用 ID<input name="secret_reference_id" required /></label>
    <label>密钥用途（自动绑定）<input
      name="secret_purpose"
      value={secretPurpose}
      readOnly
      aria-readonly="true"
      data-testid="connector-secret-purpose"
    /></label>
    <p className={styles.empty}>用途由已批准的 GSC/GA4 定义自动决定，不能手工修改。</p>
    <label>密钥版本<input name="secret_version" type="number" min="1" defaultValue="1" required /></label>
  </ActionForm>;
}

function connectorLabel(kind: string): string {
  return kind === "google_analytics_4" ? "Google Analytics 4" : "Google Search Console";
}
