"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, WheelEvent } from "react";

export type InteractiveTraceabilityNode = {
  id: string;
  label: string;
  meta: string;
  href: string;
  x: number;
  y: number;
  tone: "report" | "score" | "evidence" | "source" | "action" | "draft" | "audit" | "link";
};

export type InteractiveTraceabilityEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
};

type Transform = {
  x: number;
  y: number;
  scale: number;
};

const viewBox = { width: 1020, height: 620 };
const nodeBounds = { minX: 70, maxX: viewBox.width - 70, minY: 44, maxY: viewBox.height - 44 };
const forceLayoutIterations = 72;

function clampScale(value: number): number {
  return Math.min(1.9, Math.max(0.58, value));
}

function clampPosition(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function computeForceDirectedLayout(
  sourceNodes: InteractiveTraceabilityNode[],
  sourceEdges: InteractiveTraceabilityEdge[]
): InteractiveTraceabilityNode[] {
  const nodes = sourceNodes.map((node) => ({
    ...node,
    x: clampPosition(node.x, nodeBounds.minX, nodeBounds.maxX),
    y: clampPosition(node.y, nodeBounds.minY, nodeBounds.maxY)
  }));
  const nodeIndex = new Map(nodes.map((node, index) => [node.id, index]));
  const links = sourceEdges.flatMap((edge) => {
    const from = nodeIndex.get(edge.from);
    const to = nodeIndex.get(edge.to);
    return from === undefined || to === undefined ? [] : [{ from, to }];
  });
  if (nodes.length < 3) return nodes;

  for (let iteration = 0; iteration < forceLayoutIterations; iteration += 1) {
    const forces = nodes.map(() => ({ x: 0, y: 0 }));
    for (let left = 0; left < nodes.length; left += 1) {
      for (let right = left + 1; right < nodes.length; right += 1) {
        const dx = nodes[right].x - nodes[left].x || 0.01;
        const dy = nodes[right].y - nodes[left].y || 0.01;
        const distanceSquared = Math.max(dx * dx + dy * dy, 1600);
        const distance = Math.sqrt(distanceSquared);
        const strength = Math.min(4.4, 9200 / distanceSquared);
        const pushX = (dx / distance) * strength;
        const pushY = (dy / distance) * strength;
        forces[left].x -= pushX;
        forces[left].y -= pushY;
        forces[right].x += pushX;
        forces[right].y += pushY;
      }
    }

    links.forEach((link) => {
      const from = nodes[link.from];
      const to = nodes[link.to];
      const dx = to.x - from.x || 0.01;
      const dy = to.y - from.y || 0.01;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const targetDistance = from.tone === "source" || to.tone === "source" ? 198 : 168;
      const strength = (distance - targetDistance) * 0.018;
      const pullX = (dx / distance) * strength;
      const pullY = (dy / distance) * strength;
      forces[link.from].x += pullX;
      forces[link.from].y += pullY;
      forces[link.to].x -= pullX;
      forces[link.to].y -= pullY;
    });

    nodes.forEach((node, index) => {
      const anchor = sourceNodes[index];
      forces[index].x += (anchor.x - node.x) * 0.025;
      forces[index].y += (anchor.y - node.y) * 0.025;
      node.x = clampPosition(node.x + forces[index].x * 0.82, nodeBounds.minX, nodeBounds.maxX);
      node.y = clampPosition(node.y + forces[index].y * 0.82, nodeBounds.minY, nodeBounds.maxY);
    });
  }
  return nodes.map((node) => ({ ...node, x: Math.round(node.x), y: Math.round(node.y) }));
}

function edgePath(from: InteractiveTraceabilityNode, to: InteractiveTraceabilityNode): string {
  const delta = Math.max(Math.abs(to.x - from.x) * 0.38, 44);
  const fromControl = from.x <= to.x ? from.x + delta : from.x - delta;
  const toControl = from.x <= to.x ? to.x - delta : to.x + delta;
  return `M ${from.x + 54} ${from.y} C ${fromControl} ${from.y}, ${toControl} ${to.y}, ${to.x - 54} ${to.y}`;
}

export function InteractiveTraceabilityMap({
  edges,
  nodes
}: {
  edges: InteractiveTraceabilityEdge[];
  nodes: InteractiveTraceabilityNode[];
}) {
  const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, scale: 0.92 });
  const [layoutNodes, setLayoutNodes] = useState<InteractiveTraceabilityNode[]>(() =>
    computeForceDirectedLayout(nodes, edges)
  );
  const [selectedId, setSelectedId] = useState(nodes[0]?.id || "");
  const [draggingNodeId, setDraggingNodeId] = useState("");
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(
    null
  );
  const nodeDragRef = useRef<{
    pointerId: number;
    nodeId: string;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    scale: number;
  } | null>(null);
  const nodeById = useMemo(() => new Map(layoutNodes.map((node) => [node.id, node])), [layoutNodes]);
  const selectedNode = nodeById.get(selectedId) || layoutNodes[0];

  useEffect(() => {
    setLayoutNodes(computeForceDirectedLayout(nodes, edges));
    setSelectedId((current) => (nodes.some((node) => node.id === current) ? current : nodes[0]?.id || ""));
    setDraggingNodeId("");
    nodeDragRef.current = null;
  }, [edges, nodes]);

  function zoomBy(multiplier: number): void {
    setTransform((current) => ({ ...current, scale: clampScale(current.scale * multiplier) }));
  }

  function fitMap(): void {
    setTransform({ x: 0, y: 0, scale: 0.82 });
  }

  function resetMap(): void {
    setTransform({ x: 0, y: 0, scale: 0.92 });
    setLayoutNodes(computeForceDirectedLayout(nodes, edges));
    setSelectedId(nodes[0]?.id || "");
  }

  function runForceLayout(): void {
    setLayoutNodes((current) => computeForceDirectedLayout(current, edges));
  }

  function resetNodePositions(): void {
    setLayoutNodes(computeForceDirectedLayout(nodes, edges));
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    if ((event.target as Element).closest("button,a")) return;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: transform.x,
      originY: transform.y
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setTransform((current) => ({
      ...current,
      x: drag.originX + event.clientX - drag.startX,
      y: drag.originY + event.clientY - drag.startY
    }));
  }

  function handlePointerEnd(event: PointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer capture may already be released if the pointer leaves the viewport.
    }
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>): void {
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const pointerX = ((event.clientX - bounds.left) / bounds.width) * viewBox.width;
    const pointerY = ((event.clientY - bounds.top) / bounds.height) * viewBox.height;
    setTransform((current) => {
      const nextScale = clampScale(current.scale * (event.deltaY > 0 ? 0.92 : 1.08));
      const ratio = nextScale / current.scale;
      return {
        x: pointerX - (pointerX - current.x) * ratio,
        y: pointerY - (pointerY - current.y) * ratio,
        scale: nextScale
      };
    });
  }

  function handleNodePointerDown(event: PointerEvent<SVGGElement>, nodeId: string): void {
    const node = nodeById.get(nodeId);
    if (!node) return;
    event.stopPropagation();
    setSelectedId(nodeId);
    setDraggingNodeId(nodeId);
    nodeDragRef.current = {
      pointerId: event.pointerId,
      nodeId,
      startX: event.clientX,
      startY: event.clientY,
      originX: node.x,
      originY: node.y,
      scale: transform.scale
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleNodePointerMove(event: PointerEvent<SVGGElement>): void {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const nextX = clampPosition(drag.originX + (event.clientX - drag.startX) / drag.scale, nodeBounds.minX, nodeBounds.maxX);
    const nextY = clampPosition(drag.originY + (event.clientY - drag.startY) / drag.scale, nodeBounds.minY, nodeBounds.maxY);
    setLayoutNodes((current) =>
      current.map((node) => (node.id === drag.nodeId ? { ...node, x: Math.round(nextX), y: Math.round(nextY) } : node))
    );
  }

  function handleNodePointerEnd(event: PointerEvent<SVGGElement>): void {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    nodeDragRef.current = null;
    setDraggingNodeId("");
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer capture may already be released if the pointer leaves the node.
    }
  }

  function selectNode(nodeId: string): void {
    setSelectedId(nodeId);
  }

  function handleNodeKeyDown(event: KeyboardEvent<SVGGElement>, nodeId: string): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectNode(nodeId);
    }
  }

  return (
    <div className="interactiveTraceabilityMap">
      <div className="interactiveTraceabilityToolbar" aria-label="Traceability map controls">
        <button aria-label="Zoom in" title="Zoom in" type="button" onClick={() => zoomBy(1.12)}>
          +
        </button>
        <button aria-label="Zoom out" title="Zoom out" type="button" onClick={() => zoomBy(0.88)}>
          -
        </button>
        <button aria-label="Fit map" title="Fit map" type="button" onClick={fitMap}>
          []
        </button>
        <button aria-label="Reset map" title="Reset map" type="button" onClick={resetMap}>
          1:1
        </button>
        <button aria-label="Run force-directed layout" title="Run force-directed layout" type="button" onClick={runForceLayout}>
          Layout
        </button>
        <button aria-label="Reset node positions" title="Reset node positions" type="button" onClick={resetNodePositions}>
          Nodes
        </button>
        <span>{Math.round(transform.scale * 100)}%</span>
      </div>
      <div
        className="interactiveTraceabilityViewport"
        onPointerCancel={handlePointerEnd}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
        onWheel={handleWheel}
      >
        <svg
          aria-label="Interactive runtime traceability graph"
          role="img"
          viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
        >
          <defs>
            <marker id="interactiveTraceabilityArrow" markerHeight="7" markerWidth="7" orient="auto" refX="6" refY="3.5">
              <path d="M 0 0 L 7 3.5 L 0 7 z" />
            </marker>
          </defs>
          <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.scale})`}>
            {edges.map((edge) => {
              const from = nodeById.get(edge.from);
              const to = nodeById.get(edge.to);
              if (!from || !to) return null;
              const midX = (from.x + to.x) / 2;
              const midY = (from.y + to.y) / 2;
              return (
                <g className="interactiveTraceabilityEdge" key={edge.id}>
                  <path d={edgePath(from, to)} markerEnd="url(#interactiveTraceabilityArrow)" />
                  <text x={midX} y={midY - 7}>
                    {edge.label}
                  </text>
                </g>
              );
            })}
            {layoutNodes.map((node) => {
              const selected = node.id === selectedNode?.id;
              return (
                <g
                  aria-label={`${node.label} ${node.meta}`}
                  className={`interactiveTraceabilityNode interactiveTraceabilityNode-${node.tone}${
                    selected ? " interactiveTraceabilityNodeSelected" : ""
                  }${draggingNodeId === node.id ? " interactiveTraceabilityNodeDragging" : ""}`}
                  key={node.id}
                  onClick={() => selectNode(node.id)}
                  onKeyDown={(event) => handleNodeKeyDown(event, node.id)}
                  onPointerCancel={handleNodePointerEnd}
                  onPointerDown={(event) => handleNodePointerDown(event, node.id)}
                  onPointerMove={handleNodePointerMove}
                  onPointerUp={handleNodePointerEnd}
                  role="button"
                  tabIndex={0}
                  transform={`translate(${node.x - 58} ${node.y - 27})`}
                >
                  <rect height="54" rx="7" width="116" />
                  <text className="interactiveTraceabilityNodeLabel" x="58" y="22" textAnchor="middle">
                    {node.label}
                  </text>
                  <text className="interactiveTraceabilityNodeMeta" x="58" y="39" textAnchor="middle">
                    {node.meta}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      {selectedNode ? (
        <div className="interactiveTraceabilityInspector">
          <div>
            <strong>{selectedNode.label}</strong>
            <span>{selectedNode.meta}</span>
          </div>
          <a className="nodeLink" href={selectedNode.href}>
            Open node
          </a>
        </div>
      ) : null}
    </div>
  );
}
