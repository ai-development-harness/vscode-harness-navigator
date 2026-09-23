import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  COMMAND_GRAPH_RELATIVE_PATH,
  loadCatalogForRoot,
  parseCommandGraph,
  type CommandCatalog,
} from '../../src/commandCatalog/commandGraph';
import { MAXIMUM_MARKDOWN_SIZE_BYTES } from '../../src/projectModel/artifactIndex';

const here = path.dirname(fileURLToPath(import.meta.url));
const snapshotText = readFileSync(
  path.join(here, 'fixtures/command-transitions.snapshot.json'),
  'utf8',
);

function readyCatalog(text: string): CommandCatalog {
  const parsed = parseCommandGraph(text);
  assert.equal(parsed.kind, 'ready');
  if (parsed.kind !== 'ready') throw new Error('unreachable');
  return parsed.catalog;
}

type Graph = Record<string, unknown> & {
  domains: Record<string, { commands: Record<string, unknown> } | string>;
};

function graphWith(mutate: (graph: Graph) => void): string {
  const graph = JSON.parse(snapshotText) as Graph;
  mutate(graph);
  return JSON.stringify(graph);
}

function stepCommandsOf(graph: Graph): Record<string, unknown> {
  const step = graph.domains.STEP;
  if (step === undefined || typeof step === 'string') throw new Error('unexpected');
  return step.commands;
}

function tempRoot(): string {
  return mkdtempSync(path.join(tmpdir(), 'command-graph-'));
}

function writeGraph(root: string, text: string): void {
  mkdirSync(path.join(root, '.harness'), { recursive: true });
  writeFileSync(path.join(root, COMMAND_GRAPH_RELATIVE_PATH), text);
}

test('снимок графа даёт 7 доменов и 32 команды в порядке графа', () => {
  const catalog = readyCatalog(snapshotText);
  assert.deepEqual(
    catalog.domains.map((domain) => domain.name),
    ['PROJECT', 'STEP', 'SKILL', 'GITHUB', 'RELEASE', 'HARNESS', 'GIT'],
  );
  assert.equal(catalog.commands.length, 32);
  assert.deepEqual(catalog.skipped, []);
});

test('canonical, target, input и chain metadata выводятся из графа', () => {
  const catalog = readyCatalog(snapshotText);
  const byCanonical = new Map(catalog.commands.map((command) => [command.canonical, command]));
  const plan = byCanonical.get('STEP PLAN STEP-NNN');
  assert.ok(plan);
  assert.equal(plan.domain, 'STEP');
  assert.equal(plan.operation, 'PLAN');
  assert.equal(plan.target, 'step');
  assert.equal(plan.input, 'none');
  assert.equal(plan.chainAllowed, true);
  assert.equal(plan.dispatchKind, 'semantic');
  assert.deepEqual(
    plan.outgoing.map((transition) => transition.to),
    ['IMPLEMENT'],
  );
  assert.equal(byCanonical.get('PROJECT QUICK FIX:')?.input, 'required');
  assert.equal(byCanonical.get('GIT COMMIT')?.input, 'optional');
  assert.equal(byCanonical.get('HARNESS UPDATE CHECK')?.target, 'release-optional');
  const step = catalog.domains.find((domain) => domain.name === 'STEP');
  assert.equal(step?.chainEnabled, true);
  assert.equal(step?.inheritTarget, true);
  const harness = catalog.domains.find((domain) => domain.name === 'HARNESS');
  assert.deepEqual(harness?.continuationAliases, { APPLY: 'UPDATE APPLY' });
});

test('schemaVersion 2 или отсутствие даёт unsupportedSchema', () => {
  assert.equal(
    parseCommandGraph(graphWith((graph) => (graph.schemaVersion = 2))).kind,
    'unsupportedSchema',
  );
  assert.equal(
    parseCommandGraph(graphWith((graph) => delete graph.schemaVersion)).kind,
    'unsupportedSchema',
  );
});

test('невалидный JSON, массив и примитив дают readError', () => {
  for (const text of ['{ not json', '[]', '42', 'null', '"x"'])
    assert.equal(parseCommandGraph(text).kind, 'readError', text);
  assert.equal(parseCommandGraph('{"schemaVersion":1,"domains":[]}').kind, 'readError');
});

test('будущая команда и неизвестные target/input сохраняются', () => {
  const catalog = readyCatalog(
    graphWith((graph) => {
      stepCommandsOf(graph).FUTURE = {
        canonical: 'STEP FUTURE STEP-NNN',
        chainAllowed: false,
        target: 'quantum',
        input: 'maybe',
        summary: 'Future command.',
        dispatch: { kind: 'telepathy' },
      };
    }),
  );
  const future = catalog.commands.find((command) => command.canonical === 'STEP FUTURE STEP-NNN');
  assert.equal(future?.target, 'quantum');
  assert.equal(future?.input, 'maybe');
  assert.equal(future?.dispatchKind, 'telepathy');
  assert.equal(catalog.commands.length, 33);
});

test('одна malformed команда пропускается и попадает в skipped', () => {
  const catalog = readyCatalog(
    graphWith((graph) => {
      stepCommandsOf(graph).LIST = { canonical: 42 };
    }),
  );
  assert.equal(catalog.commands.length, 31);
  assert.deepEqual(catalog.skipped, ['STEP/LIST']);
});

test('malformed домен пропускается без падения каталога', () => {
  const catalog = readyCatalog(
    graphWith((graph) => {
      graph.domains.SKILL = 'oops';
    }),
  );
  assert.deepEqual(catalog.skipped, ['SKILL']);
  assert.equal(catalog.domains.length, 6);
});

test('loadCatalogForRoot: ready для валидного графа', () => {
  const root = tempRoot();
  try {
    writeGraph(root, snapshotText);
    const state = loadCatalogForRoot(root);
    assert.equal(state.kind, 'ready');
    assert.deepEqual(state.diagnostics, []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('loadCatalogForRoot: отсутствующий файл, malformed JSON и oversize дают CommandGraphReadError', () => {
  const root = tempRoot();
  try {
    let state = loadCatalogForRoot(root);
    assert.equal(state.kind, 'readError');
    assert.equal(state.diagnostics[0]?.category, 'CommandGraphReadError');
    writeGraph(root, '{ nope');
    state = loadCatalogForRoot(root);
    assert.equal(state.kind, 'readError');
    assert.equal(state.diagnostics[0]?.category, 'CommandGraphReadError');
    assert.equal(state.diagnostics[0]?.detail, '');
    writeGraph(root, ' '.repeat(MAXIMUM_MARKDOWN_SIZE_BYTES + 1));
    assert.equal(loadCatalogForRoot(root).kind, 'readError');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('loadCatalogForRoot: unsupported schema даёт CommandGraphUnsupportedSchema', () => {
  const root = tempRoot();
  try {
    writeGraph(root, '{"schemaVersion":2,"domains":{}}');
    const state = loadCatalogForRoot(root);
    assert.equal(state.kind, 'unsupportedSchema');
    assert.equal(state.diagnostics[0]?.category, 'CommandGraphUnsupportedSchema');
    assert.deepEqual(state.diagnostics[0]?.messageArguments, ['2']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('loadCatalogForRoot: symlink на файл вне root даёт readError', () => {
  const root = tempRoot();
  const outside = tempRoot();
  try {
    writeFileSync(path.join(outside, 'graph.json'), snapshotText);
    mkdirSync(path.join(root, '.harness'), { recursive: true });
    symlinkSync(path.join(outside, 'graph.json'), path.join(root, COMMAND_GRAPH_RELATIVE_PATH));
    assert.equal(loadCatalogForRoot(root).kind, 'readError');
  } finally {
    rmSync(root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});
