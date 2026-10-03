import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { spawn, type SpawnOptionsWithoutStdio } from 'node:child_process';
import { ProjectGraphService } from '../../src/projectGraph/projectStateService';
import type * as vscode from 'vscode';
import {
  ProjectStateProcess,
  projectStateArguments,
} from '../../src/projectGraph/projectStateProcess';

/** Реальный Python в isolated temp root, а не mock-only доказательство lifecycle. */
function fixture(t: { after(fn: () => void): void }, script: string) {
  const root = mkdtempSync(path.join(tmpdir(), 'navigator-process-'));
  mkdirSync(path.join(root, '.harness/tools'), { recursive: true });
  writeFileSync(path.join(root, '.harness/tools/project-state.py'), script);
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

test('fixed shell-free invocation использует canonical cwd и не пишет pycache', async (t) => {
  const root = fixture(t, 'import sys\nprint("Привет", end="")\n');
  let invocation: unknown;
  const process = new ProjectStateProcess({
    spawn: ((command: string, args: readonly string[], options: SpawnOptionsWithoutStdio) => {
      invocation = { command, args, options };
      return spawn(command, args, options);
    }) as unknown as typeof spawn,
  });
  assert.deepEqual(projectStateArguments(root), {
    command: 'python3',
    args: ['.harness/tools/project-state.py', '--json'],
    cwd: root,
  });
  assert.deepEqual(await process.run(root), { kind: 'success', stdout: 'Привет' });
  const recorded = invocation as {
    options: { shell: boolean; cwd: string; env: { PYTHONDONTWRITEBYTECODE: string } };
  };
  assert.equal(recorded.options.shell, false);
  assert.equal(recorded.options.cwd, root);
  assert.equal(recorded.options.env.PYTHONDONTWRITEBYTECODE, '1');
});

test('missing Python/tool, nonzero exit и outside tool symlink', async (t) => {
  const root = fixture(t, 'import sys\nsys.stderr.write("failure")\nsys.exit(7)\n');
  const result = await new ProjectStateProcess().run(root);
  assert.equal(result.kind === 'error' && result.reason, 'processError');
  const missing = await new ProjectStateProcess({ executable: path.join(root, 'no-python') }).run(
    root,
  );
  assert.equal(missing.kind === 'error' && missing.reason, 'missingPython');
  const tool = path.join(root, '.harness/tools/project-state.py');
  rmSync(tool);
  assert.equal((await new ProjectStateProcess().run(root)).kind, 'error');
  if (process.platform !== 'win32') {
    symlinkSync(process.execPath, tool);
    const escaped = await new ProjectStateProcess().run(root);
    assert.equal(escaped.kind === 'error' && escaped.reason, 'missingTool');
  }
});

test('BLOCKED JSON с exit 1 сохраняет API status вместо общей process error', async (t) => {
  const root = fixture(
    t,
    'import sys\nprint(\'{"schemaVersion":1,"status":"BLOCKED","error":"bad artifact"}\')\nsys.exit(1)\n',
  );
  const service = new ProjectGraphService({
    isTrusted: () => true,
    process: new ProjectStateProcess(),
  });
  const folder = {
    name: 'blocked',
    index: 0,
    uri: { fsPath: root, toString: () => root },
  } as vscode.WorkspaceFolder;
  const snapshot = await service.refresh(folder);
  assert.equal(snapshot.error, 'blocked');
  assert.equal(snapshot.payload, undefined);
  service.dispose();
});

test('stdout/stderr byte limits завершают настоящий child', async (t) => {
  for (const channel of ['stdout', 'stderr']) {
    const root = fixture(
      t,
      `import sys\nsys.${channel}.write("x" * 10000)\nsys.${channel}.flush()\n`,
    );
    const result = await new ProjectStateProcess({ outputLimitBytes: 100 }).run(root);
    assert.equal(result.kind === 'error' && result.reason, 'oversizedOutput');
  }
});

test('timeout и cancellation ждут close, включая игнорирование SIGTERM', async (t) => {
  const root = fixture(
    t,
    'import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n',
  );
  const timeout = await new ProjectStateProcess({ timeoutMs: 100, killGraceMs: 30 }).run(root);
  assert.equal(timeout.kind === 'error' && timeout.reason, 'timeout');
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), 100);
  const cancelled = await new ProjectStateProcess({ killGraceMs: 30 }).run(root, abort.signal);
  clearTimeout(timer);
  assert.equal(cancelled.kind === 'error' && cancelled.reason, 'cancelled');
  assert.equal((await new ProjectStateProcess().run(root, abort.signal)).kind, 'error');
});
