// @ts-check
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import eslintConfigPrettier from 'eslint-config-prettier';
import globals from 'globals';

export default tseslint.config(
  {
    ignores: ['dist/**', 'out/**', 'node_modules/**', '*.vsix', '.yarn/**'],
  },
  {
    // Type-aware linting исходного кода расширения из tsconfig.json.
    files: ['src/**/*.ts'],
    ignores: ['src/test/**/*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/no-non-null-assertion': 'error',
    },
  },
  {
    // Type-aware linting integration и unit tests из отдельного
    // tsconfig.eslint.json. Plain project service не обнаруживает его рядом с
    // tsconfig.json/tsconfig.test.json, которые намеренно не включают все test globs.
    files: ['src/test/**/*.ts', 'tests/**/*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.eslint.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/no-non-null-assertion': 'error',
      // `test()`/`suite()` из node:test и `test()` из Mocha возвращают promises,
      // которые ожидает сам runner; правило добавило бы шумные `void` prefixes
      // во всём test suite без дополнительной проверки поведения.
      '@typescript-eslint/no-floating-promises': 'off',
    },
  },
  {
    // Release/test tooling scripts (TypeScript, запускаются через tsx).
    files: ['scripts/**/*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.scripts.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-non-null-assertion': 'error',
    },
  },
  {
    // Для plain Node/CommonJS tooling scripts type-aware linting не нужен.
    files: ['esbuild.js'],
    extends: [js.configs.recommended],
    languageOptions: {
      sourceType: 'commonjs',
      globals: globals.node,
    },
  },
  {
    // Для plain ESM Node config files type-aware linting не нужен.
    files: ['eslint.config.mjs', '.vscode-test.mjs'],
    extends: [js.configs.recommended],
    languageOptions: {
      sourceType: 'module',
      globals: globals.node,
    },
  },
  eslintConfigPrettier,
);
