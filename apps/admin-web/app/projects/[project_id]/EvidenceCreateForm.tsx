"use client";

import { useActionState } from "react";

import { createEvidenceAction } from "./catalogActions";
import { CatalogActionFeedback } from "./CatalogActionFeedback";
import {
  confidentialityValues,
  genericEvidenceItemTypes,
  initialCatalogActionState,
  subjectRoles,
  usageRightsValues,
  type CatalogEntity
} from "./catalogTypes";
import styles from "./Catalog.module.css";

type EntityOption = Pick<CatalogEntity, "id" | "entity_type" | "canonical_name">;

export function EvidenceCreateForm({
  entities,
  projectId
}: {
  entities: EntityOption[];
  projectId: string;
}) {
  const defaultEntity = entities.find((entity) => entity.entity_type === "brand") || entities[0];
  const defaultSubjectRole = defaultEntity ? subjectRoleFor(defaultEntity.entity_type) : "neutral";
  const [state, action, pending] = useActionState(
    createEvidenceAction,
    initialCatalogActionState
  );
  return (
    <form action={action} className={styles.form}>
      <input type="hidden" name="project_id" value={projectId} />
      <div className={styles.formGrid}>
        <label>
          <span>证据类型</span>
          <select name="item_type" defaultValue="citation">
            {genericEvidenceItemTypes.map((type) => <option key={type} value={type}>{evidenceTypeLabel(type)}</option>)}
          </select>
        </label>
        <label>
          <span>Source UUID</span>
          <input name="source_id" placeholder="00000000-0000-4000-8000-000000000000" required />
        </label>
        <label>
          <span>事实主体角色</span>
          <select name="subject_role" defaultValue={defaultSubjectRole}>
            {subjectRoles.map((role) => <option key={role} value={role}>{subjectRoleLabel(role)}</option>)}
          </select>
        </label>
        <label>
          <span>主体实体</span>
          <select name="subject_entity_id" defaultValue={defaultEntity?.id || ""}>
            <option value="">无（仅限 neutral）</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.canonical_name} · {entity.entity_type}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>来源版本类型</span>
          <select name="revision_kind" defaultValue="content_hash">
            <option value="content_hash">Content hash</option>
            <option value="row_version">Row version</option>
            <option value="report_version">Report version</option>
          </select>
        </label>
        <label>
          <span>来源版本值</span>
          <input name="revision_value" placeholder="sha256 / v1 / row-42" required />
        </label>
        <label>
          <span>使用权</span>
          <select name="usage_rights" defaultValue="owned">
            {usageRightsValues.map((right) => <option key={right} value={right}>{right}</option>)}
          </select>
        </label>
        <label>
          <span>机密级别</span>
          <select name="confidentiality" defaultValue="internal">
            {confidentialityValues.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className={styles.wide}>
          <span>证据描述</span>
          <textarea
            name="snapshot_text"
            maxLength={32768}
            placeholder="录入经过核对的事实或一段真实消费者使用描述。SHA-256 将由服务端计算。"
            required
          />
        </label>
        <label className={styles.wide}>
          <span>定位信息（JSON object）</span>
          <textarea name="locator" defaultValue="{}" spellCheck={false} />
        </label>
        <label><span>公开来源 URL</span><input name="source_url" type="url" /></label>
        <label><span>公开来源标题</span><input name="source_title" /></label>
        <label><span>引用标签</span><input name="citation_label" /></label>
      </div>
      <div className={styles.checkGrid}>
        <label><input type="checkbox" name="disclosure_allowed" />允许公开披露</label>
        <label><input type="checkbox" name="quotation_allowed" />允许引用原文</label>
        <label><input type="checkbox" name="attribution_required" />必须署名</label>
      </div>
      <div className={styles.formActions}>
        <button type="submit" disabled={pending}>{pending ? "录入中..." : "录入证据"}</button>
      </div>
      <CatalogActionFeedback state={state} />
    </form>
  );
}

function evidenceTypeLabel(type: string): string {
  if (type === "consumer_experience") return "真实消费者使用描述";
  if (type === "report_extract") return "报告节选";
  if (type === "source_asset") return "来源资产";
  if (type === "citation") return "公开引用";
  return "内容 Chunk";
}

function subjectRoleLabel(role: string): string {
  if (role === "primary_brand") return "主品牌";
  if (role === "competitor") return "竞品";
  if (role === "product") return "产品";
  if (role === "market") return "市场";
  return "中立";
}

function subjectRoleFor(entityType: CatalogEntity["entity_type"]): string {
  if (entityType === "brand") return "primary_brand";
  return entityType;
}
