import { defineConfig } from '@vscode/test-cli';

// Все workspaceFolder указывают на копию fixtures в out/test-workspace
// (`scripts/prepare-test-workspace.ts`), а не на tracked src/test/fixtures.
const mocha = { timeout: 60000 };
const locales = ['en', 'ru'];

const integration = locales.map((locale) => ({
  label: `integration-${locale}`,
  files: 'out/test/integration/*.test.js',
  workspaceFolder: 'out/test-workspace/multi-root.code-workspace',
  launchArgs: ['--locale', locale],
  mocha,
}));

const mvp = locales.map((locale) => ({
  label: `mvp-${locale}`,
  files: 'out/test/integration/mvp/**/*.test.js',
  workspaceFolder: 'out/test-workspace/mvp/mvp.code-workspace',
  launchArgs: ['--locale', locale],
  mocha,
}));

// Packaged-профили запускают скомпилированные suites из самого распакованного
// расширения: Extension Host выдаёт отдельный instance vscode API на
// расширение, поэтому патчи тестов должны быть видны bundle.
const packaged = locales.map((locale) => ({
  label: `packaged-${locale}`,
  extensionDevelopmentPath: 'out/packaged/extension',
  files: 'out/packaged/extension/__packaged_tests__/integration/mvp/**/*.test.js',
  workspaceFolder: 'out/test-workspace/mvp/mvp.code-workspace',
  launchArgs: ['--locale', locale, '--disable-extensions'],
  mocha,
}));

export default defineConfig([...integration, ...mvp, ...packaged]);
