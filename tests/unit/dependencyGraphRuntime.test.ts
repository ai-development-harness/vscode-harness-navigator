import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Script } from 'node:vm';
import * as esbuild from 'esbuild';
import { readFileSync } from 'node:fs';
import { dependencyGraphHtml } from '../../src/projectGraph/dependencyGraphWebview';
import { presentDependencyGraph } from '../../src/projectGraph/dependencyGraphPresentation';
import { parseProjectStatePayload } from '../../src/projectGraph/projectStatePayload';
import { projectStateFixture } from './fixtures/projectState';
import type { DependencyGraphPresentation } from '../../src/projectGraph/dependencyGraphPresentation';

/** Адаптер запускает ровно serialized WebView runtime без второго алгоритма rendering. */
class Element {
  children: Element[] = [];
  attributes: Record<string, string> = {};
  className = '';
  textContent = '';
  value = '';
  checked = false;
  onclick?: () => void;
  onchange?: () => void;
  oninput?: () => void;
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
    if (key === 'viewBox') {
      const [x = 0, y = 0, width = 1000, height = 600] = value.split(' ').map(Number);
      this.viewBox.baseVal = { x, y, width, height };
    }
  }
  getComputedTextLength() {
    return Array.from(this.textContent).length * 7;
  }
  classList = { toggle: () => undefined };
  addEventListener(type: string, listener: () => void) {
    if (type === 'click') this.onclick = listener;
  }
  closest() {
    return undefined;
  }
  setPointerCapture() {}
  getBoundingClientRect() {
    return { width: 800, height: 600 };
  }
  scrollIntoView() {}
  focus() {}
  select() {}
}

function render(model: DependencyGraphPresentation) {
  const html = dependencyGraphHtml({ cspSource: 'local' }, model);
  const source = html.match(/<script nonce="[^"]+">([\s\S]*)<\/script>/u)?.[1];
  assert.ok(source);
  const elements = new Map<string, Element>();
  const byId = (id: string) => {
    const existing = elements.get(id);
    if (existing) return existing;
    const created = new Element(id);
    elements.set(id, created);
    return created;
  };
  const messages: unknown[] = [];
  let update: ((event: unknown) => void) | undefined;
  new Script(source).runInNewContext({
    document: {
      getElementById: byId,
      createElement: (tag: string) => new Element(tag),
      createElementNS: (_: string, tag: string) => new Element(tag),
    },
    acquireVsCodeApi: () => ({ postMessage: (message: unknown) => messages.push(message) }),
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    window: {
      addEventListener: (_: string, listener: (event: unknown) => void) => {
        update = listener;
      },
    },
  });
  return {
    html,
    byId,
    messages,
    update: (modelUpdate: DependencyGraphPresentation) =>
      update?.({ data: { type: 'model', model: modelUpdate } }),
  };
}

function fixtureModel() {
  const parsed = parseProjectStatePayload(projectStateFixture());
  if (parsed.kind !== 'valid') throw new Error('fixture must parse');
  return presentDependencyGraph({ kind: 'ready', payload: parsed.payload });
}

test('shipped script строит overview, SVG и локальные presets без API message', () => {
  const view = render(fixtureModel());
  assert.match(view.html, /Project overview/u);
  assert.ok(view.byId('overview').children.length > 0);
  assert.ok(view.byId('graph').children.some((node) => node.tag === 'g'));
  const buttons = view.byId('presets').children.filter((node) => node.tag === 'button');
  buttons.find((node) => node.textContent === 'STEP dependencies')?.onclick?.();
  assert.equal(view.byId('graph').children.filter((node) => node.tag === 'g').length, 2);
  assert.equal(view.messages.length, 0);
});

test('selection, MISSING и model refresh сохраняют narrow ID-based contract', () => {
  const model = fixtureModel();
  const view = render(model);
  const node = view
    .byId('graph')
    .children.find((item) => item.attributes['aria-label']?.startsWith('STEP-002'));
  node?.onclick?.();
  assert.equal(
    JSON.stringify(view.messages.at(-1)),
    JSON.stringify({ type: 'select', id: 'STEP-002' }),
  );
  view.update({ ...model, nodes: model.nodes.filter((item) => item.id !== 'STEP-002') });
  assert.ok(view.byId('graph-inspector').children.length > 0);
});

test('preset Blockers показывает только seed и direct neighbours без транзитивного expansion', () => {
  const model: DependencyGraphPresentation = {
    state: 'ready',
    nodes: ['STEP-019', 'STEP-018', 'REQ-001'].map((id) => ({
      id,
      kind: 'STEP' as const,
      metadata: {},
    })),
    edges: [
      { from: 'STEP-019', to: 'STEP-018', type: 'depends_on', declaredBy: [] },
      { from: 'STEP-018', to: 'REQ-001', type: 'depends_on', declaredBy: [] },
    ],
    insights: { blockers: [{ nodeId: 'STEP-019' }], dependency: { cycles: [] } },
    longestDependencyChain: undefined,
  };
  const view = render(model);
  view
    .byId('presets')
    .children.find((node) => node.textContent === 'Blockers')
    ?.onclick?.();
  const ids = view
    .byId('graph')
    .children.filter((node) => node.tag === 'g')
    .map((node) => node.attributes['aria-label']);
  assert.deepEqual(ids.sort(), ['STEP-018', 'STEP-019']);
});

test('F-001: longest chain подсвечивает существующие reverse depends_on из captured API', () => {
  const wire = JSON.parse(
    readFileSync('tests/unit/fixtures/dependencyGraphApi.json', 'utf8'),
  ) as Record<string, unknown>;
  const parsed = parseProjectStatePayload(wire);
  if (parsed.kind !== 'valid') throw new Error('captured fixture must parse');
  const model = presentDependencyGraph({ kind: 'ready', payload: parsed.payload });
  const view = render(model);
  view
    .byId('toolbar')
    .children.find((node) => node.textContent === 'Longest dependency chain')
    ?.onclick?.();
  const chain = ((wire.insights as Record<string, unknown>).dependency as Record<string, unknown>)
    .longestChain as string[];
  const pairs = new Set(
    chain.slice(0, -1).map((id, index) => [id, chain[index + 1]].sort().join('\0')),
  );
  const expected = model.edges.filter(
    (edge) => edge.type === 'depends_on' && pairs.has([edge.from, edge.to].sort().join('\0')),
  );
  const highlighted = view
    .byId('graph')
    .children.filter((node) => node.tag === 'path' && node.attributes.class?.includes(' chain'));
  assert.equal(highlighted.length, expected.length);
  assert.equal(highlighted.length, 9);
  assert.deepEqual(
    highlighted
      .map((edge) => `${edge.attributes['data-source']}→${edge.attributes['data-target']}`)
      .sort(),
    expected.map((edge) => `${edge.from}→${edge.to}`).sort(),
  );
  assert.ok(highlighted.every((edge) => edge.attributes.class?.includes('depends_on')));
  assert.ok(highlighted.every((edge) => edge.attributes['marker-end'] === 'url(#arrow)'));
  assert.equal(view.messages.length, 0);
  view
    .byId('toolbar')
    .children.find((node) => node.textContent === 'Longest dependency chain')
    ?.onclick?.();
  assert.equal(
    view.byId('graph').children.filter((node) => node.attributes.class?.includes(' chain')).length,
    0,
  );
});

test('serialized production runtime сохраняет diagnostics и не выводит raw JSON containers', () => {
  const model = fixtureModel();
  const view = render(model);
  assert.ok(view.byId('diagnostics').children.length > 0);
  assert.doesNotMatch(view.html, /<pre(?:\s|>)/u);
  assert.match(view.html, /textContent/u);
});

test('status filter остаётся видимым при исчезновении matching status из нового snapshot', () => {
  const initial = fixtureModel();
  const view = render(initial);
  const status = view.byId('status-filter');
  status.value = 'blocked';
  status.onchange?.();
  view.update({
    ...initial,
    nodes: initial.nodes.map((n) => (n.status === 'blocked' ? { ...n, status: 'completed' } : n)),
  });
  assert.equal(status.value, 'blocked');
  assert.ok(status.children.some((option) => option.value === 'blocked'));
  assert.equal(view.byId('graph').children.filter((n) => n.tag === 'g').length, 0);
});

test('cold context open сохраняет pending focus через loading/error → ready с той же revision', () => {
  const ready = fixtureModel();
  const pending = presentDependencyGraph({ kind: 'error', error: 'loading' }, 'STEP-002');
  assert.equal(pending.focusId, 'STEP-002');
  const view = render({ ...pending, navigationRevision: 0 });
  view.update({
    ...presentDependencyGraph({ kind: 'error', error: 'malformed' }, 'STEP-002'),
    navigationRevision: 0,
  });
  view.update({ ...ready, navigationRevision: 0, selectedId: 'STEP-002', focusId: 'STEP-002' });
  const ids = view
    .byId('graph')
    .children.filter((n) => n.tag === 'g')
    .map((n) => n.attributes['aria-label']);
  assert.ok(ids.some((id) => id?.startsWith('STEP-002')));
  assert.ok(!ids.some((id) => id?.startsWith('SKILL:')));
  assert.ok(view.byId('graph-inspector').children.some((n) => n.textContent === 'STEP-002'));
});

/** Обычный Host echo не равен новому external reveal: client filters и viewport принадлежат panel. */
test('snapshot/selection echo сохраняют view/viewport, повторный reveal сбрасывает их, исчезнувший ID очищается', () => {
  const initial = { ...fixtureModel(), navigationRevision: 1 };
  const view = render(initial);
  const search = view.byId('search');
  search.value = 'STEP-002';
  search.oninput?.();
  const graph = view.byId('graph');
  const originalNode = graph.children.find((n) => n.tag === 'g');
  assert.ok(originalNode);
  originalNode.onclick?.();
  const zoom = view.byId('toolbar').children.find((n) => n.textContent === 'Zoom in');
  zoom?.onclick?.();
  const box = graph.attributes.viewBox;
  view.update({ ...initial, selectedId: 'STEP-002' });
  assert.equal(
    graph.children.find((n) => n.tag === 'g'),
    originalNode,
  );
  assert.equal(graph.attributes.viewBox, box);
  assert.equal(search.value, 'STEP-002');
  view.update({ ...initial, summary: { ...initial.summary, reviews: 123 } });
  assert.equal(search.value, 'STEP-002');
  assert.equal(graph.attributes.viewBox, box);
  view.update({ ...initial, navigationRevision: 2, focusId: 'STEP-001', selectedId: 'STEP-001' });
  assert.equal(search.value, '');
  search.value = 'absent';
  search.oninput?.();
  view.update({ ...initial, navigationRevision: 3, focusId: 'STEP-001', selectedId: 'STEP-001' });
  assert.equal(search.value, '');
  assert.ok(graph.children.some((n) => n.attributes['aria-label']?.startsWith('STEP-001')));
  view.update({
    ...initial,
    navigationRevision: 3,
    nodes: initial.nodes.filter((n) => n.id !== 'STEP-001'),
  });
  assert.ok(view.byId('graph-inspector').children.some((n) => n.className === 'empty-inspector'));
  assert.equal(view.messages.filter((m) => (m as { type: string }).type === 'refresh').length, 0);
});

test('dev и minified esbuild module сохраняют исполнимый shipped WebView factory', () => {
  for (const minify of [false, true]) {
    const output = esbuild.buildSync({
      entryPoints: ['src/projectGraph/dependencyGraphWebview.ts'],
      bundle: true,
      platform: 'node',
      format: 'cjs',
      write: false,
      minify,
    }).outputFiles[0];
    assert.ok(output);
    const module = { exports: {} as Record<string, unknown> };
    new Script(output.text).runInNewContext({
      module,
      exports: module.exports,
      require: () => ({}),
    });
    const html = (
      module.exports.dependencyGraphHtml as (
        webview: { cspSource: string },
        model: DependencyGraphPresentation,
      ) => string
    )({ cspSource: 'local' }, fixtureModel());
    assert.match(html, /<script nonce=/u);
    assert.match(html, /<svg/u);
    const source = html.match(/<script nonce="[^"]+">([\s\S]*)<\/script>/u)?.[1];
    assert.ok(source);
    const elements = new Map<string, Element>();
    const byId = (id: string) => {
      const existing = elements.get(id);
      if (existing) return existing;
      const created = new Element(id);
      elements.set(id, created);
      return created;
    };
    new Script(source).runInNewContext({
      document: {
        getElementById: byId,
        createElement: (tag: string) => new Element(tag),
        createElementNS: (_: string, tag: string) => new Element(tag),
      },
      acquireVsCodeApi: () => ({ postMessage: () => undefined }),
      navigator: { clipboard: { writeText: () => Promise.resolve() } },
      window: { addEventListener: () => undefined },
    });
    assert.ok(byId('graph').children.some((node) => node.tag === 'g'));
  }
});
