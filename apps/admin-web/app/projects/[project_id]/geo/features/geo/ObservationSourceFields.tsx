"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ObservationClientKind,
  ObservationDevice,
  ObservationModelState,
  ObservationPlatform,
  ObservationSearchMode,
  ObservationSurface,
  ObservationSurfaceKind,
  OperatorObservationCaptureMethod
} from "@geo/types/geo";
import styles from "./GeoWorkspace.module.css";

type SurfaceOption = Readonly<{ label: string; value: ObservationSurface }>;
type PlatformOption = Readonly<{
  label: string;
  value: ObservationPlatform;
  surfaces: readonly SurfaceOption[];
}>;

const SOURCE_OPTIONS: Record<OperatorObservationCaptureMethod, readonly PlatformOption[]> = {
  manual_ui: [
    { label: "OpenAI", value: "openai", surfaces: [{ label: "ChatGPT Search", value: "chatgpt_search" }] },
    { label: "Google", value: "google", surfaces: [
      { label: "Google Search", value: "google_search" },
      { label: "Google AI Overviews", value: "google_ai_overviews" },
      { label: "Google AI Mode", value: "google_ai_mode" },
      { label: "Gemini", value: "gemini" }
    ] },
    { label: "Perplexity", value: "perplexity", surfaces: [{ label: "Perplexity Answer", value: "perplexity_answer" }] },
    { label: "Microsoft", value: "microsoft", surfaces: [
      { label: "Bing Search", value: "bing_search" },
      { label: "Bing Copilot", value: "bing_copilot" }
    ] },
    { label: "Anthropic", value: "anthropic", surfaces: [{ label: "Claude.ai", value: "claude_ai" }] },
    { label: "其他", value: "other", surfaces: [{ label: "其他消费者界面", value: "other" }] }
  ],
  provider_api: [
    { label: "OpenAI", value: "openai", surfaces: [{ label: "OpenAI API", value: "openai_api" }] },
    { label: "Google", value: "google", surfaces: [{ label: "Google Gemini API", value: "google_gemini_api" }] },
    { label: "Perplexity", value: "perplexity", surfaces: [{ label: "Perplexity API", value: "perplexity_api" }] },
    { label: "Anthropic", value: "anthropic", surfaces: [{ label: "Anthropic API", value: "anthropic_api" }] },
    { label: "其他", value: "other", surfaces: [{ label: "其他 Provider API", value: "other" }] }
  ],
  proxy_grounded_api: [
    { label: "Microsoft", value: "microsoft", surfaces: [{ label: "Azure AI Bing Grounding", value: "microsoft_foundry_bing_grounding" }] },
    { label: "Google", value: "google", surfaces: [{ label: "Google Vertex Grounding", value: "google_vertex_grounding" }] },
    { label: "其他", value: "other", surfaces: [{ label: "其他 Grounded Proxy", value: "other" }] }
  ]
};

const CAPTURE_LABELS: Record<OperatorObservationCaptureMethod, string> = {
  manual_ui: "人工消费者界面",
  provider_api: "Provider API",
  proxy_grounded_api: "Grounded Proxy API"
};

const SURFACE_KIND: Record<OperatorObservationCaptureMethod, ObservationSurfaceKind> = {
  manual_ui: "consumer_ui",
  provider_api: "provider_api",
  proxy_grounded_api: "grounded_proxy"
};

const SEARCH_MODES: ReadonlyArray<Readonly<{ label: string; value: ObservationSearchMode }>> = [
  { label: "实时联网", value: "live_web" },
  { label: "Grounded Web", value: "grounded_web" },
  { label: "平台自动决定", value: "automatic" },
  { label: "未启用搜索", value: "disabled" },
  { label: "不适用", value: "not_applicable" }
];

export function ObservationSourceFields({ locale }: { locale: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [captureMethod, setCaptureMethod] = useState<OperatorObservationCaptureMethod>("manual_ui");
  const [platform, setPlatform] = useState<ObservationPlatform>("openai");
  const [surface, setSurface] = useState<ObservationSurface>("chatgpt_search");
  const [engine, setEngine] = useState("openai");
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [searchMode, setSearchMode] = useState<ObservationSearchMode>("live_web");
  const platformOptions = SOURCE_OPTIONS[captureMethod];
  const selectedPlatform = platformOptions.find((item) => item.value === platform)
    || platformOptions[0];
  const apiCapture = captureMethod !== "manual_ui";
  const devices: ObservationDevice[] = apiCapture ? ["api"] : ["desktop", "mobile", "tablet"];
  const clients: ObservationClientKind[] = apiCapture ? ["api"] : ["browser", "native_app"];

  useEffect(() => {
    const form = containerRef.current?.closest("form");
    if (!form) return;
    const reset = () => queueMicrotask(() => {
      setCaptureMethod("manual_ui");
      setPlatform("openai");
      setSurface("chatgpt_search");
      setEngine("openai");
      setSearchEnabled(true);
      setSearchMode("live_web");
    });
    form.addEventListener("reset", reset);
    return () => form.removeEventListener("reset", reset);
  }, []);

  const selectCaptureMethod = (next: OperatorObservationCaptureMethod) => {
    const nextPlatform = SOURCE_OPTIONS[next][0];
    setCaptureMethod(next);
    setPlatform(nextPlatform.value);
    setSurface(nextPlatform.surfaces[0].value);
    setEngine(nextPlatform.value);
    setSearchEnabled(true);
    setSearchMode(next === "manual_ui" ? "live_web" : "automatic");
  };
  const selectPlatform = (next: ObservationPlatform) => {
    const nextPlatform = platformOptions.find((item) => item.value === next) || platformOptions[0];
    setPlatform(nextPlatform.value);
    setSurface(nextPlatform.surfaces[0].value);
    setEngine(nextPlatform.value);
  };

  return <div className={styles.formInset} ref={containerRef}>
    <div className={styles.inline}>
      <label>采集方式<select name="capture_method" value={captureMethod}
        onChange={(event) => selectCaptureMethod(event.target.value as OperatorObservationCaptureMethod)}>
        {(Object.keys(CAPTURE_LABELS) as OperatorObservationCaptureMethod[]).map((method) =>
          <option key={method} value={method}>{CAPTURE_LABELS[method]}</option>)}
      </select></label>
      <label>平台<select name="source_platform" value={selectedPlatform.value}
        onChange={(event) => selectPlatform(event.target.value as ObservationPlatform)}>
        {platformOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
    </div>
    <label>Surface<select name="source_surface" value={surface}
      onChange={(event) => setSurface(event.target.value as ObservationSurface)}>
      {selectedPlatform.surfaces.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select></label>
    <input type="hidden" name="source_surface_kind" value={SURFACE_KIND[captureMethod]} />
    {selectedPlatform.value === "other" ? <label>平台说明<input name="platform_detail" required /></label> : null}
    {surface === "other" ? <label>Surface 说明<input name="surface_detail" required /></label> : null}

    <ModelIdentityFields
      key={`model-${captureMethod}`}
      configuredStateName="configured_model_state"
      configuredValueName="configured_model"
      reportedStateName="reported_model_state"
      reportedValueName="provider_reported_model"
      configuredDefault={apiCapture ? "disclosed" : "not_disclosed"}
    />

    <fieldset><legend>运行参数</legend>
      <label>Engine<input name="engine" required value={engine}
        onChange={(event) => setEngine(event.target.value)} pattern="[a-z0-9](?:[a-z0-9_]|-)*" /></label>
      <div className={styles.inline}>
        <label>Locale<input name="locale" required defaultValue={locale} /></label>
        <label>地区<input name="region" required placeholder="例如：AU" /></label>
        <label>语言<input name="language" required defaultValue={locale.split("-")[0] || "zh"} /></label>
      </div>
      <div className={styles.inline}>
        <label>设备<select key={`device-${captureMethod}`} name="device" defaultValue={devices[0]}>{devices.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label>客户端<select key={`client-${captureMethod}`} name="client_kind" defaultValue={clients[0]}>{clients.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label>搜索模式<select name="search_mode" value={searchMode}
          onChange={(event) => setSearchMode(event.target.value as ObservationSearchMode)}>{SEARCH_MODES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      </div>
      <label className={styles.check}><input type="checkbox" name="search_enabled" checked={searchEnabled}
        onChange={(event) => {
          setSearchEnabled(event.target.checked);
          setSearchMode(event.target.checked ? (apiCapture ? "automatic" : "live_web") : "disabled");
        }} />本次启用搜索或 grounding</label>
      <label>实际问题<textarea name="prompt_text" required /></label>
      <label>后续追问<textarea name="follow_up_prompts" placeholder="每行一个" /></label>
      <div className={styles.inline}>
        <label>Adapter<input name="adapter_name" required={apiCapture} /></label>
        <label>Adapter 版本<input name="adapter_version" required={apiCapture} /></label>
        <label>Provider Request ID<input name="provider_request_id" required={apiCapture} /></label>
      </div>
    </fieldset>

    <fieldset><legend>原始证据</legend>
      <label>{apiCapture ? "原始响应 JSON" : "完整原始回答"}<textarea name="raw_answer" /></label>
      <div className={styles.inline}>
        <label>不可变工件 URI<input name="artifact_uri" pattern="s3://.+" placeholder="s3://bucket/object" /></label>
        <label>工件 SHA-256<input name="artifact_hash" pattern="[0-9a-f]{64}" /></label>
      </div>
    </fieldset>
  </div>;
}

export function ProtocolSourceStratumFields({ locale }: { locale: string }) {
  const fieldsetRef = useRef<HTMLFieldSetElement>(null);
  const [captureMethod, setCaptureMethod] = useState<OperatorObservationCaptureMethod>("manual_ui");
  const [platform, setPlatform] = useState<ObservationPlatform>("openai");
  const [surface, setSurface] = useState<ObservationSurface>("chatgpt_search");
  const [engine, setEngine] = useState("openai");
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [searchMode, setSearchMode] = useState<ObservationSearchMode>("live_web");
  const platformOptions = SOURCE_OPTIONS[captureMethod];
  const selectedPlatform = platformOptions.find((item) => item.value === platform)
    || platformOptions[0];
  const apiCapture = captureMethod !== "manual_ui";

  useEffect(() => {
    const form = fieldsetRef.current?.closest("form");
    if (!form) return;
    const reset = () => queueMicrotask(() => {
      setCaptureMethod("manual_ui");
      setPlatform("openai");
      setSurface("chatgpt_search");
      setEngine("openai");
      setSearchEnabled(true);
      setSearchMode("live_web");
    });
    form.addEventListener("reset", reset);
    return () => form.removeEventListener("reset", reset);
  }, []);

  const selectCaptureMethod = (next: OperatorObservationCaptureMethod) => {
    const nextPlatform = SOURCE_OPTIONS[next][0];
    setCaptureMethod(next);
    setPlatform(nextPlatform.value);
    setSurface(nextPlatform.surfaces[0].value);
    setEngine(nextPlatform.value);
    setSearchEnabled(true);
    setSearchMode(next === "manual_ui" ? "live_web" : "automatic");
  };
  const selectPlatform = (next: ObservationPlatform) => {
    const nextPlatform = platformOptions.find((item) => item.value === next) || platformOptions[0];
    setPlatform(nextPlatform.value);
    setSurface(nextPlatform.surfaces[0].value);
    setEngine(nextPlatform.value);
  };

  return <fieldset ref={fieldsetRef}><legend>冻结来源分层</legend>
    <div className={styles.inline}>
      <label>采集方式<select name="capture_method" value={captureMethod}
        onChange={(event) => selectCaptureMethod(event.target.value as OperatorObservationCaptureMethod)}>
        {(Object.keys(CAPTURE_LABELS) as OperatorObservationCaptureMethod[]).map((method) =>
          <option key={method} value={method}>{CAPTURE_LABELS[method]}</option>)}
      </select></label>
      <label>平台<select name="source_platform" value={selectedPlatform.value}
        onChange={(event) => selectPlatform(event.target.value as ObservationPlatform)}>
        {platformOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
      <label>Surface<select name="source_surface" value={surface}
        onChange={(event) => setSurface(event.target.value as ObservationSurface)}>
        {selectedPlatform.surfaces.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
    </div>
    <input type="hidden" name="source_surface_kind" value={SURFACE_KIND[captureMethod]} />
    {selectedPlatform.value === "other" ? <label>平台说明<input name="stratum_platform_detail" required /></label> : null}
    {surface === "other" ? <label>Surface 说明<input name="stratum_surface_detail" required /></label> : null}
    <input type="hidden" name="platform" value={protocolPlatform(surface)} />
    <input type="hidden" name="protocol_device" value="desktop" />
    <label>Engine<input name="stratum_engine" required value={engine}
      onChange={(event) => setEngine(event.target.value)} pattern="[a-z0-9](?:[a-z0-9_]|-)*" /></label>
    <ModelIdentityFields
      key={`stratum-model-${captureMethod}`}
      configuredStateName="stratum_configured_model_state"
      configuredValueName="stratum_configured_model"
      reportedStateName="stratum_reported_model_state"
      reportedValueName="stratum_reported_model"
      configuredDefault={apiCapture ? "disclosed" : "not_disclosed"}
    />
    <div className={styles.inline}>
      <label>Locale<input name="locale" defaultValue={locale} required /></label>
      <label>地区<input name="region" placeholder="例如：AU" required /></label>
      <label>语言<input name="language" defaultValue={locale.split("-")[0] || "zh"} required /></label>
    </div>
    <div className={styles.inline}>
      <label>设备<select key={`protocol-device-${captureMethod}`} name="source_device" defaultValue={apiCapture ? "api" : "desktop"}>
        {(apiCapture ? ["api"] : ["desktop", "mobile", "tablet"]).map((item) =>
          <option key={item} value={item}>{item}</option>)}
      </select></label>
      <label>客户端<select key={`protocol-client-${captureMethod}`} name="client_kind" defaultValue={apiCapture ? "api" : "browser"}>
        {(apiCapture ? ["api"] : ["browser", "native_app"]).map((item) =>
          <option key={item} value={item}>{item}</option>)}
      </select></label>
      <label>搜索模式<select name="search_mode" value={searchMode}
        onChange={(event) => setSearchMode(event.target.value as ObservationSearchMode)}>
        {SEARCH_MODES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
    </div>
    <label className={styles.check}><input type="checkbox" name="search_enabled" checked={searchEnabled}
      onChange={(event) => {
        setSearchEnabled(event.target.checked);
        setSearchMode(event.target.checked ? (apiCapture ? "automatic" : "live_web") : "disabled");
      }} />启用搜索或 grounding</label>
  </fieldset>;
}

function ModelIdentityFields({
  configuredDefault,
  configuredStateName,
  configuredValueName,
  reportedStateName,
  reportedValueName
}: {
  configuredDefault: ObservationModelState;
  configuredStateName: string;
  configuredValueName: string;
  reportedStateName: string;
  reportedValueName: string;
}) {
  return <fieldset><legend>模型身份</legend><div className={styles.inline}>
    <ModelIdentityField
      defaultState={configuredDefault}
      label="配置模型"
      stateName={configuredStateName}
      valueName={configuredValueName}
    />
    <ModelIdentityField
      defaultState="not_disclosed"
      label="平台报告模型"
      stateName={reportedStateName}
      valueName={reportedValueName}
    />
  </div></fieldset>;
}

function ModelIdentityField({ defaultState, label, stateName, valueName }: {
  defaultState: ObservationModelState;
  label: string;
  stateName: string;
  valueName: string;
}) {
  const [state, setState] = useState<ObservationModelState>(defaultState);
  const disclosed = state === "disclosed";
  return <>
    <label>{label}状态<select name={stateName} value={state}
      onChange={(event) => setState(event.target.value as ObservationModelState)}>
      <option value="disclosed">已披露</option>
      <option value="not_disclosed">未披露</option>
      <option value="not_applicable">不适用</option>
    </select></label>
    <label>{label}<input name={valueName} disabled={!disclosed} required={disclosed}
      placeholder={disclosed ? "填写准确模型标识" : "当前状态无需填写"} /></label>
  </>;
}

function protocolPlatform(surface: ObservationSurface): string {
  if (surface === "perplexity_answer" || surface === "perplexity_api") return "perplexity";
  if (surface === "openai_api" || surface === "anthropic_api") return "other";
  if (surface === "google_gemini_api") return "gemini";
  if (surface === "microsoft_foundry_bing_grounding") return "bing_search";
  if (surface === "google_vertex_grounding") return "google_search";
  return surface;
}

export function OfficialReportSourceFields() {
  const [platform, setPlatform] = useState<"google" | "microsoft">("google");
  const surface = platform === "google"
    ? "google_generative_ai_performance_report"
    : "bing_ai_performance_report";
  return <div className={styles.formInset}>
    <label>官方数据源<select name="official_platform" value={platform}
      onChange={(event) => setPlatform(event.target.value as "google" | "microsoft")}>
      <option value="google">Google Generative AI Performance</option>
      <option value="microsoft">Bing AI Performance</option>
    </select></label>
    <input type="hidden" name="official_surface" value={surface} />
  </div>;
}
