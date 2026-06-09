from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI

from geno_core.market import build_au_market_profile

app = FastAPI(title="GENO SaaS AU API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geno-saas-au-api"}


@app.get("/v1/market-profiles/au")
def au_market_profile() -> dict[str, object]:
    return asdict(build_au_market_profile())


@app.get("/v1/contracts")
def contracts() -> dict[str, list[str]]:
    return {
        "interfaces": [
            "CollectorBackend",
            "LLMGateway",
            "ParserEngine",
            "VectorStore",
            "GraphStore",
            "GeoProvider",
            "ScoringFormula",
            "ReportExporter",
        ],
        "auditability": [
            "AuditEvent",
            "EvidenceLink",
            "ScoreContribution",
            "ReportExport",
        ],
    }
