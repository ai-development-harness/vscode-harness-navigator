import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  chmodSync,
  constants,
  mkdtempSync,
  mkdirSync,
  readdirSync,
  readlinkSync,
  renameSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import {
  ArtifactIndex,
  MAXIMUM_MARKDOWN_SIZE_BYTES,
  handleArtifactWatcherEvent,
  isHarnessAwareMarkdown,
  markdownFiles,
  readContainedMarkdown,
} from '../../src/projectModel/artifactIndex';
import type { ConfiguredPaths, ValidProjectState } from '../../src/projectModel/projectState';

function withProject(callback: (root: string) => void): void {
  const root = mkdtempSync(path.join(tmpdir(), 'navigator-index-'));
  try {
    callback(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function project(root: string): ValidProjectState {
  return {
    kind: 'valid',
    workspaceRoot: root,
    release: '0.6.0',
    configuredPaths: {
      taskDirectory: 'planning/tasks',
      projectOverview: 'docs/PROJECT.md',
      requirements: 'docs/requirements',
      adrDirectory: 'docs/adr',
      architecture: 'docs/architecture.md',
      openQuestions: 'docs/open-questions',
      openQuestionsIndex: 'docs/OPEN_QUESTIONS.md',
      roadmap: 'planning/PLAN.md',
      status: 'planning/STATUS.md',
    },
    diagnostic: {
      category: 'ValidHarnessProject',
      message: 'Harness manifest is valid.',
      messageArguments: [],
      detail: '',
    },
  };
}

function write(root: string, relative: string, content: string): void {
  const file = path.join(root, relative);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, content);
}

function artifact(id: string, fields = '', title = 'Тестовый артефакт'): string {
  return `---\nschema: 1\nid: ${id}\n${fields}---\n\n# ${id} — ${title}\n`;
}

test('строит единый индекс, backlinks и lifecycle REQ из проекции', () => {
  withProject((root) => {
    write(
      root,
      'planning/tasks/STEP-001.md',
      artifact('STEP-001', 'status: planned\nrequirements:\n  - REQ-001\n'),
    );
    write(root, 'docs/requirements/REQ-001.md', artifact('REQ-001', 'status: draft\n'));
    write(
      root,
      'docs/requirements/STATUS.md',
      '| ID | Status |\n| --- | --- |\n| REQ-001 | active |\n',
    );
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(index.get('REQ-001')?.status, 'active');
    assert.deepEqual(index.get('REQ-001')?.incomingRelations, ['STEP-001']);
  });
});

test('STEP depends_on и OQ affects строят outgoing и incoming relations', () => {
  withProject((root) => {
    write(root, 'planning/tasks/STEP-002.md', artifact('STEP-002', 'status: planned\n'));
    write(root, 'planning/tasks/STEP-003.md', artifact('STEP-003', 'depends_on:\n  - STEP-002\n'));
    write(root, 'docs/open-questions/OQ-001.md', artifact('OQ-001', 'affects:\n  - STEP-003\n'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.ok(index.get('STEP-003')?.outgoingRelations.includes('STEP-002'));
    assert.ok(index.get('STEP-002')?.incomingRelations.includes('STEP-003'));
    assert.ok(index.get('STEP-003')?.incomingRelations.includes('OQ-001'));
  });
});

test('изолирует malformed artifact, duplicate и неизвестную связь', () => {
  withProject((root) => {
    write(
      root,
      'planning/tasks/STEP-001.md',
      artifact('STEP-001', 'status: planned\nrequirements:\n  - REQ-999\n'),
    );
    write(
      root,
      'planning/tasks/STEP-001-copy.md',
      artifact('STEP-001', 'status: planned\nrequirements:\n  - REQ-999\n'),
    );
    write(root, 'docs/requirements/REQ-002-invalid.md', '# без frontmatter\n');
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    const categories = index.snapshot().diagnostics.map((item) => item.category);
    assert.ok(categories.includes('DuplicateArtifactId'));
    assert.ok(categories.includes('ArtifactParseError'));
    assert.ok(categories.includes('InvalidArtifactReference'));
    assert.ok(index.get('STEP-001'));
  });
});

test('удаление winning duplicate восстанавливает следующий корректный artifact', () => {
  withProject((root) => {
    const first = 'planning/tasks/STEP-001-a.md';
    const second = 'planning/tasks/STEP-001-b.md';
    write(root, first, artifact('STEP-001', 'status: planned\n', 'Первый'));
    write(root, second, artifact('STEP-001', 'status: planned\n', 'Второй'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(index.get('STEP-001')?.title, 'Первый');
    rmSync(path.join(root, first));
    index.updatePath(project(root), path.join(root, first));
    assert.equal(index.get('STEP-001')?.title, 'Второй');
    assert.ok(
      !index.snapshot().diagnostics.some((item) => item.category === 'DuplicateArtifactId'),
    );
  });
});

test('incremental update изменяет затронутый artifact без полного scan', () => {
  withProject((root) => {
    write(root, 'planning/tasks/STEP-001.md', artifact('STEP-001', 'status: planned\n'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    write(root, 'planning/tasks/STEP-002.md', artifact('STEP-002', 'status: planned\n'));
    index.updatePath(project(root), path.join(root, 'planning/tasks/STEP-002.md'));
    assert.ok(index.get('STEP-002'));
  });
});

test('пустой каталог normal, отсутствующий configured каталог диагностируется', () => {
  withProject((root) => {
    for (const directory of [
      'planning/tasks',
      'docs/requirements',
      'docs/adr',
      'docs/open-questions',
    ]) {
      mkdirSync(path.join(root, directory), { recursive: true });
    }
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.ok(
      !index.snapshot().diagnostics.some((item) => item.category === 'ArtifactDirectoryMissing'),
    );
    rmSync(path.join(root, 'docs/adr'), { recursive: true });
    index.rebuild(project(root));
    assert.ok(
      index.snapshot().diagnostics.some((item) => item.category === 'ArtifactDirectoryMissing'),
    );
  });
});

test('STATUS.md является projection, а не malformed REQ artifact', () => {
  withProject((root) => {
    write(root, 'docs/requirements/STATUS.md', '| ID | Status |\n| --- | --- |\n');
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.ok(
      !index.snapshot().diagnostics.some((item) => item.messageArguments[0] === 'STATUS.md'),
    );
  });
});

test('изменение requirements STATUS обновляет lifecycle без scan artifacts', () => {
  withProject((root) => {
    write(root, 'docs/requirements/REQ-001.md', artifact('REQ-001', 'status: draft\n'));
    write(
      root,
      'docs/requirements/STATUS.md',
      '| ID | Status |\n| --- | --- |\n| REQ-001 | active |\n',
    );
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    write(
      root,
      'docs/requirements/STATUS.md',
      '| ID | Status |\n| --- | --- |\n| REQ-001 | completed |\n',
    );
    index.updatePath(project(root), path.join(root, 'docs/requirements/STATUS.md'));
    assert.equal(index.get('REQ-001')?.status, 'completed');
  });
});

test('read seam блокирует symlink swap между проверкой и open', () => {
  withProject((root) => {
    const file = path.join(root, 'planning/tasks/STEP-001.md');
    write(root, 'planning/tasks/STEP-001.md', artifact('STEP-001'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-outside-'));
    try {
      const external = path.join(outside, 'external.md');
      writeFileSync(external, 'внешнее содержимое');
      assert.throws(() =>
        readContainedMarkdown(root, file, {
          noFollowFlag: constants.O_NOFOLLOW,
          beforeOpen: () => {
            unlinkSync(file);
            symlinkSync(external, file);
          },
        }),
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('classifier включает только configured и Harness-aware Markdown', () => {
  withProject((root) => {
    const paths = project(root).configuredPaths;
    assert.ok(isHarnessAwareMarkdown(root, path.join(root, 'planning/tasks/STEP-001.md'), paths));
    assert.ok(isHarnessAwareMarkdown(root, path.join(root, '.harness/docs/guide.md'), paths));
    assert.ok(isHarnessAwareMarkdown(root, path.join(root, 'docs/PROJECT.md'), paths));
    assert.ok(isHarnessAwareMarkdown(root, path.join(root, 'docs/guides/usage.md'), paths));
    assert.ok(isHarnessAwareMarkdown(root, path.join(root, 'README.md'), paths));
    assert.ok(!isHarnessAwareMarkdown(root, path.join(root, 'node_modules/a/readme.md'), paths));
  });
});

test('reference хранит range и диагностирует неизвестный текстовый ID', () => {
  withProject((root) => {
    write(root, 'docs/guides/usage.md', 'См. REQ-999 для примера.\n');
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    const reference = index.snapshot().references.find((item) => item.targetId === 'REQ-999');
    assert.equal(reference?.length, 'REQ-999'.length);
    assert.ok(index.snapshot().diagnostics.some((item) => item.messageArguments[0] === 'REQ-999'));
  });
});

test('F-011: подмена ancestor directory между lstat-проверкой и рекурсивным open не читает внешний каталог', (t) => {
  if (process.platform !== 'linux') {
    t.skip('directory descriptor identity-проверка F-011 доступна только на Linux.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/ancestor/leaf/STEP-100.md', artifact('STEP-100'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-ancestor-outside-'));
    try {
      write(outside, 'leaf/STEP-999.md', artifact('STEP-999'));
      const ancestor = path.join(root, 'planning/tasks/ancestor');
      const swapped = path.join(root, 'planning/tasks/ancestor-original');
      let swapPerformed = false;
      const files = markdownFiles(root, 'planning/tasks', {
        beforeDescend: (name) => {
          // Подмена происходит именно между lstat-проверкой "leaf" (уже
          // выполненной через fd-relative path родителя "ancestor") и
          // рекурсивным open этого "leaf": переименовываем "ancestor" в
          // сторону и подставляем на его место symlink на внешний каталог,
          // у которого тоже есть подкаталог "leaf".
          if (name === 'leaf' && !swapPerformed) {
            swapPerformed = true;
            renameSync(ancestor, swapped);
            symlinkSync(outside, ancestor);
          }
        },
      });
      assert.ok(swapPerformed, 'hook должен был сработать перед рекурсией в leaf');
      assert.ok(
        !files.some((file) => file.includes('STEP-999')),
        'внешний STEP-999.md не должен попасть в scan после подмены ancestor',
      );
      assert.ok(
        files.some((file) => file.includes('STEP-100')),
        'уже открытый descriptor ancestor должен по-прежнему видеть свой оригинальный leaf/STEP-100.md',
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('F-019: подмена ancestor configured каталога верхнего уровня между containment-check и open фейлит закрыто, не читает внешний каталог', (t) => {
  if (process.platform !== 'linux') {
    t.skip('post-open containment re-derivation F-019 доступна только на Linux.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/STEP-100.md', artifact('STEP-100'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-root-outside-'));
    try {
      // Внешний каталог содержит подкаталог с тем же basename ("tasks"), что
      // и подменяемый configured каталог верхнего уровня, чтобы open по уже
      // зафиксированной строке пути "успешно" открыл внешний объект — именно
      // это должна поймать post-open re-derivation, а не просто O_NOFOLLOW
      // (который защищает только финальный component строки пути, а не
      // "planning") и не dev/ino (на глубине 0 нет доверенного "expected" —
      // это и был сам дефект F-019).
      write(outside, 'tasks/STEP-999.md', artifact('STEP-999'));
      const configuredParent = path.join(root, 'planning');
      const swapped = path.join(root, 'planning-original');
      let swapPerformed = false;
      let externalVisibleAtHookTime = false;
      assert.throws(
        () =>
          markdownFiles(root, 'planning/tasks', {
            beforeRootOpen: () => {
              swapPerformed = true;
              // Подмена ancestor ("planning"), а не самого "tasks": final
              // component строки пути остаётся обычным каталогом ("tasks"
              // внутри outside), поэтому O_NOFOLLOW его не блокирует. Этот
              // hook срабатывает СРАЗУ после containment-проверки строки
              // `realDirectory` и ДО открытия — то есть ровно в окне, которое
              // F-019 эксплуатировал (никакого промежуточного lstat identity
              // между этими двумя точками больше нет).
              renameSync(configuredParent, swapped);
              symlinkSync(outside, configuredParent);
              // Доказываем, что подмена реально активна в момент срабатывания
              // hook (а не что seam расположен вне настоящего окна, как было
              // структурной ошибкой прежнего F-016 теста, отмеченной F-020):
              // строковый readdir по уже зафиксированному `realDirectory`
              // прямо сейчас видит внешний файл.
              externalVisibleAtHookTime = readdirSync(path.join(root, 'planning/tasks')).includes(
                'STEP-999.md',
              );
            },
          }),
        /ContainmentError/u,
      );
      assert.ok(swapPerformed, 'hook должен был сработать перед open верхнего уровня');
      assert.ok(
        externalVisibleAtHookTime,
        'подмена должна быть реально видима по строковому пути в момент срабатывания hook — иначе seam вне настоящего окна',
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('F-022: подмена ancestor ПОСЛЕ open, непосредственно перед readlink-based re-derivation, не приводит к утечке (directory)', (t) => {
  if (process.platform !== 'linux') {
    t.skip('readlink-based post-open re-derivation F-022 доступна только на Linux.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/STEP-100.md', artifact('STEP-100'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-f022-outside-'));
    try {
      write(outside, 'tasks/STEP-999.md', artifact('STEP-999'));
      const configuredParent = path.join(root, 'planning');
      const swapped = path.join(root, 'planning-original');
      let swapPerformed = false;
      let derivedLinkPath: string | undefined;
      // Прежняя реализация (`realpathSync('/proc/self/fd/<fd>')`) была
      // уязвима к подмене, происходящей ПОСЛЕ чтения magic-link, но ДО
      // завершения её собственного повторного покомпонентного resolve этой
      // строки (F-022). `readlinkSync` не имеет такого второго resolve — это
      // один syscall, поэтому у него структурно нет соответствующего окна.
      // Этот тест подтверждает это не описанием, а фактом: подмена ancestor
      // выполняется здесь же, непосредственно перед вызовом настоящего
      // `readlinkSync` уже открытого descriptor, и всё равно не даёт течь.
      // F-025: root и "planning" сами уже открываются как отдельные
      // покомпонентные уровни (root вообще не вызывает `derive`), поэтому
      // первый вызов `deriveOpenedDirectoryPath` относится к верификации
      // самого "planning", а сценарий этого теста (подмена ancestor уже
      // открытого "tasks") соответствует ВТОРОМУ вызову.
      let callCount = 0;
      const files = markdownFiles(root, 'planning/tasks', {
        deriveOpenedDirectoryPath: (descriptor) => {
          callCount += 1;
          if (callCount === 2 && !swapPerformed) {
            swapPerformed = true;
            renameSync(configuredParent, swapped);
            symlinkSync(outside, configuredParent);
          }
          derivedLinkPath = readlinkSync(`/proc/self/fd/${descriptor}`);
          return derivedLinkPath;
        },
      });
      assert.ok(
        swapPerformed,
        'hook должен был подменить ancestor перед readlink уже открытого fd',
      );
      assert.ok(
        derivedLinkPath !== undefined && derivedLinkPath.startsWith(root),
        'd_path уже открытого descriptor следует за rename своего собственного ancestor и остаётся внутри root, а не резолвится через новый symlink на его прежнем месте',
      );
      assert.ok(
        !files.some((file) => file.includes('STEP-999')),
        'внешний STEP-999.md не должен попасть в scan, несмотря на подмену ancestor после open',
      );
      assert.ok(
        files.some((file) => file.includes('STEP-100')),
        'оригинальный STEP-100.md должен остаться читаемым через anchored fd после rename своего ancestor',
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('F-022: containment fail-closed, когда re-derivation сообщает внешний путь (directory и file)', (t) => {
  if (process.platform !== 'linux') {
    t.skip('post-open re-derivation seam F-022 доступна только на Linux.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/STEP-100.md', artifact('STEP-100'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-f022-fail-closed-'));
    try {
      const externalDirectory = path.join(outside, 'tasks');
      mkdirSync(externalDirectory, { recursive: true });
      // Прямая проверка containment-логики независимо от того, каким
      // механизмом получена re-derived строка: если она когда-либо укажет
      // наружу realRoot (регрессия к старому `realpathSync`-поведению или
      // любой другой баг), scan обязан фейлиться закрыто, а не тихо
      // продолжить с внешним объектом.
      assert.throws(
        () =>
          markdownFiles(root, 'planning/tasks', {
            deriveOpenedDirectoryPath: () => externalDirectory,
          }),
        /ContainmentError/u,
      );
      const file = path.join(root, 'planning/tasks/STEP-100.md');
      const externalFile = path.join(outside, 'external.md');
      writeFileSync(externalFile, 'внешнее содержимое');
      assert.throws(
        () => readContainedMarkdown(root, file, { deriveOpenedPath: () => externalFile }),
        /ContainmentError/u,
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('F-017: подмена уже верифицированного вложенного каталога между identity-check и readdirSync не даёт утечь содержимому', (t) => {
  if (process.platform !== 'linux') {
    t.skip('fd-anchored identity re-check доступна только на Linux.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/ancestor/leaf/STEP-100.md', artifact('STEP-100'));
    const outside = mkdtempSync(path.join(tmpdir(), 'navigator-selfread-outside-'));
    try {
      writeFileSync(path.join(outside, 'STEP-999.md'), artifact('STEP-999'));
      const leaf = path.join(root, 'planning/tasks/ancestor/leaf');
      const swapped = path.join(root, 'planning/tasks/ancestor/leaf-original');
      const leafLogical = path.join('ancestor', 'leaf');
      let swapPerformed = false;
      const files = markdownFiles(root, 'planning/tasks', {
        beforeSelfRead: (logicalPath) => {
          // Это окно наступает уже ПОСЛЕ того, как identity "leaf" открыта и
          // сверена по dev/ino (F-011/F-016 механизм), но ДО readdirSync его
          // содержимого — именно это и есть реальный gap, который F-017
          // требует покрыть, а не более раннюю точку до входа в проверку.
          if (!swapPerformed && logicalPath.endsWith(leafLogical)) {
            swapPerformed = true;
            renameSync(leaf, swapped);
            symlinkSync(outside, leaf);
          }
        },
      });
      assert.ok(
        swapPerformed,
        'hook должен был сработать после identity-проверки "leaf", перед readdirSync',
      );
      assert.ok(
        !files.some((file) => file.includes('STEP-999')),
        'containment: содержимое подменённого после verify каталога не должно попасть в scan — ' +
          'readdirSync anchored к уже открытому fd, а не к строке пути',
      );
      assert.ok(
        files.some((file) => file.includes('STEP-100')),
        'anchored fd должен по-прежнему читать оригинальное содержимое "leaf", несмотря на подмену пути после verify',
      );
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});

test('F-015: подкаталог, удалённый во время обхода (ENOENT), изолируется без потери валидных соседей', () => {
  withProject((root) => {
    write(root, 'planning/tasks/keep/STEP-100.md', artifact('STEP-100'));
    write(root, 'planning/tasks/flaky/STEP-200.md', artifact('STEP-200'));
    const keep = path.join(root, 'planning/tasks/keep');
    const flaky = path.join(root, 'planning/tasks/flaky');
    let deleted = false;
    const errors: string[] = [];
    const files = markdownFiles(root, 'planning/tasks', {
      beforeDescend: (name) => {
        if (deleted) return;
        deleted = true;
        // Независимо от порядка readdir удаляем именно "другой" каталог,
        // чтобы детерминированно смоделировать конкурентное удаление уже
        // перечисленного, но ещё не посещённого entry (обычная активность
        // вроде `rm -rf`, а не adversarial swap).
        rmSync(name === 'keep' ? flaky : keep, { recursive: true, force: true });
      },
      onSubtreeError: (logicalPath) => {
        errors.push(logicalPath);
      },
    });
    assert.ok(deleted, 'hook должен был сработать перед удалением соседнего поддерева');
    assert.ok(
      files.some((file) => file.includes('STEP-100')) ||
        files.some((file) => file.includes('STEP-200')),
      'хотя бы одно поддерево (то, что не было удалено) должно остаться просканированным',
    );
    assert.equal(
      files.length,
      1,
      'ровно одно поддерево уцелело: удалённое соседнее поддерево изолировано, но не абортировало весь scan',
    );
    assert.ok(
      errors.length > 0,
      'удалённое поддерево должно быть сообщено через onSubtreeError, а не тихо проигнорировано',
    );
  });
});

test('F-015: chmod 000 поддерево изолируется, а остальные valid artifacts и references не теряются', (t) => {
  if (process.platform === 'win32') {
    t.skip('chmod 000 недостоверен на Windows.');
    return;
  }
  if (typeof process.getuid === 'function' && process.getuid() === 0) {
    t.skip('root обходит permission enforcement — сценарий недостоверен под root.');
    return;
  }
  withProject((root) => {
    write(root, 'planning/tasks/STEP-100.md', artifact('STEP-100'));
    write(root, 'planning/tasks/blocked/STEP-200.md', artifact('STEP-200'));
    write(root, 'docs/guides/usage.md', 'См. STEP-100 в примере.\n');
    const blocked = path.join(root, 'planning/tasks/blocked');
    chmodSync(blocked, 0o000);
    try {
      const index = new ArtifactIndex();
      index.rebuild(project(root));
      assert.ok(
        index.get('STEP-100'),
        'valid artifact вне недоступного поддерева должен остаться проиндексированным',
      );
      assert.equal(
        index.get('STEP-200'),
        undefined,
        'artifact внутри недоступного поддерева недостижим и не публикуется',
      );
      assert.ok(
        index.snapshot().diagnostics.some((item) => item.category === 'ArtifactDirectoryMissing'),
        'недоступное поддерево должно быть диагностировано, а не тихо потеряно (F-015)',
      );
      const reference = index.snapshot().references.find((item) => item.targetId === 'STEP-100');
      assert.ok(
        reference,
        'Reference Index не должен обнуляться целиком из-за одного недоступного соседнего поддерева',
      );
    } finally {
      chmodSync(blocked, 0o755);
    }
  });
});

test('F-012: невалидный target вроде PROJECT игнорируется как relation, а не диагностируется', () => {
  withProject((root) => {
    write(
      root,
      'planning/tasks/STEP-001.md',
      artifact('STEP-001', 'status: planned\ndepends_on:\n  - PROJECT\n'),
    );
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.deepEqual(index.get('STEP-001')?.outgoingRelations, []);
    assert.ok(
      !index
        .snapshot()
        .diagnostics.some(
          (item) =>
            item.category === 'InvalidArtifactReference' && item.messageArguments[0] === 'PROJECT',
        ),
    );
  });
});

test('ADR supersedes строит outgoing и incoming relations между ADR', () => {
  withProject((root) => {
    write(root, 'docs/adr/ADR-001.md', artifact('ADR-001', 'status: accepted\n'));
    write(
      root,
      'docs/adr/ADR-002.md',
      artifact('ADR-002', 'status: accepted\nsupersedes:\n  - ADR-001\n'),
    );
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.ok(index.get('ADR-002')?.outgoingRelations.includes('ADR-001'));
    assert.ok(index.get('ADR-001')?.incomingRelations.includes('ADR-002'));
    assert.equal(index.get('ADR-001')?.kind, 'ADR');
    assert.equal(index.get('ADR-002')?.kind, 'ADR');
  });
});

test('OQ артефакт получает kind OQ и участвует в relations как самостоятельная identity', () => {
  withProject((root) => {
    write(root, 'planning/tasks/STEP-001.md', artifact('STEP-001', 'status: planned\n'));
    write(root, 'docs/open-questions/OQ-005.md', artifact('OQ-005', 'affects:\n  - STEP-001\n'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(index.get('OQ-005')?.kind, 'OQ');
    assert.ok(index.get('OQ-005')?.outgoingRelations.includes('STEP-001'));
    assert.ok(index.get('STEP-001')?.incomingRelations.includes('OQ-005'));
  });
});

test('F-014: prefix и H1 mismatch изолируются как ArtifactParseError, не ломая остальные artifacts', () => {
  withProject((root) => {
    // Имя файла не соответствует frontmatter id (prefix mismatch).
    write(root, 'planning/tasks/STEP-001.md', artifact('STEP-002', 'status: planned\n'));
    // Frontmatter id совпадает с именем файла, но H1 не начинается с id (H1 mismatch).
    write(
      root,
      'planning/tasks/STEP-003.md',
      '---\nschema: 1\nid: STEP-003\nstatus: planned\n---\n\n# Неверный заголовок без id\n',
    );
    write(root, 'planning/tasks/STEP-004.md', artifact('STEP-004', 'status: planned\n'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(
      index.snapshot().diagnostics.filter((item) => item.category === 'ArtifactParseError').length,
      2,
    );
    assert.equal(index.get('STEP-002'), undefined);
    assert.equal(index.get('STEP-003'), undefined);
    assert.ok(index.get('STEP-004'), 'корректный artifact не должен пострадать от соседних ошибок');
  });
});

test('F-014: STATUS.md в реальной generated five-column projection форме читается корректно', () => {
  withProject((root) => {
    write(root, 'docs/requirements/REQ-001.md', artifact('REQ-001', 'status: draft\n'));
    write(
      root,
      'docs/requirements/STATUS.md',
      [
        '# Requirements Status',
        '',
        '| REQ | Название | Статус | Реализующие STEP | Evidence |',
        '|---|---|---|---|---|',
        '| [REQ-001](REQ-001-read-only.md) | Пример требования | partial | STEP-001, STEP-002 | sha256:aaaa |',
        '',
      ].join('\n'),
    );
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(index.get('REQ-001')?.status, 'partial');
    assert.ok(
      !index.snapshot().diagnostics.some((item) => item.category === 'ProjectionReadError'),
    );
  });
});

test('F-014: malformed STATUS.md диагностирует ProjectionReadError и восстанавливается после исправления', () => {
  withProject((root) => {
    write(root, 'docs/requirements/REQ-001.md', artifact('REQ-001', 'status: draft\n'));
    write(root, 'docs/requirements/STATUS.md', 'REQ-001 упомянут вне таблицы, без колонок\n');
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.ok(index.snapshot().diagnostics.some((item) => item.category === 'ProjectionReadError'));
    write(
      root,
      'docs/requirements/STATUS.md',
      '| ID | Status |\n| --- | --- |\n| REQ-001 | active |\n',
    );
    index.updatePath(project(root), path.join(root, 'docs/requirements/STATUS.md'));
    assert.equal(index.get('REQ-001')?.status, 'active');
    assert.ok(
      !index.snapshot().diagnostics.some((item) => item.category === 'ProjectionReadError'),
    );
  });
});

test('F-014: оверсайз artifact input изолируется как ArtifactParseError без чтения полного содержимого', () => {
  withProject((root) => {
    const oversized = artifact('STEP-001') + 'x'.repeat(MAXIMUM_MARKDOWN_SIZE_BYTES + 1);
    write(root, 'planning/tasks/STEP-001.md', oversized);
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    assert.equal(index.get('STEP-001'), undefined);
    assert.ok(index.snapshot().diagnostics.some((item) => item.category === 'ArtifactParseError'));
  });
});

test('F-014: FIFO artifact input не блокирует read seam и не публикуется как artifact', (t) => {
  withProject((root) => {
    const fifoPath = path.join(root, 'planning/tasks/STEP-001.md');
    mkdirSync(path.dirname(fifoPath), { recursive: true });
    const fifo = spawnSync('mkfifo', [fifoPath]);
    if (fifo.error !== undefined || fifo.status !== 0) {
      t.skip('mkfifo недоступен в текущем окружении.');
      return;
    }
    try {
      // markdownFiles фильтрует не-regular entries на уровне readdir: FIFO
      // никогда не должен попасть в scanned file list.
      const files = markdownFiles(root, 'planning/tasks');
      assert.ok(!files.includes(fifoPath));
      // Defense-in-depth: даже прямой вызов read seam на FIFO path не
      // блокируется и завершается управляемой ошибкой, а не hang.
      assert.throws(() => readContainedMarkdown(root, fifoPath));
    } finally {
      rmSync(fifoPath, { force: true });
    }
  });
});

test('F-014: arbitrary configured watcher roots — index работает с нестандартными именами каталогов', () => {
  withProject((root) => {
    const customPaths: ConfiguredPaths = {
      taskDirectory: 'work/steps',
      projectOverview: 'spec/overview.md',
      requirements: 'spec/reqs',
      adrDirectory: 'spec/decisions',
      architecture: 'spec/architecture.md',
      openQuestions: 'spec/questions',
      openQuestionsIndex: 'spec/OPEN_QUESTIONS.md',
      roadmap: 'plan/ROADMAP.md',
      status: 'plan/STATUS.md',
    };
    write(root, 'work/steps/STEP-001.md', artifact('STEP-001', 'status: planned\n'));
    write(root, 'spec/reqs/REQ-001.md', artifact('REQ-001', 'status: draft\n'));
    write(root, 'spec/decisions/ADR-001.md', artifact('ADR-001', 'status: accepted\n'));
    write(root, 'spec/questions/OQ-001.md', artifact('OQ-001', 'affects:\n  - STEP-001\n'));
    const index = new ArtifactIndex();
    index.rebuild({ ...project(root), configuredPaths: customPaths });
    assert.ok(index.get('STEP-001'));
    assert.ok(index.get('REQ-001'));
    assert.ok(index.get('ADR-001'));
    assert.ok(index.get('OQ-001')?.outgoingRelations.includes('STEP-001'));
  });
});

test('F-021/F-024: watcher-обработчик вызывает инкрементальный ArtifactIndex.updatePath, а не полный rebuild', () => {
  withProject((root) => {
    write(root, 'planning/tasks/STEP-001.md', artifact('STEP-001', 'status: planned\n'));
    const index = new ArtifactIndex();
    index.rebuild(project(root));
    write(root, 'planning/tasks/STEP-002.md', artifact('STEP-002', 'status: planned\n'));
    // F-024: прежняя версия этого теста удовлетворялась и `updatePath`, и
    // полным `rebuild(project)` — обе assertions (`STEP-002` появился,
    // `STEP-001` присутствует) выполняются в обоих случаях, если содержимое
    // диска валидно. Различающий сигнал: удаляем STEP-001.md с диска ПЕРЕД
    // вызовом обработчика на изменившийся STEP-002.md. Инкрементальный
    // `updatePath` трогает только changed path (STEP-002.md) и оставляет
    // уже проиндексированный STEP-001 нетронутым в памяти, тогда как любой
    // полный `rebuild(project)` заново просканировал бы диск и потерял бы
    // STEP-001 (файла там больше нет). Тест поэтому падает на регрессии,
    // подменяющей `updatePath` на `rebuild`.
    rmSync(path.join(root, 'planning/tasks/STEP-001.md'));
    // Это ровно та функция, которую все три обработчика (create/change/
    // delete) artifact FileSystemWatcher в ProjectStateService.createArtifactWatcher
    // вызывают на каждое событие. Проверяется здесь напрямую и
    // детерминированно (без реального FileSystemWatcher и его таймингов),
    // чтобы регрессия, ломающая эту связку, была поймана независимо от
    // того, успел ли watcher сработать в конкретном integration-прогоне
    // быстрее watcher-only окна.
    handleArtifactWatcherEvent(index, project(root), path.join(root, 'planning/tasks/STEP-002.md'));
    assert.ok(
      index.get('STEP-002'),
      'handleArtifactWatcherEvent должен инкрементально проиндексировать changed path через updatePath',
    );
    assert.ok(
      index.get('STEP-001'),
      'STEP-001 уже удалён с диска, но остаётся в индексе: полный rebuild потерял бы его, ' +
        'поэтому его присутствие доказывает именно инкрементальный updatePath, а не rebuild',
    );
  });
});
