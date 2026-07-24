"use client";

import { useActionState, useState } from "react";

import {
  admitStyleCollectionAction,
  cancelSyntheticJobAction
} from "./syntheticLabJobActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import {
  initialSyntheticActionState,
  type CollectionAuthorization,
  type StyleLoginSecretReference,
  type StyleSource,
  type SyntheticJob
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export function StyleCollectionAdmissionForm({
  authorizations,
  canContribute,
  commandKey,
  loginSecrets,
  projectId,
  sources
}: {
  authorizations: CollectionAuthorization[];
  canContribute: boolean;
  commandKey: string;
  loginSecrets: StyleLoginSecretReference[];
  projectId: string;
  sources: StyleSource[];
}) {
  const [state, action, pending] = useActionState(
    admitStyleCollectionAction, initialSyntheticActionState
  );
  const liveSources = sources.filter((item) => item.status === "active"
    && item.access_mode !== "manual_import");
  const [sourceId, setSourceId] = useState(liveSources[0]?.id || "");
  const source = liveSources.find((item) => item.id === sourceId) || liveSources[0];
  const adapters = authorizations.filter((item) => item.channel === source?.channel
    && item.effective_state === "approved"
    && item.allowed_purposes.includes("style_collection"));
  const secrets = loginSecrets.filter((item) => item.purpose
    === `style_collection_login.${source?.channel || ""}`);
  const blocked = !source || adapters.length === 0
    || (source.access_mode === "authenticated" && secrets.length === 0);
  return (
    <form action={action} className={styles.writeForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      <fieldset disabled={!canContribute || pending || blocked}>
        <legend>澳洲英文 Style Collection</legend>
        <div className={styles.formGridThree}>
          <label><span>Style Source</span><select name="style_source_revision_id" onChange={(event) => setSourceId(event.target.value)} value={source?.id || ""}>{liveSources.map((item) => <option key={item.id} value={item.id}>{item.channel} · r{item.revision_number} · {item.access_mode}</option>)}</select></label>
          <label><span>Approved adapter</span><select name="adapter_release">{adapters.map((item) => <option key={item.id} value={item.adapter_release}>{item.adapter_release}</option>)}</select></label>
          <label><span>Login Secret Reference</span><select name="login_secret_reference_id" required={source?.access_mode === "authenticated"}><option value="">无需 Secret</option>{secrets.map((item) => <option key={item.reference_id} value={item.reference_id}>{item.purpose} · v{item.current_version}</option>)}</select></label>
          <button disabled={!canContribute || pending || blocked} type="submit">{pending ? "排队中..." : "批准并排队采集"}</button>
        </div>
      </fieldset>
      {blocked ? <p className={styles.formNote}>blocked · source / authorization / login secret admission incomplete</p> : null}
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function SelectedJobControls({
  canContribute,
  commandKey,
  job,
  projectId
}: {
  canContribute: boolean;
  commandKey: string;
  job: SyntheticJob;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(cancelSyntheticJobAction, initialSyntheticActionState);
  const terminal = ["succeeded", "failed", "dead_lettered", "cancelled"].includes(job.status);
  return (
    <form action={action} className={styles.jobControlForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      <input name="job_id" type="hidden" value={job.id} />
      <input name="expected_version" type="hidden" value={job.version} />
      <button className="danger" disabled={!canContribute || pending || terminal} type="submit">{pending ? "取消中..." : "取消任务"}</button>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}
