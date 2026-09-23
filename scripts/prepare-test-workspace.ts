// Готовит изолированную копию test fixtures в out/test-workspace, чтобы
// Extension Host integration tests никогда не изменяли tracked
// src/test/fixtures/**. Запуск: node --import tsx scripts/prepare-test-workspace.ts
// Только node:fs и node:path; записи вне out/test-workspace запрещены.

import * as fs from 'node:fs';
import * as path from 'node:path';

const repoRoot = path.resolve(__dirname, '..');
const sourceRoot = path.join(repoRoot, 'src', 'test', 'fixtures');
const targetRoot = path.join(repoRoot, 'out', 'test-workspace');

/** Отказывает в любой записи вне out/test-workspace (проверка resolved target до записи). */
function guarded(target: string): string {
  const resolved = path.resolve(target);
  if (resolved !== targetRoot && !resolved.startsWith(targetRoot + path.sep))
    throw new Error(`Refusing to write outside ${targetRoot}: ${resolved}`);
  return resolved;
}

/** Возвращает права каталогам, которые сам скрипт ранее сделал недоступными, иначе rm их не удалит. */
function restorePermissions(directory: string): void {
  if (process.platform === 'win32' || !fs.existsSync(directory)) return;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isSymbolicLink() || !entry.isDirectory()) continue;
    try {
      fs.chmodSync(full, 0o755);
    } catch {
      continue;
    }
    restorePermissions(full);
  }
}

const skipped: Record<string, string> = {};

function tryCreate(name: string, action: () => void): void {
  try {
    action();
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code ?? 'unknown';
    if (code === 'EPERM' || code === 'EACCES' || code === 'ENOSYS' || code === 'ENOTSUP')
      skipped[name] = `OS refused to create the fixture (${code}).`;
    else throw error;
  }
}

function symlink(target: string, linkPath: string): void {
  const resolvedTarget = path.resolve(path.dirname(linkPath), target);
  if (process.platform !== 'win32') {
    fs.symlinkSync(target, guarded(linkPath));
    return;
  }
  // win32: 'junction' допустим только для каталогов (и требует абсолютный target);
  // файловые цели создаются как настоящий file-symlink.
  const isDirectory = fs.existsSync(resolvedTarget) && fs.statSync(resolvedTarget).isDirectory();
  if (isDirectory) fs.symlinkSync(resolvedTarget, guarded(linkPath), 'junction');
  else fs.symlinkSync(target, guarded(linkPath), 'file');
}

function main(): void {
  guarded(targetRoot);
  restorePermissions(path.join(targetRoot, 'mvp', 'mvp-unreadable'));
  fs.rmSync(targetRoot, { recursive: true, force: true });
  fs.mkdirSync(targetRoot, { recursive: true });
  fs.cpSync(sourceRoot, targetRoot, { recursive: true, verbatimSymlinks: true });

  const mvp = path.join(targetRoot, 'mvp');

  // node_modules/ игнорируется Git, поэтому fixture хранится как _node_modules.
  const stored = path.join(mvp, 'mvp-valid', '_node_modules');
  if (fs.existsSync(stored))
    fs.renameSync(guarded(stored), guarded(path.join(mvp, 'mvp-valid', 'node_modules')));

  const external = path.join(mvp, 'mvp-external');

  // Static symlink-файл внутри valid root: root остаётся valid, файл не индексируется.
  tryCreate('mvp-valid-symlink-file', () =>
    symlink(
      path.join('..', '..', '..', 'mvp-external', 'planning', 'tasks', 'STEP-991.md'),
      path.join(mvp, 'mvp-valid', 'planning', 'tasks', 'STEP-991.md'),
    ),
  );

  // Configured каталог — symlink за пределы root.
  tryCreate('mvp-symlink', () => {
    fs.mkdirSync(guarded(path.join(mvp, 'mvp-symlink', 'planning')), { recursive: true });
    symlink(
      path.join('..', '..', 'mvp-external', 'planning', 'tasks'),
      path.join(mvp, 'mvp-symlink', 'planning', 'tasks'),
    );
  });

  // Manifest — symlink на внешний валидный manifest.
  tryCreate('mvp-manifest-symlink', () => {
    fs.rmSync(guarded(path.join(mvp, 'mvp-manifest-symlink', '.harness', '.gitkeep')), {
      force: true,
    });
    symlink(
      path.join('..', '..', 'mvp-external', 'valid-manifest.yaml'),
      path.join(mvp, 'mvp-manifest-symlink', '.harness', 'manifest.yaml'),
    );
  });

  // Абсолютный configured path зависит от platform, поэтому в Git не хранится.
  const absoluteTasks = path.resolve(external, 'planning', 'tasks');
  const absoluteManifest = [
    'harness:',
    '  version: "1"',
    '  release: "0.6.0"',
    'protocol:',
    `  taskDirectory: ${JSON.stringify(absoluteTasks)}`,
    'sources:',
    '  projectOverview: docs/PROJECT.md',
    '  requirements: docs/requirements',
    '  adrDirectory: docs/adr',
    '  architecture: docs/architecture.md',
    '  openQuestions: docs/open-questions',
    '  openQuestionsIndex: docs/OPEN_QUESTIONS.md',
    '  roadmap: planning/PLAN.md',
    '  status: planning/STATUS.md',
    '',
  ].join('\n');
  const absoluteHarness = path.join(mvp, 'mvp-absolute', '.harness');
  fs.mkdirSync(guarded(absoluteHarness), { recursive: true });
  fs.writeFileSync(guarded(path.join(absoluteHarness, 'manifest.yaml')), absoluteManifest);

  // Каталог .harness без права поиска: UnexpectedInternalError (POSIX, не root).
  const unreadable = path.join(mvp, 'mvp-unreadable');
  fs.mkdirSync(guarded(unreadable), { recursive: true });
  const isRoot = typeof process.getuid === 'function' && process.getuid() === 0;
  if (process.platform === 'win32' || isRoot) {
    skipped['mvp-unreadable'] = 'chmod-based unreadable fixture is unavailable (Windows or root).';
  } else {
    tryCreate('mvp-unreadable', () => {
      const harness = path.join(unreadable, '.harness');
      fs.mkdirSync(guarded(harness), { recursive: true });
      fs.chmodSync(guarded(harness), 0o000);
    });
  }

  fs.writeFileSync(
    guarded(path.join(mvp, 'skipped-fixtures.json')),
    `${JSON.stringify(skipped, null, 2)}\n`,
  );
  process.stdout.write(
    `test workspace prepared at ${targetRoot} (platform ${process.platform}, skipped: ${Object.keys(skipped).join(', ') || 'none'})\n`,
  );
}

main();
