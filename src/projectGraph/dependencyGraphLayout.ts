import type { DependencyGraphPresentation } from './dependencyGraphPresentation';
import type { ProjectGraphNodeKind } from './projectStatePayload';

export interface GraphLayoutNode {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly lane: string;
}
export interface GraphLayoutEdge {
  readonly from: string;
  readonly to: string;
  readonly relation: string;
  readonly declaredBy: readonly string[];
  readonly reciprocal: boolean;
  readonly self: boolean;
}
export interface DependencyGraphLayout {
  readonly nodes: readonly GraphLayoutNode[];
  readonly edges: readonly GraphLayoutEdge[];
  readonly bounds: readonly [number, number, number, number];
}

/**
 * Стабильный lane layout используется и Host tests, и serialized WebView factory.
 * Колонки имеют ограниченное число строк, поэтому REVIEW не растягивает canvas вниз.
 */
export function layoutDependencyGraph(
  model: Pick<DependencyGraphPresentation, 'nodes' | 'edges'>,
): DependencyGraphLayout {
  const lanes: readonly ProjectGraphNodeKind[] = [
    'PROJECT',
    'REQ',
    'ADR',
    'STEP',
    'OQ',
    'REVIEW',
    'SKILL',
    'MISSING',
  ];
  const width = 220,
    height = 96,
    rowGap = 118;
  const placed: GraphLayoutNode[] = [];
  const ordered = new Map(
    lanes.map((lane) => [
      lane,
      model.nodes.filter((n) => n.kind === lane).sort((a, b) => a.id.localeCompare(b.id)),
    ]),
  );
  const neighbours = new Map<string, Set<string>>();
  model.edges.forEach((edge) => {
    if (edge.from === edge.to) return;
    for (const [id, other] of [
      [edge.from, edge.to],
      [edge.to, edge.from],
    ]) {
      if (!id || !other) continue;
      const values = neighbours.get(id) ?? new Set<string>();
      values.add(other);
      neighbours.set(id, values);
    }
  });
  // Два bounded barycenter sweep сближают соседей внутри type regions без новых graph facts.
  // Начальный ID order и ID tie-break сохраняют координаты при перестановке API arrays.
  for (let sweep = 0; sweep < 2; sweep++) {
    const ranks = new Map<string, number>();
    ordered.forEach((nodes) =>
      nodes.forEach((n, i) => ranks.set(n.id, i / Math.max(1, nodes.length - 1))),
    );
    const rank = (id: string) => {
      const values = [...(neighbours.get(id) ?? [])]
        .sort()
        .flatMap((other) => (ranks.has(other) ? [ranks.get(other) ?? 0] : []));
      return values.length
        ? values.reduce((sum, value) => sum + value, 0) / values.length
        : (ranks.get(id) ?? 0);
    };
    ordered.forEach((nodes) =>
      nodes.sort((a, b) => rank(a.id) - rank(b.id) || a.id.localeCompare(b.id)),
    );
  }
  // Каждая region содержит только один тип; три region в строке дают сбалансированный обзор.
  // Пустые типы не оставляют holes, а stable ordering уменьшает зависимость от API order.
  const present = lanes.filter((kind) => model.nodes.some((node) => node.kind === kind));
  let rowY = 52;
  for (let offset = 0; offset < present.length; offset += 3) {
    const regions = present.slice(offset, offset + 3);
    let columnX = 42,
      maxHeight = 0;
    for (const lane of regions) {
      const laneNodes = ordered.get(lane) ?? [];
      const columns = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(laneNodes.length / 1.4))));
      laneNodes.forEach((node, index) =>
        placed.push({
          id: node.id,
          x: columnX + (index % columns) * (width + 28),
          y: rowY + Math.floor(index / columns) * rowGap,
          width,
          height,
          lane,
        }),
      );
      maxHeight = Math.max(maxHeight, Math.ceil(laneNodes.length / columns) * rowGap);
      columnX += columns * (width + 28) + 64;
    }
    rowY += maxHeight + 80;
  }
  const ids = new Set(placed.map((node) => node.id));
  const edges = model.edges
    .filter((edge) => ids.has(edge.from) && ids.has(edge.to))
    .map((edge) => ({
      from: edge.from,
      to: edge.to,
      relation: edge.type,
      declaredBy: edge.declaredBy,
      reciprocal: model.edges.some(
        (other) => other.from === edge.to && other.to === edge.from && other.type === edge.type,
      ),
      self: edge.from === edge.to,
    }));
  return {
    nodes: placed,
    edges,
    bounds: [
      0,
      0,
      Math.max(380, ...placed.map((node) => node.x + node.width + 42)),
      Math.max(240, ...placed.map((node) => node.y + node.height + 52)),
    ],
  };
}
