const modules = [
  "AU MarketProfile configured",
  "DTC Prompt Pack: 100",
  "AI Answer Runner",
  "Raw Evidence Store",
  "Audit / Provenance",
  "AUVisibilityScore",
  "Evidence Report"
];

export default function Home() {
  return (
    <main className="shell">
      <section className="header">
        <div>
          <p className="eyebrow">GENO SaaS AU</p>
          <h1>Evidence-first AI Search Visibility</h1>
        </div>
        <span className="status">M1 bootstrap</span>
      </section>
      <section className="grid">
        {modules.map((module) => (
          <article key={module} className="tile">
            <span>{module}</span>
          </article>
        ))}
      </section>
    </main>
  );
}
