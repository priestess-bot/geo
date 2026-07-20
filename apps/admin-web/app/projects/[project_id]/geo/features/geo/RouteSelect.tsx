"use client";

import { useEffect, useState } from "react";
import styles from "./GeoWorkspace.module.css";

export function RouteSelect({ label, options, value, placeholder = "请选择" }: {
  label: string;
  options: Array<{ href: string; label: string; value: string }>;
  value?: string;
  placeholder?: string;
}) {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return <label className={styles.routeSelect}><span>{label}</span><select aria-label={label} value={value || ""}
    disabled={!hydrated}
    onChange={(event) => window.location.assign(event.currentTarget.selectedOptions[0]?.dataset.href || event.currentTarget.value)}>
    <option value="" disabled={Boolean(value)}>{placeholder}</option>
    {options.map((item) => <option data-href={item.href} key={item.value} value={item.value}>{item.label}</option>)}
  </select></label>;
}
