import { randomUUID } from "node:crypto";

import type { ManagedMemberRole } from "../../memberTypes";
import { SyntheticChannelStyleWorkspace } from "./SyntheticChannelStyleWorkspace";
import { SyntheticGenerationWorkbench } from "./SyntheticGenerationWorkbench";
import { SyntheticBoundaryBand, SyntheticLabNavigation } from "./SyntheticLabUI";
import type { SyntheticWorkspaceData } from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export function SyntheticLabWorkspace({
  currentRole,
  data,
  projectId
}: {
  currentRole: ManagedMemberRole | null;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const canContribute = currentRole === "owner"
    || currentRole === "admin"
    || currentRole === "analyst";
  const serviceReady = !data.directOptionsProblem
    && !data.runtimeOptionsProblem
    && data.directOptions.subjects.some((item) => item.knowledge_snapshot_hash)
    && data.directOptions.channel_styles.length > 0;

  return (
    <div className={styles.workspace} data-testid="synthetic-lab-workspace">
      <header className={styles.labShellHeader}>
        <div>
          <p>内部合成测评</p>
          <h2>合成测评实验室</h2>
        </div>
        <span className={serviceReady ? styles.serviceHealthy : styles.serviceDegraded}>
          {serviceReady ? "可以生成" : "需要补充生成条件"}
        </span>
      </header>
      <SyntheticLabNavigation currentView={data.currentView} projectId={projectId} />
      <SyntheticBoundaryBand compact />
      {data.currentView === "style" ? (
        <SyntheticChannelStyleWorkspace
          canContribute={canContribute}
          commandKey={`channel-style:${randomUUID()}`}
          initialStyles={data.directOptions.channel_styles}
          projectId={projectId}
        />
      ) : (
        <SyntheticGenerationWorkbench
          canContribute={canContribute}
          commandKey={`direct-generation:${randomUUID()}`}
          data={data}
          projectId={projectId}
        />
      )}
    </div>
  );
}

export function SyntheticLabLoading() {
  return (
    <div className={styles.workspace} aria-busy="true">
      <header className={styles.labShellHeader}>
        <div><p>内部合成测评</p><h2>合成测评实验室</h2></div>
        <span className={styles.serviceDegraded}>正在加载</span>
      </header>
      <div className={styles.loadingBar} />
    </div>
  );
}
