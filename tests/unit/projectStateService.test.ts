import assert from 'node:assert/strict';
import { test } from 'node:test';
import type * as vscode from 'vscode';
import { ProjectGraphService } from '../../src/projectGraph/projectStateService';
import type { ProjectStateProcessResult } from '../../src/projectGraph/projectStateProcess';
import { projectStateFixture } from './fixtures/projectState';

const folder = (name: string) =>
  ({
    name,
    index: 0,
    uri: { fsPath: '/tmp/' + name, toString: () => name },
  }) as vscode.WorkspaceFolder;
const ok = (): ProjectStateProcessResult => ({
  kind: 'success',
  stdout: JSON.stringify(projectStateFixture()),
});
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test('untrusted workspace никогда не вызывает process; trust grant позволяет refresh', async () => {
  let trusted = false,
    calls = 0;
  const service = new ProjectGraphService({
    isTrusted: () => trusted,
    process: {
      run: () => {
        calls++;
        return Promise.resolve(ok());
      },
    },
  });
  assert.equal((await service.refresh(folder('a'))).kind, 'untrusted');
  assert.equal(calls, 0);
  trusted = true;
  assert.equal((await service.refresh(folder('a'))).kind, 'ready');
  assert.equal(calls, 1);
  service.dispose();
});

test('same-root refresh сериализован; stale payload не заменяет новый cache', async () => {
  let active = 0,
    maximum = 0,
    calls = 0;
  const service = new ProjectGraphService({
    isTrusted: () => true,
    process: {
      run: async (_root, signal) => {
        calls++;
        active++;
        maximum = Math.max(maximum, active);
        await delay(15);
        active--;
        return signal?.aborted ? { kind: 'error', reason: 'cancelled', detail: '' } : ok();
      },
    },
  });
  const root = folder('a');
  const first = service.refresh(root),
    second = service.refresh(root);
  await Promise.all([first, second]);
  assert.equal(maximum, 1);
  assert.equal(calls, 2);
  assert.equal(service.get(root)?.kind, 'ready');
  service.dispose();
});

test('debounce, multi-root events и remove/dispose изолированы', async () => {
  const calls: string[] = [],
    events: string[] = [];
  const service = new ProjectGraphService({
    isTrusted: () => true,
    debounceMs: 5,
    process: {
      run: (root) => {
        calls.push(root);
        return Promise.resolve(ok());
      },
    },
  });
  service.onDidChange((f) => events.push(f.name));
  const a = folder('a'),
    b = folder('b');
  await service.refresh(a);
  await service.refresh(b);
  service.invalidate(a);
  service.invalidate(a);
  service.invalidate(a);
  await delay(30);
  assert.deepEqual(calls, ['/tmp/a', '/tmp/b', '/tmp/a']);
  assert.deepEqual(events, ['a', 'b', 'a']);
  service.removeRoot(a);
  assert.equal(service.get(a), undefined);
  assert.equal(service.get(b)?.kind, 'ready');
  service.invalidate(b);
  service.dispose();
  await delay(20);
  assert.equal(calls.length, 3);
});

test('malformed, BLOCKED и future schema не превращаются в fallback', async () => {
  for (const stdout of [
    'not json',
    JSON.stringify({ ...projectStateFixture(), status: 'BLOCKED' }),
    JSON.stringify({ ...projectStateFixture(), schemaVersion: 2 }),
  ]) {
    const service = new ProjectGraphService({
      isTrusted: () => true,
      process: { run: () => Promise.resolve({ kind: 'success', stdout }) },
    });
    assert.equal((await service.refresh(folder('a'))).kind, 'error');
    assert.equal(service.get(folder('a'))?.payload, undefined);
    service.dispose();
  }
});

test('unsupported root сбрасывает cached graph и отменяет pending process', async () => {
  const service = new ProjectGraphService({
    isTrusted: () => true,
    process: {
      run: async (_root, signal) => {
        await delay(10);
        return signal?.aborted ? { kind: 'error', reason: 'cancelled', detail: '' } : ok();
      },
    },
  });
  const root = folder('a');
  await service.refresh(root);
  const pending = service.refresh(root);
  service.blockRoot(root, 'unsupportedHarness');
  await pending;
  assert.equal(service.get(root)?.error, 'unsupportedHarness');
  assert.equal(service.get(root)?.payload, undefined);
  service.dispose();
});

test('refresh и debounce не запускают API для ставшего неподдерживаемым root', async () => {
  let configurationError: string | undefined;
  let calls = 0;
  const root = folder('eligibility');
  const service = new ProjectGraphService({
    isTrusted: () => true,
    configurationError: () => configurationError,
    debounceMs: 5,
    process: {
      run: () => {
        calls++;
        return Promise.resolve(ok());
      },
    },
  });
  try {
    await service.refresh(root);
    for (const error of ['unsupportedHarness', 'unavailable']) {
      configurationError = error;
      service.blockRoot(root, error);
      assert.equal((await service.refresh(root)).error, error);
      service.invalidate(root);
      await delay(30);
      assert.equal(service.get(root)?.error, error);
      assert.equal(calls, 1, 'явный и отложенный refresh сохраняют blocker без process');
    }
    configurationError = undefined;
    assert.equal((await service.refresh(root)).kind, 'ready');
    assert.equal(calls, 2, 'исправленный manifest восстанавливает API');
  } finally {
    service.dispose();
  }
});
