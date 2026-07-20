"use client";

import { useEffect, useState } from "react";
import styles from "./GeoWorkspace.module.css";

export function ProtocolSamplingFields() {
  const [hydrated, setHydrated] = useState(false);
  const [sampleSize, setSampleSize] = useState(3);
  const [minimumValid, setMinimumValid] = useState(3);
  const frozenMinimum = minimumValidRepeats(sampleSize);
  useEffect(() => setHydrated(true), []);

  function updateSampleSize(value: number) {
    const next = clamp(Math.round(value) || 3, 3, 1000);
    const threshold = minimumValidRepeats(next);
    setSampleSize(next);
    setMinimumValid((current) => clamp(Math.max(current, threshold), threshold, next));
  }

  return <div className={styles.inline}>
    <label>每个问题重复次数<input name="sample_size" type="number" min="3" max="1000"
      value={sampleSize} disabled={!hydrated}
      onChange={(event) => updateSampleSize(event.currentTarget.valueAsNumber)} required /></label>
    <label>有效重复门槛<input name="minimum_valid_repeats" type="number" min={frozenMinimum}
      max={sampleSize} value={minimumValid} disabled={!hydrated}
      onChange={(event) => setMinimumValid(clamp(
        Math.round(event.currentTarget.valueAsNumber) || frozenMinimum,
        frozenMinimum,
        sampleSize
      ))} required /></label>
  </div>;
}

function minimumValidRepeats(sampleSize: number): number {
  return Math.max(3, Math.ceil(sampleSize * 0.8));
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
