import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isBundleOriginated,
  normalizeFrameFile,
  stackFiles,
} from '../../src/test/integration/support/stackAttribution';

const devBundle = '/work/repo/dist/extension.js';
const packagedBundle = '/work/repo/out/packaged/extension/dist/extension.js';

const stack = (...frames: string[]) =>
  ['Error', ...frames.map((frame) => `    at ${frame}`)].join('\n');

test('кадр bundle в dev-пути (вид "fn (file:line:col)") даёт true', () => {
  assert.equal(
    isBundleOriginated(
      stack(
        'wrapper (/work/repo/out/test/integration/support/boundarySpies.js:10:5)',
        'refreshRoot (/work/repo/dist/extension.js:120:9)',
      ),
      devBundle,
      'linux',
    ),
    true,
  );
});

test('кадр bundle в packaged-пути и минифицированный column даёт true', () => {
  assert.equal(
    isBundleOriginated(
      stack('/work/repo/out/packaged/extension/dist/extension.js:1:734512'),
      packagedBundle,
      'linux',
    ),
    true,
  );
  assert.equal(
    isBundleOriginated(
      stack('async Object.a (file:///work/repo/out/packaged/extension/dist/extension.js:1:9)'),
      packagedBundle,
      'linux',
    ),
    true,
  );
});

test('Windows: drive letter, backslash и регистр нормализуются', () => {
  assert.equal(
    isBundleOriginated(
      stack('fn (file:///C:/Work/Repo/dist/extension.js:5:1)'),
      'c:\\work\\repo\\dist\\extension.js',
      'win32',
    ),
    true,
  );
  assert.equal(
    isBundleOriginated(
      stack('fn (C:\\Work\\Repo\\dist\\Extension.JS:5:1)'),
      'c:\\work\\repo\\dist\\extension.js',
      'win32',
    ),
    true,
  );
});

test('не-bundle кадры дают false: тесты, .vscode-test, mocha, __packaged_tests__, map, jsx, соседний extension', () => {
  const others = [
    '/work/repo/out/test/integration/mvp/boundary.test.js:1:1',
    '/work/repo/.vscode-test/vscode-linux/resources/app/out/vs/workbench/api/node/extensionHostProcess.js:1:1',
    '/work/repo/node_modules/mocha/lib/runner.js:100:5',
    '/work/repo/out/packaged/extension/__packaged_tests__/integration/mvp/boundary.test.js:1:1',
    '/work/repo/dist/extension.js.map:1:1',
    '/work/repo/dist/extension.jsx:1:1',
    '/work/repo/dist/extension.js/other.js:1:1',
    '/work/repo-other/dist/extension.js:1:1',
    '/work/repo/dist/extension.js2:1:1',
  ];
  for (const frame of others)
    assert.equal(isBundleOriginated(stack(`fn (${frame})`), devBundle, 'linux'), false, frame);
});

test('stack без кадров и пустая строка дают false', () => {
  assert.equal(isBundleOriginated('Error: nothing', devBundle, 'linux'), false);
  assert.equal(isBundleOriginated('', devBundle, 'linux'), false);
});

test('разбор форм кадров и снятие :line:col', () => {
  assert.deepEqual(
    stackFiles(stack('fn (/a/b.js:1:2)', '/c/d.js:3:4', 'async fn2 (file:///e/f.js:5:6)')),
    ['/a/b.js', '/c/d.js', 'file:///e/f.js'],
  );
  assert.equal(normalizeFrameFile('/a/../b/x.js', 'linux'), '/b/x.js');
});
