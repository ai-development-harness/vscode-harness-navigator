import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Script } from 'node:vm';
import { dependencyGraphHtml } from '../../src/projectGraph/dependencyGraphWebview';
import { presentDependencyGraph } from '../../src/projectGraph/dependencyGraphPresentation';
import { parseProjectStatePayload } from '../../src/projectGraph/projectStatePayload';
import { projectStateFixture } from './fixtures/projectState';
import type { DependencyGraphPresentation } from '../../src/projectGraph/dependencyGraphPresentation';

/** Минимальный DOM adapter исполняет именно shipped script, а не второй UI алгоритм. */
class Element {
  children: Element[] = [];
  attributes: Record<string, string> = {};
  textContent = '';
  value = '';
  checked = false;
  onclick?: () => void;
  onchange?: () => void;
  viewBox = { baseVal: { x: 0, y: 0, width: 1000, height: 600 } };
  constructor(readonly tag: string) {}
  append(...children: Element[]) {
    this.children.push(...children);
  }
  replaceChildren(...children: Element[]) {
    this.children = children;
  }
  setAttribute(key: string, value: string) {
    this.attributes[key] = value;
  }
  /** Предсказуемая метрика для runtime regression; реальные шрифты проверяются в браузере. */
  getComputedTextLength() {
    return Array.from(this.textContent).length * 7;
  }
}

/** Общий adapter исполняет production script для разных canonical API snapshots. */
function renderWebview(model: DependencyGraphPresentation) {
  const html = dependencyGraphHtml({ cspSource: 'local' }, model);
  const scriptText = html.match(/<script nonce="[^"]+">([\s\S]*)<\/script>/u)?.[1];
  assert.ok(scriptText);
  const script = new Script(scriptText);
  const elements = new Map<string, Element>();
  const el = (id: string) => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id) as Element;
  };
  const messages: unknown[] = [];
  let update: ((event: unknown) => void) | undefined;
  script.runInNewContext({
    document: {
      getElementById: el,
      createElement: (tag: string) => new Element(tag),
      createElementNS: (_ns: string, tag: string) => new Element(tag),
      createTextNode: (text: string) => {
        const e = new Element('text');
        e.textContent = text;
        return e;
      },
    },
    acquireVsCodeApi: () => ({ postMessage: (message: unknown) => messages.push(message) }),
    window: {
      addEventListener: (_type: string, listener: (event: unknown) => void) => {
        update = listener;
      },
    },
  });
  const nodes = () => el('graph').children.filter((n) => n.tag === 'g');
  return { el, nodes, messages, update: (event: unknown) => update?.(event) };
}

test('shipped WebView script: syntax, SVG selection/details, filters, STEP mode, reset/fit', () => {
  const payload = parseProjectStatePayload(projectStateFixture());
  if (payload.kind !== 'valid') throw new Error('fixture must parse');
  const model = presentDependencyGraph({ kind: 'ready', payload: payload.payload });
  const { el, nodes, messages, update } = renderWebview(model);
  assert.equal(nodes().length, 9);
  nodes()
    .find((n) => n.attributes['aria-label'] === 'STEP-002')
    ?.onclick?.();
  assert.ok(el('details').children.some((n) => n.textContent.includes('STEP-002')));
  assert.ok(nodes().some((n) => n.attributes.class?.includes('selected')));
  assert.equal(JSON.stringify(messages.at(-1)), JSON.stringify({ type: 'select', id: 'STEP-002' }));
  const selects = el('toolbar')
    .children.flatMap((n) => n.children)
    .filter((n) => n.tag === 'select');
  const kinds = selects[0] as Element,
    statuses = selects[1] as Element,
    relations = selects[2] as Element;
  kinds.value = 'MISSING';
  kinds.onchange?.();
  assert.equal(nodes().length, 1);
  kinds.value = '';
  statuses.value = 'blocked';
  statuses.onchange?.();
  assert.equal(nodes().length, 1);
  statuses.value = '';
  relations.value = 'reviews';
  relations.onchange?.();
  assert.equal(el('graph').children.filter((n) => n.attributes.class === 'edge').length, 1);
  const mode = el('toolbar')
    .children.flatMap((n) => n.children)
    .find((n) => n.tag === 'input') as Element;
  relations.value = '';
  mode.checked = true;
  mode.onchange?.();
  assert.equal(nodes().length, 2);
  assert.equal(el('graph').children.filter((n) => n.attributes.class === 'edge').length, 2);
  el('toolbar')
    .children.find((n) => n.textContent === 'Full graph')
    ?.onclick?.();
  assert.equal(nodes().length, 9);
  assert.equal(mode.checked, false);
  assert.ok(el('graph').attributes.viewBox);
  // Initial loading panel получает statuses только после async ответа API.
  update?.({
    data: {
      type: 'model',
      model: { ...model, nodes: model.nodes.map((n) => ({ ...n, status: 'new-state' })) },
    },
  });
  assert.ok(statuses.children.some((n) => n.value === 'new-state'));
});

test('текущий STEP выделяется независимо от blocked REVIEW, длинные подписи остаются внутри узла', () => {
  const reviewId = 'REVIEW:STEP-002:REVIEW-20260922T064000Z';
  const model: DependencyGraphPresentation = {
    state: 'ready',
    nodes: [
      { id: 'STEP-018', kind: 'STEP', status: 'in_progress', metadata: {} },
      { id: 'STEP-002', kind: 'STEP', status: 'completed', metadata: {} },
      {
        id: reviewId,
        kind: 'REVIEW',
        status: 'blocked',
        title: 'Исторический отчёт',
        metadata: {},
      },
      { id: 'REQ-011', kind: 'REQ', status: 'очень-длинный-статус-без-пробелов', metadata: {} },
    ],
    edges: [],
    longestDependencyChain: undefined,
  };
  const { el, nodes, update } = renderWebview(model);
  const activeIds = () =>
    nodes()
      .filter((n) => n.attributes.class?.split(' ').includes('active'))
      .map((n) => n.attributes['aria-label']);
  assert.deepEqual(activeIds(), ['STEP-018']);
  assert.equal(el('legend').children.length, 4);
  const review = nodes().find((n) => n.attributes['aria-label'] === reviewId);
  assert.ok(review);
  assert.ok(review.attributes.class?.includes('blocked'));
  const reviewText = review.children.find((n) => n.tag === 'text');
  assert.ok(reviewText?.textContent.endsWith('…'));
  assert.ok(review.children.find((n) => n.tag === 'title')?.textContent.includes(reviewId));
  for (const node of nodes()) {
    for (const label of node.children.filter((n) => n.tag === 'text')) {
      assert.ok(label.getComputedTextLength() <= 170);
      assert.equal(label.attributes['clip-path'], 'url(#node-label-clip)');
    }
  }
  review.onclick?.();
  assert.ok(el('details').children.some((n) => n.textContent.includes(reviewId)));
  assert.deepEqual(activeIds(), ['STEP-018'], 'выбор REVIEW не меняет canonical active status');
  update({
    data: {
      type: 'model',
      model: {
        ...model,
        nodes: model.nodes.map((n) => ({ ...n, status: 'completed' })),
      },
    },
  });
  assert.deepEqual(activeIds(), [], 'refresh снимает подсветку завершённого STEP');
});

test('title виден после ID: перенос, сокращение, отсутствие названия и обновление snapshot', () => {
  const title = 'Качество и тестируемость';
  const longTitle =
    'Очень длинное название артефакта с дополнительными подробностями и пояснениями';
  const model: DependencyGraphPresentation = {
    state: 'ready',
    nodes: [
      { id: 'REQ-010', kind: 'REQ', title, metadata: {} },
      { id: 'STEP-018', kind: 'STEP', title: longTitle, status: 'in_progress', metadata: {} },
      { id: 'ADR-008', kind: 'ADR', title: 'НазваниеБезПробелов'.repeat(8), metadata: {} },
      { id: 'OQ-001', kind: 'OQ', metadata: {} },
      { id: 'OQ-002', kind: 'OQ', title: '  \n ', metadata: {} },
    ],
    edges: [{ from: 'REQ-010', to: 'STEP-018', type: 'implemented_by', declaredBy: [] }],
    longestDependencyChain: undefined,
  };
  const { nodes, update } = renderWebview(model);
  const labels = (id: string) =>
    nodes()
      .find((node) => node.attributes['aria-label'] === id)
      ?.children.filter((child) => child.tag === 'text') as Element[];
  assert.deepEqual(
    labels('REQ-010').map((label) => label.textContent),
    ['REQ-010', title, 'REQ · '],
  );
  for (const id of ['STEP-018', 'ADR-008']) {
    const lines = labels(id);
    assert.equal(lines.length, 5, 'ID, три строки названия и статус');
    assert.ok(lines[3]?.textContent.endsWith('…'));
    assert.equal(lines.at(-1)?.attributes.y, '99');
    for (const line of lines) assert.ok(line.getComputedTextLength() <= 170);
  }
  for (const id of ['OQ-001', 'OQ-002']) {
    assert.equal(labels(id).length, 2);
    assert.equal(labels(id).at(-1)?.attributes.y, '46');
  }
  const step = nodes().find((node) => node.attributes['aria-label'] === 'STEP-018');
  assert.equal(step?.attributes['aria-description'], longTitle);
  assert.ok(step?.children.find((child) => child.tag === 'title')?.textContent.includes(longTitle));
  update({
    data: {
      type: 'model',
      model: { ...model, nodes: [{ ...model.nodes[0], title: 'Новое название' }] },
    },
  });
  assert.equal(labels('REQ-010')[1]?.textContent, 'Новое название');
});

test('стрелки находятся вне target rect и сохраняют противоположные направления API', () => {
  const ids = ['STEP-001', 'STEP-002', 'STEP-003', 'STEP-004'];
  const model: DependencyGraphPresentation = {
    state: 'ready',
    nodes: ids.map((id, index) => ({
      id,
      kind: 'STEP',
      metadata: {},
      ...(index % 2 ? { title: 'Название' } : {}),
    })),
    edges: ids.flatMap((from) =>
      ids.map((to) => ({ from, to, type: 'depends_on', declaredBy: [] })),
    ),
    longestDependencyChain: undefined,
  };
  const { el, nodes } = renderWebview(model);
  const paths = el('graph').children.filter((node) => node.attributes.class === 'edge');
  assert.equal(paths.length, 16);
  for (const edge of paths) {
    const target = nodes().find(
      (node) => node.attributes['aria-label'] === edge.attributes['data-target'],
    );
    assert.ok(target);
    const position = target.attributes.transform?.match(/translate\(([^,]+),([^)]+)\)/u);
    const coordinates = edge.attributes.d?.match(/-?\d+(?:\.\d+)?/gu)?.map(Number);
    assert.ok(position && coordinates);
    const x = coordinates.at(-2) as number,
      y = coordinates.at(-1) as number;
    const tx = Number(position[1]),
      ty = Number(position[2]);
    const height = Number(target.children.find((child) => child.tag === 'rect')?.attributes.height);
    assert.ok(
      x < tx || x > tx + 190 || y < ty || y > ty + height,
      'marker endpoint не скрыт target',
    );
    assert.equal(
      edge.children[0]?.textContent,
      `${edge.attributes['data-source']} → ${edge.attributes['data-target']} · depends_on`,
    );
  }
  assert.notEqual(
    paths[1]?.attributes.d,
    paths[4]?.attributes.d,
    'обратное relation имеет другую стрелку',
  );
});
