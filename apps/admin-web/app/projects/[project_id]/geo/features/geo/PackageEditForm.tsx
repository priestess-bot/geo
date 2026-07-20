"use client";

import { useMemo, useState } from "react";
import type { ClaimView, PackageVersionView } from "@geo/types/geo";
import { ActionForm } from "./ActionForm";
import { editPackage } from "./placement-actions";
import styles from "./GeoWorkspace.module.css";

export function PackageEditForm({ campaignId, projectId, version, claims }: {
  campaignId: string; projectId: string; version: PackageVersionView; claims: ClaimView[];
}) {
  const [text, setText] = useState(version.rendered_text);
  const [requiredDisclosures, setRequiredDisclosures] = useState(() =>
    stringArray(version.content_json.required_disclosures).join("\n")
  );
  const [expectedLinks, setExpectedLinks] = useState(() =>
    stringArray(version.content_json.expected_links).join("\n")
  );
  const [items, setItems] = useState(() => claims.map((claim) => ({
    text: claim.claim_text,
    kind: claim.claim_kind,
    support_status: claim.support_status,
    evidence_item_ids: claim.evidence_item_ids
  })));
  const claimsJson = useMemo(() => JSON.stringify(items), [items]);
  const contentJson = useMemo(() => JSON.stringify({
    ...version.content_json,
    required_disclosures: lines(requiredDisclosures),
    expected_links: lines(expectedLinks),
    rendered_text: text
  }), [expectedLinks, requiredDisclosures, text, version.content_json]);
  return <ActionForm action={editPackage} submitLabel="保存为新版本">
    <input name="project_id" type="hidden" value={projectId} /><input name="campaign_id" type="hidden" value={campaignId} /><input name="package_id" type="hidden" value={version.package_id} /><input name="base_version_id" type="hidden" value={version.id} /><input name="base_content_hash" type="hidden" value={version.content_hash} />
    <input name="content_json" type="hidden" value={contentJson} /><input name="claims" type="hidden" value={claimsJson} />
    <label>文案正文<textarea name="rendered_text" required value={text} onChange={(event) => setText(event.target.value)} /></label>
    <label>必需披露文本<textarea value={requiredDisclosures} onChange={(event) => setRequiredDisclosures(event.target.value)} /></label>
    <label>预期公开链接<textarea value={expectedLinks} onChange={(event) => setExpectedLinks(event.target.value)} /></label>
    <fieldset><legend>事实与表述清单</legend>{items.map((item, index) => <div className={styles.claimEditor} key={`${index}-${item.evidence_item_ids.join("-")}`}>
      <label>表述<input value={item.text} onChange={(event) => setItems((current) => current.map((candidate, candidateIndex) => candidateIndex === index ? { ...candidate, text: event.target.value } : candidate))} /></label>
      <div className={styles.inline}><label>类型<select value={item.kind} onChange={(event) => setItems((current) => current.map((candidate, candidateIndex) => candidateIndex === index ? { ...candidate, kind: event.target.value } : candidate))}><option value="factual">事实</option><option value="comparative">比较</option><option value="experience">体验</option><option value="non_factual">非事实表达</option></select></label>
        <label>证据状态<select value={item.support_status} onChange={(event) => setItems((current) => current.map((candidate, candidateIndex) => candidateIndex === index ? { ...candidate, support_status: event.target.value } : candidate))}><option value="supported">已有证据</option><option value="unsupported">缺少证据</option><option value="conflict">证据冲突</option><option value="not_required">无需证据</option></select></label></div>
      <small>{item.evidence_item_ids.length} 条证据引用</small>
    </div>)}</fieldset>
    <label>修改原因<input name="reason" required placeholder="例如：客户要求调整语气，未改变事实含义" /></label>
  </ActionForm>;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
