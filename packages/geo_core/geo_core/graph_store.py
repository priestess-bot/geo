from __future__ import annotations

from dataclasses import asdict
from typing import Any

from geo_core.models import CitationGraphResult


class InMemoryPostgresAdjacencyGraphStore:
    """GraphStore-compatible projection that mirrors the MVP PostgreSQL adjacency shape."""

    store_id = "graph_store.postgres_adjacency.memory"

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.evidence_edges: list[dict[str, Any]] = []
        self.source_gaps: list[dict[str, Any]] = []
        self.competitor_benchmarks: list[dict[str, Any]] = []

    def upsert_node(self, *, node_type: str, node_id: str, properties: dict[str, Any]) -> None:
        self.nodes[node_id] = {"node_type": node_type, "node_id": node_id, **properties}

    def query(self, *, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        project_id = str(params.get("project_id", ""))
        if query_name == "source_nodes_by_project":
            return sorted(
                (
                    node
                    for node in self.nodes.values()
                    if node["node_type"] == "source" and str(node.get("project_id")) == project_id
                ),
                key=lambda item: (str(item["source_domain"]), str(item["source_type"])),
            )
        if query_name == "evidence_links_by_project":
            source_ids = {
                node["node_id"]
                for node in self.nodes.values()
                if node["node_type"] == "source" and str(node.get("project_id")) == project_id
            }
            return sorted(
                (edge for edge in self.evidence_edges if edge["source_graph_id"] in source_ids),
                key=lambda item: (str(item["source_graph_id"]), str(item["answer_run_id"]), str(item["id"])),
            )
        if query_name == "source_gaps_by_project":
            return sorted(
                (gap for gap in self.source_gaps if str(gap.get("project_id")) == project_id),
                key=lambda item: (str(item["source_type"]), str(item["gap_type"])),
            )
        if query_name == "competitor_benchmarks_by_project":
            return sorted(
                (benchmark for benchmark in self.competitor_benchmarks if str(benchmark.get("project_id")) == project_id),
                key=lambda item: str(item["competitor_name"]),
            )
        raise ValueError(f"Unsupported graph query: {query_name}")

    def save_citation_graph(self, *, project_id: str, graph: CitationGraphResult) -> None:
        for node in graph.nodes:
            self.upsert_node(node_type="source", node_id=node.id, properties=asdict(node))
        for evidence in graph.evidence_links:
            self.evidence_edges.append(asdict(evidence))
        for gap in graph.source_gaps:
            self.source_gaps.append({"project_id": project_id, **asdict(gap)})
        for benchmark in graph.competitor_benchmarks:
            self.competitor_benchmarks.append(asdict(benchmark))


class InMemoryNeo4jCitationGraphStore:
    """GraphStore-compatible projection that mirrors a Neo4j node/relation shape."""

    store_id = "graph_store.neo4j.memory"

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.relationships: list[dict[str, Any]] = []

    def upsert_node(self, *, node_type: str, node_id: str, properties: dict[str, Any]) -> None:
        self.nodes[node_id] = {"labels": (node_type,), "node_id": node_id, "properties": dict(properties)}

    def query(self, *, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        project_id = str(params.get("project_id", ""))
        if query_name == "source_nodes_by_project":
            return sorted(
                (
                    dict(node["properties"])
                    for node in self.nodes.values()
                    if "Source" in node["labels"] and str(node["properties"].get("project_id")) == project_id
                ),
                key=lambda item: (str(item["source_domain"]), str(item["source_type"])),
            )
        if query_name == "evidence_links_by_project":
            source_ids = {
                node_id
                for node_id, node in self.nodes.items()
                if "Source" in node["labels"] and str(node["properties"].get("project_id")) == project_id
            }
            return sorted(
                (
                    {
                        "id": relationship["id"],
                        "source_graph_id": relationship["from_id"],
                        "answer_run_id": relationship["to_id"],
                        "answer_citation_id": relationship["properties"].get("answer_citation_id"),
                        "relation_type": relationship["type"],
                    }
                    for relationship in self.relationships
                    if relationship["type"] == "cited_by_answer" and relationship["from_id"] in source_ids
                ),
                key=lambda item: (str(item["source_graph_id"]), str(item["answer_run_id"]), str(item["id"])),
            )
        if query_name == "source_gaps_by_project":
            return sorted(
                (
                    dict(node["properties"])
                    for node in self.nodes.values()
                    if "SourceGap" in node["labels"] and str(node["properties"].get("project_id")) == project_id
                ),
                key=lambda item: (str(item["source_type"]), str(item["gap_type"])),
            )
        if query_name == "competitor_benchmarks_by_project":
            return sorted(
                (
                    dict(node["properties"])
                    for node in self.nodes.values()
                    if "CompetitorBenchmark" in node["labels"]
                    and str(node["properties"].get("project_id")) == project_id
                ),
                key=lambda item: str(item["competitor_name"]),
            )
        raise ValueError(f"Unsupported graph query: {query_name}")

    def save_citation_graph(self, *, project_id: str, graph: CitationGraphResult) -> None:
        for node in graph.nodes:
            self.upsert_node(node_type="Source", node_id=node.id, properties=asdict(node))
        for evidence in graph.evidence_links:
            self.upsert_node(
                node_type="AnswerRun",
                node_id=evidence.answer_run_id,
                properties={"id": evidence.answer_run_id, "project_id": project_id},
            )
            self.relationships.append(
                {
                    "id": evidence.id,
                    "from_id": evidence.source_graph_id,
                    "to_id": evidence.answer_run_id,
                    "type": evidence.relation_type,
                    "properties": {"answer_citation_id": evidence.answer_citation_id},
                }
            )
        for gap in graph.source_gaps:
            gap_id = f"{project_id}:source_gap:{gap.source_type}:{gap.gap_type}"
            self.upsert_node(node_type="SourceGap", node_id=gap_id, properties={"project_id": project_id, **asdict(gap)})
        for benchmark in graph.competitor_benchmarks:
            self.upsert_node(
                node_type="CompetitorBenchmark",
                node_id=benchmark.id,
                properties=asdict(benchmark),
            )


def summarize_citation_graph_store(store: Any, *, project_id: str) -> dict[str, Any]:
    source_nodes = store.query(query_name="source_nodes_by_project", params={"project_id": project_id})
    evidence_links = store.query(query_name="evidence_links_by_project", params={"project_id": project_id})
    source_gaps = store.query(query_name="source_gaps_by_project", params={"project_id": project_id})
    competitor_benchmarks = store.query(
        query_name="competitor_benchmarks_by_project",
        params={"project_id": project_id},
    )
    return {
        "source_domains": tuple(sorted(str(node["source_domain"]) for node in source_nodes)),
        "source_types": tuple(sorted(str(node["source_type"]) for node in source_nodes)),
        "source_node_count": len(source_nodes),
        "evidence_link_count": len(evidence_links),
        "source_gap_types": tuple(sorted(str(gap["gap_type"]) for gap in source_gaps)),
        "competitor_names": tuple(sorted(str(item["competitor_name"]) for item in competitor_benchmarks)),
        "competitor_mention_counts": tuple(
            (str(item["competitor_name"]), int(item["mention_count"])) for item in competitor_benchmarks
        ),
    }
