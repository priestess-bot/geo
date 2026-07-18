"use client";

import styles from "./GeoWorkspace.module.css";

export function RouteSelect({ label, options, value }: {
  label: string;
  options: Array<{ href: string; label: string; value: string }>;
  value?: string;
}) {
  return <label className={styles.routeSelect}><span>{label}</span><select aria-label={label} value={value || ""}
    onChange={(event) => window.location.assign(event.currentTarget.selectedOptions[0]?.dataset.href || event.currentTarget.value)}>
    {options.map((item) => <option data-href={item.href} key={item.value} value={item.value}>{item.label}</option>)}
  </select></label>;
}
