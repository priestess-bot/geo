export function mergeCssModules(
  ...sources: ReadonlyArray<Readonly<Record<string, string>>>
): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const source of sources) {
    for (const [name, className] of Object.entries(source)) {
      merged[name] = merged[name] ? `${merged[name]} ${className}` : className;
    }
  }
  return merged;
}
