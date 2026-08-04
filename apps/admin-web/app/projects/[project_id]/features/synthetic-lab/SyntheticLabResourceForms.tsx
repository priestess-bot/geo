"use client";

import { useActionState, useMemo, useState } from "react";

import {
  approveManualImportPreviewAction,
  createManualImportPreviewAction,
  createReviewCaseAction,
  createReviewSuiteAction,
  createStyleProfileAction,
  createStyleSourceAction
} from "./syntheticLabResourceActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import {
  initialSyntheticActionState,
  syntheticChannels,
  type ManualImportPreview,
  type ReviewSuite,
  type StyleSource,
  type SyntheticResourceInventory,
  type SyntheticResourceOption
} from "./syntheticLabTypes";
import { channelLabel } from "./SyntheticLabUI";
import styles from "./SyntheticLab.module.css";
import formStyles from "./SyntheticLabResourceForms.module.css";

type CommandProps = Readonly<{
  canContribute: boolean;
  commandKey: string;
  projectId: string;
}>;

export function CreateStyleSourceForm(props: CommandProps) {
  const [state, action, pending] = useActionState(createStyleSourceAction, initialSyntheticActionState);
  const [accessMode, setAccessMode] = useState("public");
  const manual = accessMode === "manual_import";
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <input name="expected_version" type="hidden" value={0} />
      <fieldset disabled={!props.canContribute || pending}>
        <legend>新增风格来源</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect />
          <label><span>访问方式</span><select name="access_mode" onChange={(event) => setAccessMode(event.target.value)} value={accessMode}><option value="public">公开</option><option value="authenticated">已登录</option><option value="manual_import">人工导入</option></select></label>
          {manual
            ? <label className={styles.grow}><span>来源名称</span><input maxLength={200} name="source_label" required /></label>
            : <label className={styles.grow}><span>HTTPS URL</span><input maxLength={2048} name="source_url" required type="url" /></label>}
          <button type="submit">{pending ? "创建中..." : "创建来源"}</button>
        </div>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function ManualSampleImportForm({ sources, ...props }: CommandProps & {
  sources: StyleSource[];
}) {
  const [state, action, pending] = useActionState(
    createManualImportPreviewAction,
    initialSyntheticActionState
  );
  const manualSources = sources.filter((source) => source.access_mode === "manual_import");
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <fieldset disabled={!props.canContribute || pending || manualSources.length === 0}>
        <legend>上传样本并生成预览</legend>
        <div className={styles.formGridThree}>
          <OptionSelect label="风格来源" name="style_source_revision_id" options={manualSources.map((source) => ({ id: source.id, label: `${channelLabel(source.channel)} · 修订 ${source.revision_number}` }))} />
          <label><span>格式</span><select defaultValue="text" name="import_format"><option value="text">纯文本</option><option value="csv">CSV</option><option value="jsonl">JSONL</option></select></label>
          <label><span>样本文件</span><input accept=".txt,.text,.csv,.jsonl,.ndjson,text/plain,text/csv,application/x-ndjson" name="sample_file" required type="file" /></label>
          <label><span>来源权利</span><select defaultValue="" name="default_source_rights" required><option disabled value="">请选择权利依据</option><option value="owned">自有</option><option value="licensed">已授权</option><option value="public_reference">公开引用</option><option value="authorized_manual_capture">已授权人工采集</option></select></label>
          <label className={styles.spanTwo}><span>权利依据</span><textarea maxLength={2000} name="rights_evidence_reference" required rows={3} /></label>
          <button type="submit">{pending ? "扫描中..." : "生成安全预览"}</button>
        </div>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function ManualImportApprovalForm({ actorIdentityId, preview, ...props }: CommandProps & {
  actorIdentityId: string;
  preview: ManualImportPreview;
}) {
  const [state, action, pending] = useActionState(
    approveManualImportPreviewAction,
    initialSyntheticActionState
  );
  const selfSubmitted = Boolean(actorIdentityId) && actorIdentityId === preview.submitted_by;
  const identityUnavailable = !actorIdentityId;
  const reviewBlocked = !props.canContribute || pending || preview.status !== "pending"
    || selfSubmitted || identityUnavailable;
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <input name="preview_id" type="hidden" value={preview.id} />
      <fieldset disabled={reviewBlocked}>
        <legend>独立复核 · {preview.filename}</legend>
        <div className={formStyles.previewRows}>
          {preview.rows.map((row) => (
            <label className={formStyles.previewRow} key={row.row_number}>
              <input defaultChecked={row.selectable} disabled={!row.selectable} name="selected_row_numbers" type="checkbox" value={row.row_number} />
              <span><strong>#{row.row_number} · {importDispositionLabel(row.disposition)}</strong><span>{row.redacted_text}</span>{row.detected_codes.length ? <small>{row.detected_codes.join(" · ")}</small> : null}{row.blocking_codes.length ? <small>{row.blocking_codes.join(" · ")}</small> : null}</span>
            </label>
          ))}
        </div>
        <div className={styles.checkRow}>
          <label><input name="au_english_verified" required type="checkbox" value="true" /> 澳洲英文已明审</label>
          <label><input name="anonymization_verified" required type="checkbox" value="true" /> 匿名化已明审</label>
        </div>
        <button type="submit">{pending ? "批准中..." : "批准所选样本"}</button>
      </fieldset>
      {selfSubmitted ? <p className={styles.formNote} role="status">提交者不能复核自己的导入预览；请由另一位具备复核权限的项目成员处理。</p> : null}
      {identityUnavailable ? <p className={styles.formNote} role="status">当前成员身份无法确认，独立复核保持关闭。</p> : null}
      {!props.canContribute ? <p className={styles.formNote} role="status">当前项目角色没有样本复核权限。</p> : null}
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function CreateStyleProfileForm({ inventory, ...props }: CommandProps & {
  inventory: SyntheticResourceInventory;
}) {
  const [state, action, pending] = useActionState(createStyleProfileAction, initialSyntheticActionState);
  const [channel, setChannel] = useState("reddit");
  const samples = useMemo(
    () => inventory.samples.filter((sample) => sample.channel === channel),
    [channel, inventory.samples]
  );
  const prompts = inventory.prompt_bindings.filter((item) => item.label.startsWith("synthetic_lab.style_profile"));
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <input name="expected_version" type="hidden" value={0} />
      <fieldset disabled={!props.canContribute || pending || samples.length === 0 || prompts.length === 0}>
        <legend>创建风格画像草稿</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect onChange={setChannel} value={channel} />
          <ResourceSelect label="Prompt 程序" name="prompt_binding_id" options={prompts} />
          <div className={formStyles.optionChecklist}>
            <strong>批准样本</strong>
            {samples.map((sample) => <label key={sample.id}><input name="approved_sample_ids" type="checkbox" value={sample.id} /> {sample.label}</label>)}
          </div>
          <button type="submit">{pending ? "创建中..." : "创建风格画像"}</button>
        </div>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function CreateReviewSuiteForm(props: CommandProps) {
  const [state, action, pending] = useActionState(createReviewSuiteAction, initialSyntheticActionState);
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <fieldset disabled={!props.canContribute || pending}>
        <legend>创建测评套件草稿</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect />
          <label><span>测评套件名称</span><input maxLength={200} name="suite_name" required /></label>
          <button type="submit">{pending ? "创建中..." : "创建测评套件"}</button>
        </div>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function CreateReviewCaseForm({ inventory, suite, ...props }: CommandProps & {
  inventory: SyntheticResourceInventory;
  suite: ReviewSuite;
}) {
  const [state, action, pending] = useActionState(createReviewCaseAction, initialSyntheticActionState);
  const [mode, setMode] = useState("autonomous_scenario");
  const profiles = inventory.profiles.filter((profile) => profile.channel === suite.channel);
  const blocked = suite.status !== "draft" || !profiles.length
    || !inventory.question_sets.length || !inventory.fact_snapshots.length;
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <input name="suite_version_id" type="hidden" value={suite.id} />
      <input name="expected_version" type="hidden" value={0} />
      <input name="channel" type="hidden" value={suite.channel} />
      <fieldset disabled={!props.canContribute || pending || blocked}>
        <legend>新增测评用例</legend>
        <div className={styles.formGridThree}>
          <label><span>用例键</span><input maxLength={200} name="case_key" pattern="[a-zA-Z0-9_.:-]+" required /></label>
          <label><span>序号</span><input min={1} name="ordinal" required type="number" /></label>
          <label><span>模式</span><select name="mode" onChange={(event) => setMode(event.target.value)} value={mode}><option value="autonomous_scenario">自主</option><option value="guided_scenario">引导</option></select></label>
          <label><span>人物设定</span><input maxLength={4000} name="persona" required /></label>
          <label><span>使用场景</span><input maxLength={4000} name="use_case" required /></label>
          <label><span>主体</span><input maxLength={1000} name="subject" required /></label>
          <ResourceSelect label="问题集" name="question_set_version_id" options={inventory.question_sets} />
          <ResourceSelect label="事实快照" name="fact_snapshot_id" options={inventory.fact_snapshots} />
          <ResourceSelect label="风格画像" name="profile_version_id" options={profiles} />
          <label><span>预期风险</span><input name="expected_risks" /></label>
          {mode === "guided_scenario" ? <label><span>创意参考</span><input maxLength={4000} name="creative_reference" required /></label> : null}
        </div>
        <label className={styles.checkbox}><input name="competitor_scenario" type="checkbox" value="true" /> 竞品场景</label>
        <button type="submit">{pending ? "创建中..." : "创建用例"}</button>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

function CommandFields({ commandKey, projectId }: CommandProps) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}

function ChannelSelect({ value, onChange }: { value?: string; onChange?: (value: string) => void }) {
  return <label><span>渠道</span><select defaultValue={value ? undefined : "reddit"} name="channel" onChange={onChange ? (event) => onChange(event.target.value) : undefined} value={value}>{syntheticChannels.map((channel) => <option key={channel} value={channel}>{channelLabel(channel)}</option>)}</select></label>;
}

function ResourceSelect({ label, name, options }: { label: string; name: string; options: SyntheticResourceOption[] }) {
  return <OptionSelect label={label} name={name} options={options.map(({ id, label: optionLabel }) => ({ id, label: optionLabel }))} />;
}

function OptionSelect({ label, name, options }: { label: string; name: string; options: ReadonlyArray<{ id: string; label: string }> }) {
  return <label><span>{label}</span><select name={name} required>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>;
}

function importDispositionLabel(value: string): string {
  return {
    ready_for_review: "待复核",
    blocked: "已阻断",
    duplicate: "重复样本"
  }[value] || value;
}
