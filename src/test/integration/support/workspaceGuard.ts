import * as assert from 'node:assert/strict';
import * as path from 'node:path';
import * as vscode from 'vscode';

/**
 * Guard изоляции: integration suites обязаны работать только с копией
 * fixtures в `out/test-workspace`, а не с tracked `src/test/fixtures`.
 * Регрессия конфигурации `.vscode-test.mjs` сразу проваливает suite.
 */
export function assertIsolatedWorkspace(): void {
  const folders = vscode.workspace.workspaceFolders ?? [];
  assert.ok(folders.length > 0, 'test workspace has no folders');
  const marker = `${path.sep}out${path.sep}test-workspace${path.sep}`;
  const fixtures = `${path.sep}src${path.sep}test${path.sep}fixtures${path.sep}`;
  for (const folder of folders) {
    const fsPath = folder.uri.fsPath + path.sep;
    assert.ok(
      fsPath.includes(marker) && !fsPath.includes(fixtures),
      `workspace folder ${folder.uri.fsPath} must live inside out/test-workspace, not src/test/fixtures`,
    );
  }
}
