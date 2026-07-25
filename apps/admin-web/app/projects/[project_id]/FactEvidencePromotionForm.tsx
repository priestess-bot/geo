import type { CatalogEntity } from "./catalogTypes";
import { KnowledgeActionForm } from "./KnowledgeActionForm";
import { promoteKnowledgeFactEvidence } from "./knowledgeActions";
import type { FactEvidenceProposal } from "./knowledgeTypes";

export function FactEvidencePromotionForm({
  entities,
  projectId,
  proposal
}: {
  entities: CatalogEntity[];
  projectId: string;
  proposal: FactEvidenceProposal;
}) {
  const sourceUrl = proposal.defaults.source_url || "";
  return (
    <KnowledgeActionForm action={promoteKnowledgeFactEvidence} submitLabel="提升为正式 Evidence">
      <input name="project_id" type="hidden" value={projectId} />
      <input name="fact_id" type="hidden" value={proposal.fact.id} />
      <label>证据标题<input defaultValue={proposal.defaults.title} maxLength={500} name="title" required /></label>
      <label>事实主体<select defaultValue={defaultSubject(entities)} name="subject_assignment">
        <option value="neutral:">中立（不绑定实体）</option>
        {entities.map((entity) => <option key={entity.id} value={`${roleFor(entity.entity_type)}:${entity.id}`}>
          {entity.canonical_name} · {entityLabel(entity.entity_type)}
        </option>)}
      </select></label>
      <div>
        <label>使用权<select defaultValue={sourceUrl ? "public_reference" : "licensed"} name="usage_rights">
          <option value="owned">自有</option><option value="licensed">已授权</option>
          <option value="public_reference">公开引用</option>
        </select></label>
        <label>机密级别<select defaultValue={sourceUrl ? "public" : "internal"} name="confidentiality">
          <option value="public">公开</option><option value="internal">内部</option>
          <option value="confidential">机密</option>
        </select></label>
      </div>
      <label>公开来源 URL<input defaultValue={sourceUrl} name="source_url" type="url" /></label>
      <label>公开来源标题<input defaultValue={proposal.defaults.source_title} maxLength={500} name="source_title" /></label>
      <label>引用标签<input defaultValue={proposal.defaults.citation_label} maxLength={200} name="citation_label" /></label>
      <div>
        <label><input defaultChecked={Boolean(sourceUrl)} name="disclosure_allowed" type="checkbox" />允许公开披露</label>
        <label><input name="quotation_allowed" type="checkbox" />允许引用原文</label>
        <label><input defaultChecked name="attribution_required" type="checkbox" />必须署名</label>
      </div>
    </KnowledgeActionForm>
  );
}

function defaultSubject(entities: CatalogEntity[]): string {
  const entity = entities.find((item) => item.entity_type === "product") || entities[0];
  return entity ? `${roleFor(entity.entity_type)}:${entity.id}` : "neutral:";
}

function roleFor(entityType: CatalogEntity["entity_type"]): string {
  return entityType === "brand" ? "primary_brand" : entityType;
}

function entityLabel(entityType: CatalogEntity["entity_type"]): string {
  return ({ brand: "品牌", product: "产品", competitor: "竞品", market: "市场" })[entityType];
}
