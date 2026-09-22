import assert from 'node:assert/strict';
import {
  constants,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import {
  detectProject,
  MAXIMUM_MANIFEST_SIZE_BYTES,
  PRODUCTION_DIAGNOSTIC_MESSAGES,
  resolveManifestOpenCapability,
} from '../../src/projectModel/manifestService';

// Windows документирует `O_NOFOLLOW`/`O_NONBLOCK` как неопределённые POSIX-
// константы в `node:fs`, поэтому реальный `win32` profile не имеет ни флагов,
// ни canonical-path re-derivation — этот profile используется в тестах ниже
// как capability без `deriveOpenedPath`, буквально соответствующая Windows.
const WINDOWS_LIKE_CAPABILITY = resolveManifestOpenCapability('win32', {});

// macOS-shaped profile (F-003): POSIX open-флаги реально доступны (используем
// настоящие значения `constants.O_NOFOLLOW`/`O_NONBLOCK` этого раннера, как
// и Linux-profile ниже), но canonical-path re-derivation (`/proc/self/fd`)
// недоступна — `/dev/fd` на macOS не symlink на target (ADR-005, F-002 из
// planning-review). Буквально соответствует реальному macOS: флаги есть,
// `deriveOpenedPath` нет.
const DARWIN_LIKE_CAPABILITY = {
  ...resolveManifestOpenCapability('linux', constants),
  deriveOpenedPath: undefined,
};

function temporaryDirectory(): string {
  return mkdtempSync(path.join(tmpdir(), 'harness-navigator-'));
}

function manifest(paths: Record<string, string> = {}): string {
  const sourcePaths = {
    projectOverview: 'docs/PROJECT.md',
    requirements: 'docs/requirements',
    adrDirectory: 'docs/adr',
    architecture: 'docs/architecture.md',
    openQuestions: 'docs/open-questions',
    openQuestionsIndex: 'docs/OPEN_QUESTIONS.md',
    roadmap: 'planning/PLAN.md',
    status: 'planning/STATUS.md',
    ...paths,
  };
  return `harness:\n  version: "1"\n  release: "0.6.0"\nprotocol:\n  taskDirectory: "${paths.taskDirectory ?? 'planning/tasks'}"\nsources:\n${Object.entries(
    sourcePaths,
  )
    .filter(([name]) => name !== 'taskDirectory')
    .map(([name, value]) => `  ${name}: "${value}"`)
    .join('\n')}\n`;
}

function writeManifest(root: string, contents = manifest()): void {
  mkdirSync(path.join(root, '.harness'), { recursive: true });
  writeFileSync(path.join(root, '.harness', 'manifest.yaml'), contents);
}

function withRoot(callback: (root: string) => void): void {
  const root = temporaryDirectory();
  try {
    callback(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('обычная папка определяется без попытки legacy fallback', () => {
  withRoot((root) => {
    const project = detectProject(root);
    assert.equal(project.kind, 'nonHarness');
    assert.equal(project.diagnostic.category, 'NotHarnessProject');
  });
});

test('некорректный manifest возвращает диагностируемое состояние', () => {
  withRoot((root) => {
    writeManifest(root, 'harness: [');
    const project = detectProject(root);
    assert.equal(project.kind, 'invalidManifest');
    assert.equal(project.diagnostic.category, 'InvalidManifest');
  });
});

test('release ниже минимума не становится валидным проектом', () => {
  withRoot((root) => {
    writeManifest(root, manifest().replace('0.6.0', '0.5.9'));
    const project = detectProject(root);
    assert.equal(project.kind, 'unsupportedVersion');
    assert.equal(project.detectedRelease, '0.5.9');
    assert.equal(project.minimumRelease, '0.6.0');
  });
});

test('SemVer граница отличает prerelease, build metadata и поддерживаемые releases', () => {
  withRoot((root) => {
    for (const [release, expectedKind] of [
      ['0.5.9', 'unsupportedVersion'],
      ['0.6.0-beta.1', 'unsupportedVersion'],
      ['0.6.0', 'valid'],
      ['0.6.0+build.42', 'valid'],
      ['0.6.1-beta.1', 'valid'],
    ] as const) {
      writeManifest(root, manifest().replace('0.6.0', release));
      assert.equal(detectProject(root).kind, expectedKind, `release ${release}`);
    }
  });
});

test('некорректный SemVer release является malformed manifest', () => {
  withRoot((root) => {
    for (const release of ['banana', '01.6.0']) {
      writeManifest(root, manifest().replace('0.6.0', release));
      const project = detectProject(root);
      assert.equal(project.kind, 'invalidManifest', `release ${release}`);
      assert.equal(project.diagnostic.category, 'InvalidManifest');
    }
  });
});

test('production diagnostic keys присутствуют в English и Russian bundles', () => {
  // `PRODUCTION_DIAGNOSTIC_MESSAGES` — единственный источник значений этого
  // слоя (см. `DIAGNOSTIC_MESSAGES`/`DiagnosticMessage` в manifestService.ts).
  // Он покрывает и прямые вызовы `diagnostic(...)`, и message, создаваемые
  // динамически через `ManifestInputError` (`manifestNotRegularFile`,
  // `manifestExceedsSize`) — в отличие от прежнего regex-а по исходникам,
  // который видел только литералы прямых вызовов `diagnostic(...)`.
  // Незарегистрированный message literal перестаёт компилироваться
  // (`yarn typecheck`), поэтому этот test ловит удаление ключа из registry
  // так же надёжно, как typecheck ловит добавление нового
  // незарегистрированного literal.
  const englishBundle = JSON.parse(
    readFileSync(new URL('../../l10n/bundle.l10n.json', import.meta.url), 'utf8'),
  ) as Record<string, string>;
  const russianBundle = JSON.parse(
    readFileSync(new URL('../../l10n/bundle.l10n.ru.json', import.meta.url), 'utf8'),
  ) as Record<string, string>;

  assert.ok(PRODUCTION_DIAGNOSTIC_MESSAGES.length > 0);
  for (const key of PRODUCTION_DIAGNOSTIC_MESSAGES) {
    assert.ok(englishBundle[key] !== undefined, `English key: ${key}`);
    assert.ok(russianBundle[key] !== undefined, `Russian key: ${key}`);
  }
});

test('resolveManifestOpenCapability даёт правильный profile для каждой platform', () => {
  const linux = resolveManifestOpenCapability('linux', {
    O_NOFOLLOW: 0o400000,
    O_NONBLOCK: 0o4000,
  });
  assert.equal(linux.noFollowFlag, 0o400000);
  assert.equal(linux.nonBlockFlag, 0o4000);
  assert.equal(typeof linux.deriveOpenedPath, 'function');

  // POSIX системный вызов на macOS поддерживает O_NOFOLLOW/O_NONBLOCK, но
  // canonical-path re-derivation открытого descriptor (`/proc/self/fd`)
  // недоступна — `/dev/fd` на macOS не symlink на target (ADR-005, F-002).
  const darwin = resolveManifestOpenCapability('darwin', {
    O_NOFOLLOW: 0x00000100,
    O_NONBLOCK: 0x00000004,
  });
  assert.equal(darwin.noFollowFlag, 0x00000100);
  assert.equal(darwin.nonBlockFlag, 0x00000004);
  assert.equal(darwin.deriveOpenedPath, undefined);

  // Node документирует O_NOFOLLOW/O_NONBLOCK как неопределённые POSIX-константы
  // на win32 — оба флага и re-derivation отсутствуют.
  const win32 = resolveManifestOpenCapability('win32', {});
  assert.equal(win32.noFollowFlag, undefined);
  assert.equal(win32.nonBlockFlag, undefined);
  assert.equal(win32.deriveOpenedPath, undefined);
});

test('отсутствующий release является malformed manifest, а не unsupported version', () => {
  withRoot((root) => {
    writeManifest(root, manifest().replace('  release: "0.6.0"\n', ''));
    const project = detectProject(root);
    assert.equal(project.kind, 'invalidManifest');
    assert.equal(project.diagnostic.category, 'InvalidManifest');
  });
});

test('неподдерживаемая schema получает отдельную taxonomy category', () => {
  withRoot((root) => {
    writeManifest(root, manifest().replace('version: "1"', 'version: "2"'));
    const project = detectProject(root);
    assert.equal(project.kind, 'unsupportedSchema');
    assert.equal(project.diagnostic.category, 'UnsupportedSchema');
  });
});

test('корректный пустой Harness-проект сохраняет configured paths из manifest', () => {
  withRoot((root) => {
    writeManifest(root);
    const project = detectProject(root);
    assert.equal(project.kind, 'valid');
    assert.equal(project.configuredPaths.taskDirectory, 'planning/tasks');
    assert.equal(project.configuredPaths.requirements, 'docs/requirements');
  });
});

test('корректный проект достигает valid под capability без deriveOpenedPath (ADR-005)', () => {
  // Закрывает F-009 без реального non-Linux раннера: под capability, буквально
  // соответствующей Windows/macOS (нет canonical-path re-derivation), валидный
  // проект больше не должен ложно деградировать в `configurationBlocked`.
  withRoot((root) => {
    writeManifest(root);
    const project = detectProject(root, { capability: WINDOWS_LIKE_CAPABILITY });
    assert.equal(project.kind, 'valid');
    assert.equal(project.configuredPaths.taskDirectory, 'planning/tasks');
  });
});

test('абсолютный configured path блокируется до доступа к target', () => {
  withRoot((root) => {
    writeManifest(root, manifest({ requirements: path.join(tmpdir(), 'outside-target') }));
    const project = detectProject(root);
    assert.equal(project.kind, 'configurationBlocked');
    assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
  });
});

test('traversal configured path блокируется до доступа к target', () => {
  withRoot((root) => {
    writeManifest(root, manifest({ requirements: '../outside-target' }));
    const project = detectProject(root);
    assert.equal(project.kind, 'configurationBlocked');
    assert.match(project.diagnostic.detail, /Traversal/u);
  });
});

test('symlink configured path за пределами root блокируется без чтения внешнего target', () => {
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      writeFileSync(path.join(outside, 'secret.md'), 'secret must not be read');
      symlinkSync(outside, path.join(root, 'linked-requirements'));
      writeManifest(root, manifest({ requirements: 'linked-requirements' }));
      const project = detectProject(root);
      assert.equal(project.kind, 'configurationBlocked');
      assert.match(project.diagnostic.detail, /outside/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('висячий configured-path symlink блокируется и не маскируется отсутствующим ancestor', () => {
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      // Symlink существует для lstat, но его external target отсутствует. До F-012
      // `existsSync` считал его отсутствующим и обходил к contained parent, оставляя
      // unsafe path в valid state до возможного появления external target.
      const danglingTarget = path.join(outside, 'later-created-requirements');
      const linkedRequirements = path.join(root, 'linked-requirements');
      symlinkSync(danglingTarget, linkedRequirements);

      writeManifest(root, manifest({ requirements: 'linked-requirements' }));
      const direct = detectProject(root);
      assert.equal(direct.kind, 'configurationBlocked');

      writeManifest(root, manifest({ requirements: 'linked-requirements/nested' }));
      const nested = detectProject(root);
      assert.equal(nested.kind, 'configurationBlocked');
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('non-regular manifest получает controlled InvalidManifest состояние', () => {
  withRoot((root) => {
    mkdirSync(path.join(root, '.harness', 'manifest.yaml'), { recursive: true });
    const project = detectProject(root);
    assert.equal(project.kind, 'invalidManifest');
    assert.equal(project.diagnostic.category, 'InvalidManifest');
  });
});

test('слишком большой manifest отклоняется до YAML parsing', () => {
  withRoot((root) => {
    writeManifest(root, 'a'.repeat(MAXIMUM_MANIFEST_SIZE_BYTES + 1));
    const project = detectProject(root);
    assert.equal(project.kind, 'invalidManifest');
    assert.equal(project.diagnostic.category, 'InvalidManifest');
    assert.match(project.diagnostic.message, /exceeds/u);
  });
});

test('глубоко вложенный manifest деградирует в controlled typed state', () => {
  withRoot((root) => {
    const deeplyNested = `${'nested:\n'.repeat(7000)}  value: true\n`;
    writeManifest(root, deeplyNested);
    const project = detectProject(root);
    assert.notEqual(project.kind, 'valid');
    assert.ok(
      project.diagnostic.category === 'InvalidManifest' ||
        project.diagnostic.category === 'UnexpectedInternalError',
    );
  });
});

test('FIFO manifest не блокирует дочерний Extension Host', (t) => {
  withRoot((root) => {
    const harnessDirectory = path.join(root, '.harness');
    const manifestPath = path.join(harnessDirectory, 'manifest.yaml');
    mkdirSync(harnessDirectory, { recursive: true });
    const fifo = spawnSync('mkfifo', [manifestPath]);
    if (fifo.error !== undefined || fifo.status !== 0) {
      t.skip('mkfifo недоступен в текущем окружении.');
      return;
    }

    const moduleUrl = new URL('../../src/projectModel/manifestService.ts', import.meta.url).href;
    const probe = spawnSync(
      process.execPath,
      [
        '--import',
        'tsx',
        '--input-type=module',
        '--eval',
        `import { detectProject } from ${JSON.stringify(moduleUrl)}; console.log(JSON.stringify(detectProject(${JSON.stringify(root)})));`,
      ],
      { cwd: process.cwd(), encoding: 'utf8', timeout: 1000 },
    );

    assert.equal(probe.error, undefined, probe.stderr);
    assert.equal(probe.status, 0, probe.stderr);
    const project = JSON.parse(probe.stdout) as { kind: string; diagnostic: { category: string } };
    assert.equal(project.kind, 'invalidManifest');
    assert.equal(project.diagnostic.category, 'InvalidManifest');
  });
});

test('подмена manifest внешним symlink перед open не читает внешний target', () => {
  // F-008 symlink-swap regression на реальной Linux capability (без явной
  // capability detectProject строит её из реального `process.platform`/
  // `constants`, что на раннере этой сессии — Linux) — наблюдаемое поведение
  // не меняется после введения ManifestOpenCapability.
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      writeManifest(root);
      const manifestPath = path.join(root, '.harness', 'manifest.yaml');
      const outsideManifest = path.join(outside, 'external-manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));

      const project = detectProject(root, {
        beforeOpen: () => {
          rmSync(manifestPath);
          symlinkSync(outsideManifest, manifestPath);
        },
      });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(project.diagnostic.message, /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('подмена промежуточного ancestor (.harness) на symlink перед open блокируется реальной Linux capability (ADR-005)', () => {
  // F-001 fix: единственный сценарий, который реально требует Linux-specific
  // `deriveOpenedPath`-ветку `assertOpenedManifestContained` — подмена
  // ПРОМЕЖУТОЧНОГО ancestor directory (`.harness`), а не финального
  // component (уже покрыто F-008 regression выше) и не статический symlink
  // (отклоняется до open, см. F-002 тесты ниже). Портируемый dev/ino check
  // не ловит этот случай: и открытый descriptor, и `lstat(manifestPath)`
  // после подмены проходят через один и тот же подменённый ancestor, поэтому
  // dev/ino совпадают по построению. Отличает это только canonical-path
  // re-derivation через `/proc/self/fd` (Linux-only), поэтому здесь
  // намеренно используется реальная (не инъецированная) capability —
  // `detectProject` без `hooks.capability` строит её из настоящего
  // `process.platform`/`constants`, что на раннере этой сессии — Linux.
  // По `ADR-005` зеркальный assertion под non-Linux capability здесь
  // намеренно не пишется: отсутствие этой защиты там — принятый остаточный
  // риск, а не гарантия, и ложно-подтверждающий тест был бы хуже отсутствия
  // теста.
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      writeManifest(root);
      const harnessDirectory = path.join(root, '.harness');
      const outsideManifest = path.join(outside, 'manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));

      const project = detectProject(root, {
        beforeOpen: () => {
          rmSync(harnessDirectory, { recursive: true, force: true });
          symlinkSync(outside, harnessDirectory);
        },
      });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(project.diagnostic.message, /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('корректный проект достигает valid под macOS-shaped capability без deriveOpenedPath (ADR-005, F-003)', () => {
  withRoot((root) => {
    writeManifest(root);
    const project = detectProject(root, { capability: DARWIN_LIKE_CAPABILITY });
    assert.equal(project.kind, 'valid');
    assert.equal(project.configuredPaths.taskDirectory, 'planning/tasks');
  });
});

test('.harness/manifest.yaml как статический symlink на внешний файл блокируется под Windows-shaped capability (F-002)', () => {
  // Отличается от существующего теста `symlink configured path за пределами
  // root блокируется…` (это другая функция — `resolveContainedPath` для
  // configured paths). Здесь symlink — сам `manifest.yaml`, покрывается
  // pre-open `realpathSync`+`isContained(realRoot, realManifest)` в
  // `detectProject`. Эта проверка выполняется до какого-либо использования
  // `capability`, поэтому она гарантированно не зависит от platform profile —
  // тест подтверждает это явной инъекцией non-Linux capability.
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      mkdirSync(path.join(root, '.harness'), { recursive: true });
      const outsideManifest = path.join(outside, 'external-manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));
      symlinkSync(outsideManifest, path.join(root, '.harness', 'manifest.yaml'));

      const project = detectProject(root, { capability: WINDOWS_LIKE_CAPABILITY });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(JSON.stringify(project), /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('.harness/manifest.yaml как статический symlink на внешний файл блокируется под macOS-shaped capability (F-002, F-003)', () => {
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      mkdirSync(path.join(root, '.harness'), { recursive: true });
      const outsideManifest = path.join(outside, 'external-manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));
      symlinkSync(outsideManifest, path.join(root, '.harness', 'manifest.yaml'));

      const project = detectProject(root, { capability: DARWIN_LIKE_CAPABILITY });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(JSON.stringify(project), /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('подмена финального component symlink-ом блокируется и под macOS-shaped capability без deriveOpenedPath (F-003)', () => {
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      writeManifest(root);
      const manifestPath = path.join(root, '.harness', 'manifest.yaml');
      const outsideManifest = path.join(outside, 'external-manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));

      const project = detectProject(root, {
        capability: DARWIN_LIKE_CAPABILITY,
        beforeOpen: () => {
          rmSync(manifestPath);
          symlinkSync(outsideManifest, manifestPath);
        },
      });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(project.diagnostic.message, /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('подмена финального component symlink-ом блокируется и под capability без deriveOpenedPath', () => {
  // Доказывает, что portable-часть защиты (dev/ino identity, F-008) не
  // зависит от `capability.deriveOpenedPath` — final-component swap
  // блокируется одинаково под Windows/macOS-профилем. По ADR-005 здесь
  // намеренно НЕ проверяется защита от подмены промежуточного ancestor
  // directory под этой capability — это принятый остаточный риск, а не
  // гарантия, и ложно-подтверждающий тест этого сценария был бы хуже
  // отсутствия теста.
  withRoot((root) => {
    const outside = temporaryDirectory();
    try {
      writeManifest(root);
      const manifestPath = path.join(root, '.harness', 'manifest.yaml');
      const outsideManifest = path.join(outside, 'external-manifest.yaml');
      writeFileSync(outsideManifest, manifest().replace('0.6.0', 'banana'));

      const project = detectProject(root, {
        capability: WINDOWS_LIKE_CAPABILITY,
        beforeOpen: () => {
          rmSync(manifestPath);
          symlinkSync(outsideManifest, manifestPath);
        },
      });

      assert.equal(project.kind, 'configurationBlocked');
      assert.equal(project.diagnostic.category, 'ConfigurationBlocked');
      assert.doesNotMatch(project.diagnostic.message, /banana/u);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});
