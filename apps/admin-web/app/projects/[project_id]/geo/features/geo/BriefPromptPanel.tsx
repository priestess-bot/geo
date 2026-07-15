import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { bindPromptTask, buildEvidence, createBrief, createPromptBundle, createPromptRelease, createPromptSkill, installDefaultPromptCatalog } from "./placement-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";
import { DEFAULT_OUTPUT_SCHEMA, DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT, PROMPT_TASK_KEYS } from "./prompt-defaults";

export function BriefPromptPanel({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const opportunity = data.opportunities.data.find((item) => item.id === selection.opportunityId);
  const brief = data.briefs.data.find((item) => item.id === selection.briefVersionId);
  const readyAttempt = data.attempts.data.find((item) => item.id === selection.attemptId && item.status === "ready");
  const release = data.releases.data[data.releases.data.length - 1];
  return <div className={styles.workspace}>
    <div className={styles.columns}>
      <div className={styles.panel}>
        <SectionHeader eyebrow="1 · Content contract" title="Brief 版本" />
        <ResourceBlock resource={data.briefs}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.briefVersionId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { brief_version_id: item.id, attempt_id: undefined, bundle_id: undefined })}>
          <span className={styles.rowHeader}><strong>Brief v{item.version_number}</strong><ShortId value={item.id} /></span>
          <span className={styles.meta}>hash {item.content_hash.slice(0, 12)} · base <ShortId value={item.base_version_id} /></span>
        </Link>)}</div> : <Empty>资格化机会后创建首个 Brief。</Empty>}</ResourceBlock>
        <ActionForm action={createBrief} title="创建 Brief 新版本" submitLabel="冻结 Brief" disabled={!opportunity}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="opportunity_id" value={opportunity?.id || ""} />
          <input type="hidden" name="base_version_id" value={brief?.id || ""} />
          <label>主品牌实体 ID<input name="primary_brand_entity_id" required placeholder="UUID" /></label>
          <label>允许事实主体 ID<textarea name="allowed_subject_entity_ids" placeholder="每行一个品牌、产品或市场实体 UUID" /></label>
          <label>比较实体 ID<textarea name="compared_entity_ids" placeholder="每行一个竞品实体 UUID" /></label>
          <label>目标 JSON<textarea name="goals" required defaultValue={'{"audience":"Australian consumers","intent":"product recommendation","deliverable":"channel-ready copy"}'} /></label>
          <label>约束 JSON<textarea name="constraints" defaultValue={'{"unsupported_superlatives":false,"public_citations_required":true}'} /></label>
          <label>真实消费者使用描述<textarea name="consumer_experience_description" placeholder="可选：一段真实消费者使用描述，不虚构人物或体验" /></label>
          <label>描述来源<input name="consumer_experience_source" placeholder="访谈、已授权评论或客服记录" /></label>
          <div className={styles.inline}><label>使用权<input name="consumer_experience_usage_rights" placeholder="public_rewrite_authorized" /></label><label>披露<input name="consumer_experience_disclosure" placeholder="customer statement, edited for clarity" /></label></div>
        </ActionForm>
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="2 · Immutable evidence" title="Evidence Pack Attempts" />
        <ResourceBlock resource={data.attempts}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.attemptId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { attempt_id: item.id })}>
          <span className={styles.rowHeader}><strong>Attempt {item.attempt_number}</strong><Status value={item.status} /></span>
          <span className={styles.meta}><span>{item.pack_hash?.slice(0, 12) || "尚无 pack hash"}</span><span>{item.failure_reason || "不可变快照"}</span></span>
        </Link>)}</div> : <Empty>尚无 Evidence Pack Attempt。</Empty>}</ResourceBlock>
        <ActionForm action={buildEvidence} submitLabel="创建构建 Attempt" disabled={!brief}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="brief_version_id" value={brief?.id || ""} />
        </ActionForm>
        {data.attempt.data ? <div className={styles.keyValues}><div><span className={styles.meta}>状态</span><br /><Status value={data.attempt.data.status} /></div><div><span className={styles.meta}>Pack hash</span><br /><ShortId value={data.attempt.data.pack_hash} /></div><div><span className={styles.meta}>Attempt</span><br /><strong>{data.attempt.data.attempt_number}</strong></div></div> : null}
        {data.job.data ? <div className={styles.row}>
          <span className={styles.rowHeader}><strong>Evidence Job <ShortId value={data.job.data.id} /></strong><Status value={data.job.data.status} /></span>
          <span className={styles.meta}>{data.job.data.result_ref || data.job.data.error_code || "等待 Evidence Pack finalize"}</span>
        </div> : null}
        <h3>证据条目</h3>
        <ResourceBlock resource={data.evidenceItems}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}>
          <span className={styles.rowHeader}><strong>{item.item_type} · {item.subject_role}</strong><Status value={item.public_disclosure_allowed ? "public" : "internal"} /></span>
          <span className={styles.meta}><span>{item.citation_label || item.public_source_title || "内部证据"}</span><span>{item.usage_rights}</span><span>hash {item.snapshot_hash.slice(0, 10)}</span></span>
          {item.public_source_url ? <a href={item.public_source_url} target="_blank" rel="noreferrer">{item.public_source_url}</a> : null}
        </div>)}</div> : <Empty>选择 Attempt 后查看内部证据和公开 Citation 属性。</Empty>}</ResourceBlock>
      </div>
    </div>
    <div className={styles.threeColumns}>
      <div className={styles.panel}>
        <SectionHeader eyebrow="3 · Editable source" title="Prompt Skills" />
        <ActionForm action={installDefaultPromptCatalog} submitLabel="安装九平台默认 Prompt"><HiddenProject projectId={projectId} /></ActionForm>
        <ResourceBlock resource={data.skills}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.skillId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { skill_id: item.id })}><span className={styles.rowHeader}><strong>{item.skill_key}</strong><Status value={item.status} /></span></Link>)}</div> : <Empty>先建立 Prompt Skill。</Empty>}</ResourceBlock>
        <ActionForm action={createPromptSkill} title="新建 Skill" submitLabel="创建"><HiddenProject projectId={projectId} /><label>Skill Key<input name="skill_key" required placeholder="placement.productreview.review" /></label></ActionForm>
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="4 · Compiled release" title="Prompt Releases" />
        <ResourceBlock resource={data.releases}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}><span className={styles.rowHeader}><strong>Release {item.release_number}</strong><ShortId value={item.id} /></span><span className={styles.meta}>hash {item.release_hash.slice(0, 12)} · {item.compiler_version}</span><details><summary>查看不可变 Prompt</summary><p className={styles.meta}>Source</p><pre className={styles.code}>{item.source_text}</pre><p className={styles.meta}>System</p><pre className={styles.code}>{item.system_template}</pre><p className={styles.meta}>User</p><pre className={styles.code}>{item.user_template}</pre><p className={styles.meta}>Variables / Output schema</p><pre className={styles.code}>{JSON.stringify({ variable_schema: item.variable_schema, output_schema: item.output_schema }, null, 2)}</pre></details></div>)}</div> : <Empty>修改 Prompt 时创建新 Release，旧 Bundle 不变。</Empty>}</ResourceBlock>
        <ActionForm action={createPromptRelease} title="编译新 Release" submitLabel="创建 Release" disabled={!selection.skillId}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="skill_id" value={selection.skillId || ""} />
          <label>Skill 源<textarea name="source" required defaultValue={DEFAULT_USER_PROMPT} /></label>
          <label>System Prompt<textarea name="system_template" required defaultValue={DEFAULT_SYSTEM_PROMPT} /></label>
          <label>User Prompt<textarea name="user_template" required defaultValue={DEFAULT_USER_PROMPT} /></label>
          <label>输出 Schema JSON<textarea name="output_schema" required defaultValue={DEFAULT_OUTPUT_SCHEMA} /></label>
          <label>客户端变量<textarea name="client_variable_names" placeholder="仅填写 User Prompt 中除 brief/evidence/destination_policy 外的变量，每行一个" /></label>
        </ActionForm>
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="5 · Runtime selection" title="任务绑定与 Bundle" />
        <ResourceBlock resource={data.bindings}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.task_key}><strong>{item.task_key}</strong><span className={styles.meta}>Release <ShortId value={item.template_release_id} /></span></div>)}</div> : <Empty>尚无任务绑定。</Empty>}</ResourceBlock>
        <ActionForm action={bindPromptTask} title="绑定任务" submitLabel="保存绑定" disabled={!release}>
          <HiddenProject projectId={projectId} /><label>Task Key<select name="task_key" required defaultValue="owned_site">{PROMPT_TASK_KEYS.map((key) => <option key={key} value={key}>{key}</option>)}</select></label>
          <label>Release<select name="template_release_id" required defaultValue={release?.id || ""}>{data.releases.data.map((item) => <option key={item.id} value={item.id}>Release {item.release_number} · {item.release_hash.slice(0, 8)}</option>)}</select></label>
        </ActionForm>
        <ActionForm action={createPromptBundle} title="冻结 Prompt Bundle" submitLabel="创建 Bundle" disabled={!brief || !readyAttempt || !release}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="brief_version_id" value={brief?.id || ""} />
          <label>Ready Evidence Attempt<select name="evidence_pack_attempt_id" required defaultValue={readyAttempt?.id || ""}>{data.attempts.data.filter((item) => item.status === "ready").map((item) => <option key={item.id} value={item.id}>Attempt {item.attempt_number}</option>)}</select></label>
          <label>Release<select name="template_release_id" required defaultValue={release?.id || ""}>{data.releases.data.map((item) => <option key={item.id} value={item.id}>Release {item.release_number}</option>)}</select></label>
          <label>模型策略 Hash<input name="model_policy_hash" required placeholder="sha256 policy hash" /></label>
          <label>变量 JSON<textarea name="variables" required defaultValue="{}" /></label>
        </ActionForm>
      </div>
    </div>
    <div className={styles.panel}>
      <SectionHeader eyebrow="Immutable runtime artifact" title="Prompt Bundles" />
      <ResourceBlock resource={data.bundles}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
        className={item.id === selection.bundleId ? styles.selectedRow : styles.row} href={geoHref(projectId, selection, { bundle_id: item.id })}>
        <span className={styles.rowHeader}><strong>Bundle <ShortId value={item.id} /></strong><Status value={item.artifact_status} /></span>
        <span className={styles.meta}><span>hash {item.bundle_hash.slice(0, 12)}</span><span>{item.storage_uri || item.storage_key}</span></span>
      </Link>)}</div> : <Empty>Evidence Ready 与 Release 均存在后才能冻结 Bundle。</Empty>}</ResourceBlock>
      {data.bundle.data ? <pre className={styles.code}>{JSON.stringify(data.bundle.data.manifest, null, 2)}</pre> : null}
    </div>
  </div>;
}
