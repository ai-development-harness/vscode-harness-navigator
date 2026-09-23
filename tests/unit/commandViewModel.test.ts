import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCommandGraph, type CatalogCommand } from '../../src/commandCatalog/commandGraph';
import {
  COMMAND_CATALOG_MESSAGES,
  COMMAND_DESCRIPTIONS,
} from '../../src/commandCatalog/commandCatalogMessages';
import {
  commandDescription,
  commandTooltip,
  computeCommandsMessage,
  groupByDomain,
  renderCommandTemplate,
  stepCommands,
  type Translate,
} from '../../src/commandCatalog/commandViewModel';

const here = path.dirname(fileURLToPath(import.meta.url));
const parsed = parseCommandGraph(
  readFileSync(path.join(here, 'fixtures/command-transitions.snapshot.json'), 'utf8'),
);
assert.equal(parsed.kind, 'ready');
if (parsed.kind !== 'ready') throw new Error('unreachable');
const catalog = parsed.catalog;

const identity: Translate = (message, ...args) =>
  args.reduce<string>((text, arg, index) => text.replace(`{${index}}`, String(arg)), message);

const EXPECTED_TEMPLATES: Record<string, string> = {
  'PROJECT INIT': 'PROJECT INIT',
  'PROJECT STATUS': 'PROJECT STATUS',
  'PROJECT RECONCILE': 'PROJECT RECONCILE',
  'PROJECT QUICK FIX:': 'PROJECT QUICK FIX: <…>',
  'STEP ADD:': 'STEP ADD: <…>',
  'STEP LIST': 'STEP LIST',
  'STEP SHOW STEP-NNN': 'STEP SHOW STEP-NNN',
  'STEP NEXT': 'STEP NEXT',
  'STEP PLAN STEP-NNN': 'STEP PLAN STEP-NNN',
  'STEP IMPLEMENT STEP-NNN': 'STEP IMPLEMENT STEP-NNN',
  'STEP REVIEW STEP-NNN': 'STEP REVIEW STEP-NNN',
  'STEP FIX STEP-NNN': 'STEP FIX STEP-NNN',
  'STEP RUN STEP-NNN': 'STEP RUN STEP-NNN',
  'STEP AUDIT STEP-NNN': 'STEP AUDIT STEP-NNN',
  'SKILL FIND:': 'SKILL FIND: <…>',
  'SKILL INSTALL:': 'SKILL INSTALL: <…>',
  'SKILL CREATE:': 'SKILL CREATE: <…>',
  'GITHUB GENERATE TEMPLATES': 'GITHUB GENERATE TEMPLATES',
  'RELEASE CHECK': 'RELEASE CHECK',
  'HARNESS HELP': 'HARNESS HELP',
  'HARNESS UPDATE CHECK': 'HARNESS UPDATE CHECK',
  'HARNESS UPDATE APPLY': 'HARNESS UPDATE APPLY',
  'HARNESS STATUS': 'HARNESS STATUS',
  'HARNESS RESUME': 'HARNESS RESUME',
  'HARNESS DOCTOR': 'HARNESS DOCTOR',
  'HARNESS CONFIG': 'HARNESS CONFIG',
  'GIT CHECK': 'GIT CHECK',
  'GIT COMMIT': 'GIT COMMIT',
  'GIT PUSH': 'GIT PUSH',
  'GIT PR': 'GIT PR',
  'GIT PR FINISH': 'GIT PR FINISH',
  'GIT SYNC': 'GIT SYNC',
};

test('template всех 32 команд совпадает с зафиксированной формой', () => {
  assert.equal(catalog.commands.length, 32);
  for (const command of catalog.commands)
    assert.equal(
      renderCommandTemplate(command),
      EXPECTED_TEMPLATES[command.canonical],
      command.canonical,
    );
});

test('stepId подставляется только для target step и без двойного STEP-NNN', () => {
  for (const command of catalog.commands) {
    const text = renderCommandTemplate(command, { stepId: 'STEP-005' });
    if (command.target === 'step') {
      assert.ok(text.endsWith('STEP-005'), command.canonical);
      assert.ok(!text.includes('STEP-NNN'), command.canonical);
      assert.equal(text.split('STEP-').length, 2, command.canonical);
    } else assert.equal(text, EXPECTED_TEMPLATES[command.canonical], command.canonical);
  }
  const plan = catalog.commands.find((command) => command.canonical === 'STEP PLAN STEP-NNN');
  assert.ok(plan);
  assert.equal(renderCommandTemplate(plan, { stepId: 'STEP-005' }), 'STEP PLAN STEP-005');
});

test('ID дописывается в конец, если у будущей step-команды нет токена STEP-NNN', () => {
  assert.equal(
    renderCommandTemplate({ canonical: 'STEP FUTURE', target: 'step' }, { stepId: 'STEP-007' }),
    'STEP FUTURE STEP-007',
  );
});

test('stepCommands возвращает только команды с target step', () => {
  assert.equal(stepCommands(catalog).length, 7);
});

test('группировка по domain сохраняет порядок графа', () => {
  assert.deepEqual(
    groupByDomain(catalog).map((group) => group.domain),
    ['PROJECT', 'STEP', 'SKILL', 'GITHUB', 'RELEASE', 'HARNESS', 'GIT'],
  );
});

test('каждая команда снимка имеет presentation-описание, и ключей нет лишних', () => {
  const canonicals = new Set(catalog.commands.map((command) => command.canonical));
  for (const canonical of canonicals) assert.ok(canonical in COMMAND_DESCRIPTIONS, canonical);
  for (const canonical of Object.keys(COMMAND_DESCRIPTIONS))
    assert.ok(canonicals.has(canonical), canonical);
});

test('неизвестная будущая команда получает fallback на summary графа', () => {
  const future: CatalogCommand = {
    canonical: 'STEP FUTURE STEP-NNN',
    domain: 'STEP',
    operation: 'FUTURE',
    target: 'step',
    input: 'none',
    chainAllowed: false,
    summary: 'Summary from graph.',
    documentation: '',
    dispatchKind: 'semantic',
    outgoing: [],
    incoming: [],
  };
  const translated: Translate = () => 'должно-не-использоваться';
  assert.equal(commandDescription(future, translated), 'Summary from graph.');
  const known = catalog.commands.find((command) => command.canonical === 'STEP LIST');
  assert.ok(known);
  assert.equal(commandDescription(known, translated), 'должно-не-использоваться');
});

test('tooltip строится из graph metadata и является plain text', () => {
  const plan = catalog.commands.find((command) => command.canonical === 'STEP PLAN STEP-NNN');
  assert.ok(plan);
  const tooltip = commandTooltip(plan, identity);
  assert.match(tooltip, /Domain: STEP/);
  assert.match(tooltip, /Target: step/);
  assert.match(tooltip, /Input: none/);
  assert.match(tooltip, /Chain: allowed, next: STEP IMPLEMENT/);
  assert.match(tooltip, /Dispatch: semantic/);
  assert.match(tooltip, /Documentation: \.harness\/docs\/COMMANDS\.md#command-step-plan/);
  const list = catalog.commands.find((command) => command.canonical === 'STEP LIST');
  assert.ok(list);
  assert.match(commandTooltip(list, identity), /Chain: not allowed/);
});

test('состояния сообщения Commands View', () => {
  const none = 'No Harness project was detected in this workspace.';
  assert.equal(computeCommandsMessage([], identity, none), none);
  assert.equal(computeCommandsMessage([{ kind: 'ready', commandCount: 3 }], identity, none), '');
  assert.equal(
    computeCommandsMessage([{ kind: 'ready', commandCount: 0 }], identity, none),
    COMMAND_CATALOG_MESSAGES.viewNoCommands,
  );
  assert.equal(
    computeCommandsMessage([{ kind: 'readError', commandCount: 0 }], identity, none),
    COMMAND_CATALOG_MESSAGES.viewGraphUnavailable,
  );
  assert.equal(
    computeCommandsMessage([{ kind: 'unsupportedSchema', commandCount: 0 }], identity, none),
    COMMAND_CATALOG_MESSAGES.viewGraphUnsupported,
  );
  assert.equal(
    computeCommandsMessage(
      [
        { kind: 'unsupportedSchema', commandCount: 0 },
        { kind: 'ready', commandCount: 2 },
      ],
      identity,
      none,
    ),
    '',
  );
});
