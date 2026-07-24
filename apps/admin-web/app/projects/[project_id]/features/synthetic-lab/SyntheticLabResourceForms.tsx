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
        <legend>新增 Style Source</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect />
          <label><span>Access mode</span><select name="access_mode" onChange={(event) => setAccessMode(event.target.value)} value={accessMode}><option value="public">Public</option><option value="authenticated">Authenticated</option><option value="manual_import">Manual import</option></select></label>
          {manual
            ? <label className={styles.grow}><span>来源名称</span><input maxLength={200} name="source_label" required /></label>
            : <label className={styles.grow}><span>HTTPS URL</span><input maxLength={2048} name="source_url" required type="url" /></label>}
          <button type="submit">{pending ? "创建中..." : "创建 Source"}</button>
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
          <OptionSelect label="Style Source" name="style_source_revision_id" options={manualSources.map((source) => ({ id: source.id, label: `${source.channel} · revision ${source.revision_number}` }))} />
          <label><span>格式</span><select defaultValue="text" name="import_format"><option value="text">Text</option><option value="csv">CSV</option><option value="jsonl">JSONL</option></select></label>
          <label><span>样本文件</span><input accept=".txt,.text,.csv,.jsonl,.ndjson,text/plain,text/csv,application/x-ndjson" name="sample_file" required type="file" /></label>
          <label><span>来源权利</span><select defaultValue="authorized_manual_capture" name="default_source_rights"><option value="owned">Owned</option><option value="licensed">Licensed</option><option value="public_reference">Public reference</option><option value="authorized_manual_capture">Authorised manual capture</option></select></label>
          <label className={styles.spanTwo}><span>权利依据</span><textarea maxLength={2000} name="rights_evidence_reference" required rows={3} /></label>
          <button type="submit">{pending ? "扫描中..." : "生成安全预览"}</button>
        </div>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function ManualImportApprovalForm({ preview, ...props }: CommandProps & {
  preview: ManualImportPreview;
}) {
  const [state, action, pending] = useActionState(
    approveManualImportPreviewAction,
    initialSyntheticActionState
  );
  return (
    <form action={action} className={styles.writeForm}>
      <CommandFields {...props} />
      <input name="preview_id" type="hidden" value={preview.id} />
      <fieldset disabled={!props.canContribute || pending || preview.status !== "pending"}>
        <legend>独立复核 · {preview.filename}</legend>
        <div className={formStyles.previewRows}>
          {preview.rows.map((row) => (
            <label className={formStyles.previewRow} key={row.row_number}>
              <input defaultChecked={row.selectable} disabled={!row.selectable} name="selected_row_numbers" type="checkbox" value={row.row_number} />
              <span><strong>#{row.row_number} · {row.disposition}</strong><span>{row.redacted_text}</span>{row.detected_codes.length ? <small>{row.detected_codes.join(" · ")}</small> : null}{row.blocking_codes.length ? <small>{row.blocking_codes.join(" · ")}</small> : null}</span>
            </label>
          ))}
        </div>
        <div className={styles.checkRow}>
          <label><input name="au_english_verified" required type="checkbox" value="true" /> 澳洲英文已明审</label>
          <label><input name="anonymization_verified" required type="checkbox" value="true" /> 匿名化已明审</label>
        </div>
        <button type="submit">{pending ? "批准中..." : "批准所选样本"}</button>
      </fieldset>
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
        <legend>创建 Style Profile draft</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect onChange={setChannel} value={channel} />
          <ResourceSelect label="Prompt Program" name="prompt_binding_id" options={prompts} />
          <div className={formStyles.optionChecklist}>
            <strong>批准样本</strong>
            {samples.map((sample) => <label key={sample.id}><input name="approved_sample_ids" type="checkbox" value={sample.id} /> {sample.label}</label>)}
          </div>
          <button type="submit">{pending ? "创建中..." : "创建 Profile"}</button>
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
        <legend>创建 Review Suite draft</legend>
        <div className={styles.formGridThree}>
          <ChannelSelect />
          <label><span>Suite 名称</span><input maxLength={200} name="suite_name" required /></label>
          <button type="submit">{pending ? "创建中..." : "创建 Suite"}</button>
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
        <legend>新增 Review Case</legend>
        <div className={styles.formGridThree}>
          <label><span>Case key</span><input maxLength={200} name="case_key" pattern="[a-zA-Z0-9_.:-]+" required /></label>
          <label><span>Ordinal</span><input min={1} name="ordinal" required type="number" /></label>
          <label><span>Mode</span><select name="mode" onChange={(event) => setMode(event.target.value)} value={mode}><option value="autonomous_scenario">Autonomous</option><option value="guided_scenario">Guided</option></select></label>
          <label><span>Persona</span><input maxLength={4000} name="persona" required /></label>
          <label><span>Use case</span><input maxLength={4000} name="use_case" required /></label>
          <label><span>Subject</span><input maxLength={1000} name="subject" required /></label>
          <ResourceSelect label="Question Set" name="question_set_version_id" options={inventory.question_sets} />
          <ResourceSelect label="Fact snapshot" name="fact_snapshot_id" options={inventory.fact_snapshots} />
          <ResourceSelect label="Style Profile" name="profile_version_id" options={profiles} />
          <label><span>Expected risks</span><input name="expected_risks" /></label>
          {mode === "guided_scenario" ? <label><span>Creative reference</span><input maxLength={4000} name="creative_reference" required /></label> : null}
        </div>
        <label className={styles.checkbox}><input name="competitor_scenario" type="checkbox" value="true" /> 竞品场景</label>
        <button type="submit">{pending ? "创建中..." : "创建 Case"}</button>
      </fieldset>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

function CommandFields({ commandKey, projectId }: CommandProps) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}

function ChannelSelect({ value, onChange }: { value?: string; onChange?: (value: string) => void }) {
  return <label><span>Channel</span><select defaultValue={value ? undefined : "reddit"} name="channel" onChange={onChange ? (event) => onChange(event.target.value) : undefined} value={value}>{syntheticChannels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}</select></label>;
}

function ResourceSelect({ label, name, options }: { label: string; name: string; options: SyntheticResourceOption[] }) {
  return <OptionSelect label={label} name={name} options={options.map(({ id, label: optionLabel }) => ({ id, label: optionLabel }))} />;
}

function OptionSelect({ label, name, options }: { label: string; name: string; options: ReadonlyArray<{ id: string; label: string }> }) {
  return <label><span>{label}</span><select name={name} required>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>;
}
