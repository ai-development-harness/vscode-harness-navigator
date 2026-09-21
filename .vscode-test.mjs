import { defineConfig } from '@vscode/test-cli';

export default defineConfig([
  {
    label: 'integration-en',
    files: 'out/test/integration/**/*.test.js',
    launchArgs: ['--locale', 'en'],
    mocha: {
      timeout: 30000,
    },
  },
  {
    label: 'integration-ru',
    files: 'out/test/integration/**/*.test.js',
    launchArgs: ['--locale', 'ru'],
    mocha: {
      timeout: 30000,
    },
  },
]);
