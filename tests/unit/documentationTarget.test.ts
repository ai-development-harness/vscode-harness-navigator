import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import {
  findAnchorLine,
  parseDocumentationRef,
  resolveDocumentationPath,
} from '../../src/commandCatalog/documentationTarget';

function fixture(): { root: string; outside: string; cleanup: () => void } {
  const base = mkdtempSync(path.join(tmpdir(), 'doc-target-'));
  const root = path.join(base, 'root');
  const outside = path.join(base, 'outside.md');
  mkdirSync(path.join(root, 'docs'), { recursive: true });
  writeFileSync(path.join(root, 'docs', 'C.md'), '# C\n');
  writeFileSync(outside, '# out\n');
  return { root, outside, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

test('parseDocumentationRef: пустое, без якоря, с якорем', () => {
  assert.deepEqual(parseDocumentationRef(''), { kind: 'empty' });
  assert.deepEqual(parseDocumentationRef('   '), { kind: 'empty' });
  assert.deepEqual(parseDocumentationRef('#a'), { kind: 'empty' });
  assert.deepEqual(parseDocumentationRef('docs/C.md'), {
    kind: 'ref',
    relativePath: 'docs/C.md',
    anchor: '',
  });
  assert.deepEqual(parseDocumentationRef(' docs/C.md#a#b '), {
    kind: 'ref',
    relativePath: 'docs/C.md',
    anchor: 'a#b',
  });
});

test('resolveDocumentationPath: ok, missing, directory', () => {
  const f = fixture();
  try {
    const ok = resolveDocumentationPath(f.root, 'docs/C.md#x');
    assert.equal(ok.kind, 'ok');
    if (ok.kind === 'ok') assert.equal(ok.anchor, 'x');
    assert.equal(resolveDocumentationPath(f.root, 'docs/none.md').kind, 'missing');
    assert.equal(resolveDocumentationPath(f.root, 'docs').kind, 'missing');
    assert.equal(resolveDocumentationPath(f.root, '').kind, 'empty');
  } finally {
    f.cleanup();
  }
});

test('resolveDocumentationPath: traversal и абсолютный путь отклоняются', () => {
  const f = fixture();
  try {
    for (const value of ['../outside.md#x', 'docs/../../outside.md', f.outside, '/etc/passwd']) {
      assert.equal(resolveDocumentationPath(f.root, value).kind, 'unsafe', value);
    }
  } finally {
    f.cleanup();
  }
});

test('resolveDocumentationPath: symlink наружу и dangling symlink', (t) => {
  const f = fixture();
  try {
    try {
      symlinkSync(f.outside, path.join(f.root, 'docs', 'link.md'));
      symlinkSync(path.join(f.root, 'nowhere.md'), path.join(f.root, 'docs', 'dangling.md'));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EPERM') return t.skip('symlink EPERM');
      throw error;
    }
    assert.equal(resolveDocumentationPath(f.root, 'docs/link.md').kind, 'unsafe');
    assert.equal(resolveDocumentationPath(f.root, 'docs/dangling.md').kind, 'unsafe');
  } finally {
    f.cleanup();
  }
});

test('findAnchorLine: HTML-якорь, заголовок по slug, отсутствующий и пустой', () => {
  const text = [
    '# T',
    '',
    '<a id="command-git-check"></a>',
    '## `GIT CHECK`',
    'x',
    '## Some Heading!',
  ].join('\n');
  assert.equal(findAnchorLine(text, 'command-git-check'), 3);
  assert.equal(findAnchorLine('<a id="solo"></a>\ntext', 'solo'), 0);
  assert.equal(findAnchorLine(text, 'some-heading'), 5);
  assert.equal(findAnchorLine(text, 'Command-Git-Check'), undefined);
  assert.equal(findAnchorLine(text, 'nope'), undefined);
  assert.equal(findAnchorLine(text, ''), undefined);
});
