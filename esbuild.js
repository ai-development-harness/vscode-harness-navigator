// Production/dev bundler для entrypoint расширения.
//
// Использование:
//   node esbuild.js             -> dev bundle: sourcemap, без minify
//   node esbuild.js --production -> production bundle: minified, без sourcemap
//
// Bundle ориентирован на VS Code Extension Host (CommonJS, Node runtime) и
// исключает модуль `vscode`, который host подставляет в runtime.

const esbuild = require('esbuild');

const production = process.argv.includes('--production');

async function build() {
  const context = await esbuild.context({
    entryPoints: ['src/extension.ts'],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    target: 'node20',
    outfile: 'dist/extension.js',
    external: ['vscode'],
    minify: production,
    sourcemap: !production,
    sourcesContent: !production,
    logLevel: 'info',
  });

  await context.rebuild();
  await context.dispose();
}

build().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
