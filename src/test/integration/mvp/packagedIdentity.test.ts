import * as assert from 'node:assert/strict';
import * as crypto from 'node:crypto';
import * as path from 'node:path';
import { originalFs } from '../support/originalApis';
import { extensionPath } from '../support/helpers';

// Профиль определяется по extensionPath (а не по расположению suites): в packaged-профиле
// extensionDevelopmentPath = out/packaged/extension, поэтому запуск suites из dev-пути
// здесь обязан провалиться, а не молча пропуститься.
// Только для packaged-профилей: suites запускаются из
// `<extensionPath>/__packaged_tests__`, поэтому получают тот же instance
// vscode API, что и bundle, а bundle — это production-minified dist из VSIX.
const inPackagedDir = __dirname.split(path.sep).includes('__packaged_tests__');

suite('packaged extension identity (Extension Host)', () => {
  test('extensionPath, расположение suites и SHA-256 bundle соответствуют извлечённому VSIX', function () {
    const root = extensionPath();
    const packaged = root.split(path.sep).join('/').endsWith('out/packaged/extension');
    if (!packaged) {
      console.log('[skip] dev profile: packaged identity is asserted only in packaged-* profiles');
      this.skip();
    }
    assert.ok(inPackagedDir, 'packaged profile must run suites from __packaged_tests__');
    assert.ok(
      root.split(path.sep).join('/').endsWith('out/packaged/extension'),
      `extensionPath must be out/packaged/extension, got ${root}`,
    );
    assert.ok(
      __filename.startsWith(root + path.sep),
      'suite must live inside extensionPath (same vscode API instance as the bundle)',
    );
    const entriesFile = path.join(root, '..', 'extracted-entries.json');
    const entries = JSON.parse(originalFs.readFileSync(entriesFile, 'utf8')) as Record<
      string,
      string
    >;
    const bundle = originalFs.readFileSync(path.join(root, 'dist', 'extension.js'));
    const hash = crypto.createHash('sha256').update(bundle).digest('hex');
    assert.equal(hash, entries['extension/dist/extension.js']);
    assert.ok(
      !bundle.toString('utf8').includes('sourceMappingURL'),
      'production bundle must not carry source maps',
    );
    console.log(`[packaged] bundle sha256=${hash} size=${bundle.length}`);
  });
});
