import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  readdirSync,
  readlinkSync,
  realpathSync,
} from 'node:fs';
import path from 'node:path';
import { load } from 'js-yaml';
import type { ConfiguredPaths, ProjectDiagnostic, ValidProjectState } from './projectState';

export type ArtifactKind = 'STEP' | 'REQ' | 'ADR' | 'OQ';

export interface Artifact {
  readonly id: string;
  readonly title: string;
  readonly kind: ArtifactKind;
  readonly status: string | undefined;
  readonly file: string;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly outgoingRelations: readonly string[];
  readonly incomingRelations: readonly string[];
}

export interface ArtifactSnapshot {
  readonly artifacts: readonly Artifact[];
  readonly diagnostics: readonly ProjectDiagnostic[];
  readonly references: readonly ArtifactReference[];
}

export interface ArtifactReference {
  readonly file: string;
  readonly offset: number;
  readonly length: number;
  readonly targetId: string;
}

const MESSAGES = {
  directoryMissing: 'A configured artifact directory is unavailable: {0}.',
  parseError: 'A Harness artifact cannot be parsed: {0}.',
  duplicateId: 'A duplicate Harness artifact identifier was found: {0}.',
  invalidReference: 'A Harness artifact contains an unknown reference: {0}.',
  projectionError: 'The requirements status projection cannot be read.',
} as const;

export const ARTIFACT_DIAGNOSTIC_MESSAGES = Object.values(MESSAGES);
// Artifact Markdown является недоверенным workspace input. 1 MiB достаточно
// для canonical STEP/REQ/ADR/OQ content и ограничивает память/время чтения.
export const MAXIMUM_MARKDOWN_SIZE_BYTES = 1024 * 1024;

/**
 * Определяет ровно область Markdown, которой может владеть Reference Index.
 * Файлы вне configured canonical roots не получают неявный доступ к parsing.
 */
export function isHarnessAwareMarkdown(
  root: string,
  file: string,
  _paths: ConfiguredPaths,
): boolean {
  if (!file.endsWith('.md') || file.includes(`${path.sep}node_modules${path.sep}`)) return false;
  const absolute = path.resolve(file);
  // Additional Markdown внутри validated Harness workspace является
  // Harness-aware; внешние файлы и node_modules исключаются до чтения.
  return contained(path.resolve(root), absolute);
}

/**
 * Безопасно читает один Markdown input после повторной containment и identity
 * проверки descriptor. Это не даёт parser-у получить содержимое файла, который
 * был заменён symlink-ом между обходом каталога и открытием.
 */
export interface ArtifactReadHooks {
  readonly beforeOpen?: () => void;
  readonly noFollowFlag?: number;
  readonly deriveOpenedPath?: ((descriptor: number) => string) | undefined;
}

export function readContainedMarkdown(
  root: string,
  candidate: string,
  hooks: ArtifactReadHooks = {},
): string {
  const realRoot = realpathSync(root);
  if (process.platform !== 'linux') {
    // Portable fallback (не-Linux): нет `/proc/self/fd`, поэтому ancestor
    // остаётся защищён только pre-open containment-проверкой строки —
    // остаточный риск, явно принятый ADR-005 §2-3 / ADR-006 §2-3.
    const realCandidate = realpathSync(candidate);
    if (!contained(realRoot, realCandidate) || !lstatSync(realCandidate).isFile()) {
      throw new Error('ContainmentError');
    }
    hooks.beforeOpen?.();
    return openAndReadVerifiedFile(realRoot, realCandidate, hooks);
  }
  // F-025: предыдущая версия резолвила `candidate` в ОДНУ multi-component
  // строку (`realpathSync(candidate)`) и открывала её одним `openSync`.
  // `O_NOFOLLOW` защищает только финальный component такого пути — подмена
  // ЛЮБОГО ancestor-компонента (например, родительского каталога) на symlink
  // наружу МЕЖДУ этим `realpathSync` и `openSync` заставляла kernel
  // прозрачно последовать через него, открыв внешний объект; последующая
  // readlink-based re-derivation (F-022) могла быть обманута, если внешнее
  // дерево переименовывалось обратно внутрь root ДО вызова `readlink`
  // (независимо подтверждено adversarial review). Вместо одного
  // multi-component open путь теперь проходится покомпонентно из уже
  // открытого anchor-descriptor (`walkAnchoredDirectory`, тот же примитив,
  // что использует `markdownFiles`): каждый промежуточный каталог
  // открывается как ЕДИНСТВЕННЫЙ (финальный для своего собственного вызова)
  // path component относительно fd родителя, поэтому `O_NOFOLLOW` реально
  // защищает каждый уровень, а не только последний component исходной
  // строки. Итоговый файл открывается тем же способом — как единственный
  // component относительно уже верифицированного descriptor родительского
  // каталога.
  const resolvedCandidate = path.resolve(candidate);
  const relative = path.relative(realRoot, resolvedCandidate);
  if (
    relative === '' ||
    relative === '..' ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error('ContainmentError');
  }
  const parentRelative = path.dirname(relative) === '.' ? '' : path.dirname(relative);
  const filename = path.basename(relative);
  const { descriptor: parentDescriptor, boundDirectory: parentBound } = walkAnchoredDirectory(
    realRoot,
    parentRelative,
  );
  try {
    hooks.beforeOpen?.();
    return openAndReadVerifiedFile(realRoot, path.join(parentBound, filename), hooks);
  } finally {
    if (parentDescriptor !== undefined) closeSync(parentDescriptor);
  }
}

function openAndReadVerifiedFile(
  realRoot: string,
  candidatePath: string,
  hooks: ArtifactReadHooks,
): string {
  const noFollowFlag =
    hooks.noFollowFlag ?? (constants as { readonly O_NOFOLLOW?: number }).O_NOFOLLOW;
  const nonBlockFlag = (constants as { readonly O_NONBLOCK?: number }).O_NONBLOCK;
  const descriptor = openSync(
    candidatePath,
    constants.O_RDONLY | (noFollowFlag ?? 0) | (nonBlockFlag ?? 0),
  );
  try {
    const opened = fstatSync(descriptor);
    const current = lstatSync(candidatePath);
    if (
      !opened.isFile() ||
      !current.isFile() ||
      opened.dev !== current.dev ||
      opened.ino !== current.ino
    ) {
      throw new Error('ContainmentError');
    }
    if (opened.size < 0 || opened.size > MAXIMUM_MARKDOWN_SIZE_BYTES) {
      throw new Error('MarkdownSizeError');
    }
    // Linux позволяет вывести kernel d_path открытого descriptor одним
    // `readlink(2)` (см. `descriptorLinkPath`) и закрыть замену
    // ancestor-каталога до чтения недоверенного Markdown: гарантия
    // Linux-specific (ADR-005 §2-3 / ADR-006 §2-3), non-Linux остаётся на
    // portable pre-open containment check выше.
    const deriveOpenedPath =
      hooks.deriveOpenedPath ??
      (process.platform === 'linux'
        ? (openedDescriptor: number) => descriptorLinkPath(openedDescriptor)
        : undefined);
    if (deriveOpenedPath !== undefined && !contained(realRoot, deriveOpenedPath(descriptor))) {
      throw new Error('ContainmentError');
    }
    const buffer = Buffer.alloc(opened.size);
    const bytesRead = readSync(descriptor, buffer, 0, opened.size, 0);
    if (bytesRead !== opened.size) throw new Error('MarkdownChangedError');
    return buffer.toString('utf8');
  } finally {
    closeSync(descriptor);
  }
}

/**
 * Возвращает kernel `d_path` уже открытого descriptor через один `readlink(2)`
 * на magic-link `/proc/self/fd/<fd>` (F-022). Это принципиально отличается от
 * `realpathSync('/proc/self/fd/<fd>')`: `realpathSync` — JS-реализация,
 * которая ПОСЛЕ чтения magic-link заново покомпонентно разрешает полученную
 * строку через текущий (mutable) filesystem namespace, что открывает второе
 * TOCTOU-окно между чтением kernel-строки и её повторным resolve. `readlink`
 * на `/proc/self/fd/<fd>` — единственный syscall, который отдаёт готовую
 * kernel-строку без какого-либо дальнейшего resolve; повторного окна для него
 * структурно не существует. Значение уже абсолютное и symlink-free по
 * построению kernel; единственная нормализация, которую эта функция обязана
 * сделать сама, — fail-closed отклонить нестандартную форму magic-link target
 * (не-абсолютный путь вроде `pipe:[...]`/`anon_inode:...`, либо suffix
 * ` (deleted)` для fd, чей target уже удалён с диска).
 */
function descriptorLinkPath(descriptor: number): string {
  const target = readlinkSync(`/proc/self/fd/${descriptor}`);
  if (!path.isAbsolute(target) || target.endsWith(' (deleted)')) {
    throw new Error('ContainmentError');
  }
  return target;
}

function contained(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative === '' ||
    (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
  );
}

function diagnostic(
  category: ProjectDiagnostic['category'],
  message: string,
  argument = '',
): ProjectDiagnostic {
  return { category, message, messageArguments: argument === '' ? [] : [argument], detail: '' };
}

function artifactKind(id: string): ArtifactKind | undefined {
  const match = /^(STEP|REQ|ADR|OQ)-\d+$/u.exec(id);
  return match?.[1] as ArtifactKind | undefined;
}

function isCandidateArtifact(file: string, kind: ArtifactKind): boolean {
  return new RegExp(`^${kind}-\\d+.*\\.md$`, 'u').test(path.basename(file));
}

function parseArtifact(file: string, root: string): Omit<Artifact, 'incomingRelations'> {
  const source = readContainedMarkdown(root, file);
  const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/u.exec(source);
  const frontmatterSource = frontmatter?.[1];
  const frontmatterBlock = frontmatter?.[0];
  if (frontmatterSource === undefined || frontmatterBlock === undefined)
    throw new Error('frontmatter');
  const metadata = load(frontmatterSource);
  if (typeof metadata !== 'object' || metadata === null || Array.isArray(metadata))
    throw new Error('metadata');
  const values = metadata as Record<string, unknown>;
  const id = typeof values.id === 'string' ? values.id : '';
  const kind = artifactKind(id);
  const heading = /^#\s+(.+)$/mu.exec(source.slice(frontmatterBlock.length));
  const headingText = heading?.[1];
  if (
    kind === undefined ||
    headingText === undefined ||
    !headingText.startsWith(`${id} `) ||
    !new RegExp(`^${id}(?:[-.]|$)`, 'u').test(path.basename(file))
  )
    throw new Error('identity');
  const relations = new Set<string>();
  for (const key of [
    'requirements',
    'adrs',
    'steps',
    'depends_on',
    'affects',
    'supersedes',
    'superseded_by',
  ] as const) {
    const value = values[key];
    if (Array.isArray(value))
      for (const item of value)
        if (typeof item === 'string' && artifactKind(item) !== undefined) relations.add(item);
  }
  return {
    id,
    kind,
    title: headingText.slice(id.length + 1).replace(/^[-—]\s*/u, ''),
    status: typeof values.status === 'string' ? values.status : undefined,
    file,
    metadata: values,
    outgoingRelations: [...relations],
  };
}

/**
 * Тестовые барьеры traversal, не добавляющие I/O в production (все опциональны):
 * - `beforeDescend` (F-011): вызывается прямо перед рекурсивным открытием
 *   каждой поддиректории, после того как её identity (dev/ino) уже
 *   зафиксирована через lstat на fd-relative пути родителя.
 * - `beforeRootOpen` (F-019/F-025): вызывается один раз, сразу после того как
 *   root открыт (trust anchor, как и везде в этом файле), и до начала
 *   покомпонентного спуска в `directory` через `walkAnchoredDirectory`.
 * - `beforeSelfRead` (F-017): вызывается внутри `visit` сразу после того как
 *   identity текущего (уже открытого и сверенного по dev/ino) каталога
 *   подтверждена, но перед `readdirSync` этого каталога — это и есть
 *   реальное TOCTOU-окно, которое закрывает fd-anchoring.
 * - `onSubtreeError` (F-015): вызывается, когда обработка конкретного entry
 *   (lstat, containment, рекурсивный спуск) завершилась ошибкой любого рода
 *   (включая ContainmentError, ENOENT конкурентного удаления, EACCES и т.п.);
 *   остальной scan продолжается, это не аборт.
 * - `deriveOpenedDirectoryPath` (F-022): подменяет `descriptorLinkPath` внутри
 *   `openVerifiedDirectoryLevel` — единственный production seam, позволяющий
 *   unit-тесту подставить значение post-open re-derivation напрямую.
 */
export interface DirectoryTraversalHooks {
  readonly beforeDescend?: (name: string, candidatePath: string) => void;
  readonly beforeRootOpen?: () => void;
  readonly beforeSelfRead?: (logicalPath: string, boundDirectory: string) => void;
  readonly onSubtreeError?: (logicalPath: string, error: unknown) => void;
  readonly deriveOpenedDirectoryPath?: (descriptor: number) => string;
}

interface DirectoryIdentity {
  readonly dev: number;
  readonly ino: number;
}

/**
 * Открывает directory по `candidatePath` (ВСЕГДА единственный path component
 * относительно уже открытого anchor — либо fd-relative
 * `/proc/self/fd/<parentFd>/<name>`, либо, для самого root, доверенный
 * `realRoot`), сверяет dev/ino с `expected`, затем — на Linux — выводит
 * kernel `d_path` уже открытого descriptor одним `readlink(2)`
 * (`descriptorLinkPath`, F-022) и проверяет containment против `realRoot`
 * ЭТОЙ строки.
 *
 * F-025: предыдущая (F-022) версия закрыла gонку внутри самой re-derivation
 * (`readlink` вместо `realpathSync`), но депth-0 open в `markdownFiles`
 * по-прежнему резолвил ВЕСЬ `directory` одним multi-component string open —
 * `O_NOFOLLOW` защищает только финальный component такой строки, поэтому
 * подмена ЛЮБОГО промежуточного ancestor'а (например, "planning" в
 * "planning/tasks") на symlink наружу МЕЖДУ pre-open containment-check и этим
 * open заставляла kernel прозрачно последовать через него и открыть внешний
 * объект; независимый adversarial review воспроизвёл это без единого test
 * hook. Единственный способ сделать `O_NOFOLLOW` значимым на КАЖДОМ уровне —
 * никогда не резолвить больше одного path component за один open: каждый
 * промежуточный каталог должен быть последним (и потому единственным
 * защищённым `O_NOFOLLOW`) component своего собственного вызова. Поэтому
 * `walkAnchoredDirectory` больше не строит multi-component строку в принципе:
 * она открывает root, а затем каждый segment `directory` — по одному, каждый
 * раз относительно уже открытого fd родителя.
 */
function openVerifiedDirectoryLevel(
  realRoot: string,
  candidatePath: string,
  expected: DirectoryIdentity | undefined,
  deriveOpenedDirectoryPath: (descriptor: number) => string,
): number | undefined {
  if (process.platform !== 'linux') return undefined;
  const noFollowFlag = (constants as { readonly O_NOFOLLOW?: number }).O_NOFOLLOW ?? 0;
  const directoryFlag = (constants as { readonly O_DIRECTORY?: number }).O_DIRECTORY ?? 0;
  const descriptor = openSync(candidatePath, constants.O_RDONLY | directoryFlag | noFollowFlag);
  try {
    const opened = fstatSync(descriptor);
    const openedLinkPath = deriveOpenedDirectoryPath(descriptor);
    if (
      !opened.isDirectory() ||
      (expected !== undefined && (opened.dev !== expected.dev || opened.ino !== expected.ino)) ||
      !contained(realRoot, openedLinkPath)
    ) {
      throw new Error('ContainmentError');
    }
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
  return descriptor;
}

function openAnchoredRootDirectory(realRoot: string): number | undefined {
  if (process.platform !== 'linux') return undefined;
  const noFollowFlag = (constants as { readonly O_NOFOLLOW?: number }).O_NOFOLLOW ?? 0;
  const directoryFlag = (constants as { readonly O_DIRECTORY?: number }).O_DIRECTORY ?? 0;
  const descriptor = openSync(realRoot, constants.O_RDONLY | directoryFlag | noFollowFlag);
  try {
    if (!fstatSync(descriptor).isDirectory()) throw new Error('ContainmentError');
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
  return descriptor;
}

/**
 * Открывает `root`, затем покомпонентно спускается в `relativeDirectory`
 * (каждый segment — отдельный, единственный-в-своём-вызове `open`,
 * анкорованный к fd родителя), не резолвя ни одной multi-component строки
 * ниже root (F-025). Возвращает descriptor/bound-path последнего уровня;
 * вызывающий обязан закрыть `descriptor`, когда он определён.
 */
function walkAnchoredDirectory(
  realRoot: string,
  relativeDirectory: string,
  hooks: {
    readonly beforeRootOpen?: (() => void) | undefined;
    readonly deriveOpenedDirectoryPath?: ((descriptor: number) => string) | undefined;
  } = {},
): { descriptor: number | undefined; boundDirectory: string } {
  const derive = hooks.deriveOpenedDirectoryPath ?? descriptorLinkPath;
  // root — уже установленный trust anchor этого файла (`realRoot`); повторная
  // readlink-based проверка containment root против самого себя избыточна, а
  // главное — не нужна: любой segment ниже root получает полноценную
  // fd-anchored `openVerifiedDirectoryLevel`-проверку через `derive`.
  let descriptor = openAnchoredRootDirectory(realRoot);
  let boundDirectory = descriptor === undefined ? realRoot : `/proc/self/fd/${descriptor}`;
  if (descriptor === undefined && !contained(realRoot, realpathSync(boundDirectory))) {
    throw new Error('ContainmentError');
  }
  hooks.beforeRootOpen?.();
  if (relativeDirectory === '') return { descriptor, boundDirectory };
  if (
    relativeDirectory === '..' ||
    relativeDirectory.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relativeDirectory)
  ) {
    if (descriptor !== undefined) closeSync(descriptor);
    throw new Error('ContainmentError');
  }
  try {
    for (const segment of relativeDirectory.split(path.sep)) {
      const candidateChild = path.join(boundDirectory, segment);
      const childStat = lstatSync(candidateChild);
      if (!childStat.isDirectory()) throw new Error('ContainmentError');
      const nextDescriptor = openVerifiedDirectoryLevel(
        realRoot,
        candidateChild,
        { dev: childStat.dev, ino: childStat.ino },
        derive,
      );
      if (descriptor !== undefined) closeSync(descriptor);
      descriptor = nextDescriptor;
      boundDirectory = descriptor === undefined ? candidateChild : `/proc/self/fd/${descriptor}`;
    }
  } catch (error) {
    if (descriptor !== undefined) closeSync(descriptor);
    throw error;
  }
  return { descriptor, boundDirectory };
}

export function markdownFiles(
  root: string,
  directory: string,
  hooks: DirectoryTraversalHooks = {},
): string[] {
  const realRoot = realpathSync(root);
  const files: string[] = [];
  const derive = hooks.deriveOpenedDirectoryPath ?? descriptorLinkPath;
  const relative = path.relative(realRoot, path.resolve(root, directory));

  const visit = (
    descriptor: number | undefined,
    boundDirectory: string,
    logicalPath: string,
  ): void => {
    try {
      if (descriptor === undefined && !contained(realRoot, realpathSync(boundDirectory))) return;
      // F-017: identity этого каталога уже подтверждена (open + dev/ino
      // сверка выше). Между этим моментом и readdirSync — единственное
      // оставшееся окно, где подмена того же пути на диске теоретически
      // могла бы повлиять на чтение; на Linux readdirSync читает через уже
      // открытый fd (`/proc/self/fd/<N>`), поэтому такая подмена не меняет
      // фактически читаемое содержимое.
      hooks.beforeSelfRead?.(logicalPath, boundDirectory);
      for (const entry of readdirSync(boundDirectory, { withFileTypes: true })) {
        // Symlink никогда не является частью scan: даже ссылка внутрь root
        // не нужна canonical модели и создаёт обходную поверхность.
        if (entry.isSymbolicLink() || entry.name === 'node_modules' || entry.name === '.git')
          continue;
        // child всегда fd-relative (когда descriptor доступен): имя
        // разрешается против уже открытого directory descriptor, а не против
        // mutable string ancestor, который мог быть подменён после lstat.
        const child = path.join(boundDirectory, entry.name);
        const childLogical = path.join(logicalPath, entry.name);
        try {
          const childStat = lstatSync(child);
          if (entry.isDirectory()) {
            if (!childStat.isDirectory()) continue;
            const realChild = realpathSync(child);
            if (!contained(realRoot, realChild)) continue;
            hooks.beforeDescend?.(entry.name, child);
            // На non-Linux нет native directory descriptor API: передаём
            // resolved real path как fail-closed fallback с уменьшенной
            // гарантией (F-011 остаточный риск задокументирован явно).
            const childDescriptor = openVerifiedDirectoryLevel(
              realRoot,
              child,
              { dev: childStat.dev, ino: childStat.ino },
              derive,
            );
            const childBound =
              childDescriptor === undefined ? realChild : `/proc/self/fd/${childDescriptor}`;
            visit(childDescriptor, childBound, childLogical);
          } else if (entry.isFile() && entry.name.endsWith('.md') && childStat.isFile()) {
            files.push(realpathSync(child));
          }
        } catch (error) {
          // F-015: любая ошибка на этом entry/поддереве — ContainmentError
          // (ancestor подменён между проверкой и open), ENOENT конкурентного
          // удаления, EACCES недоступного каталога и т.п. — изолируется:
          // исключается только этот entry, остальной scan продолжается, а
          // ошибка сообщается наблюдаемо через `onSubtreeError`, а не
          // проглатывается молча.
          hooks.onSubtreeError?.(childLogical, error);
        }
      }
    } finally {
      if (descriptor !== undefined) closeSync(descriptor);
    }
  };
  const { descriptor: rootDescriptor, boundDirectory: rootBound } = walkAnchoredDirectory(
    realRoot,
    relative,
    {
      beforeRootOpen: hooks.beforeRootOpen,
      deriveOpenedDirectoryPath: hooks.deriveOpenedDirectoryPath,
    },
  );
  visit(rootDescriptor, rootBound, directory);
  return files.sort((left, right) => left.localeCompare(right));
}

/** Общий read-only Artifact/Reference Index для одного valid workspace root. */
export class ArtifactIndex {
  private readonly byId = new Map<string, Artifact>();
  private readonly candidates = new Map<string, Omit<Artifact, 'incomingRelations'>>();
  private readonly diagnostics: ProjectDiagnostic[] = [];
  private references: ArtifactReference[] = [];

  rebuild(project: ValidProjectState): void {
    this.byId.clear();
    this.candidates.clear();
    this.diagnostics.splice(0);
    this.references = [];
    const directories: readonly [string, ArtifactKind][] = [
      [project.configuredPaths.taskDirectory, 'STEP'],
      [project.configuredPaths.requirements, 'REQ'],
      [project.configuredPaths.adrDirectory, 'ADR'],
      [project.configuredPaths.openQuestions, 'OQ'],
    ];
    for (const [directory, expected] of directories) {
      let files: string[];
      try {
        files = markdownFiles(project.workspaceRoot, directory, {
          // F-015: изолированная ошибка отдельного поддерева (не весь
          // configured каталог) всё равно должна быть наблюдаемой, а не
          // проглоченной молча вместе с потерянными artifacts этого поддерева.
          onSubtreeError: (logicalPath) => {
            this.diagnostics.push(
              diagnostic('ArtifactDirectoryMissing', MESSAGES.directoryMissing, logicalPath),
            );
          },
        });
      } catch {
        this.diagnostics.push(
          diagnostic('ArtifactDirectoryMissing', MESSAGES.directoryMissing, directory),
        );
        continue;
      }
      for (const file of files.filter((item) => isCandidateArtifact(item, expected))) {
        try {
          const parsed = parseArtifact(file, project.workspaceRoot);
          if (parsed.kind !== expected) throw new Error('kind');
          this.candidates.set(file, parsed);
        } catch {
          this.diagnostics.push(
            diagnostic('ArtifactParseError', MESSAGES.parseError, path.basename(file)),
          );
        }
      }
    }
    this.materializeCandidates();
    this.applyRequirementStatuses(project.workspaceRoot, project.configuredPaths);
    for (const artifact of this.byId.values())
      for (const relation of artifact.outgoingRelations) {
        const target = this.byId.get(relation);
        if (target === undefined)
          this.diagnostics.push(
            diagnostic('InvalidArtifactReference', MESSAGES.invalidReference, relation),
          );
        else
          this.byId.set(relation, {
            ...target,
            incomingRelations: [...target.incomingRelations, artifact.id].sort(),
          });
      }
    this.references = this.collectReferences(project.workspaceRoot, project.configuredPaths);
    this.rebuildReferenceDiagnostics();
  }

  /**
   * Обновляет только changed path: полный initial scan остаётся исключительно
   * в `rebuild`, поэтому watcher не обходит workspace на каждом событии.
   */
  updatePath(project: ValidProjectState, changedPath: string): void {
    const file = path.resolve(changedPath);
    if (!isHarnessAwareMarkdown(project.workspaceRoot, file, project.configuredPaths)) return;
    this.references = this.references.filter((reference) => reference.file !== file);
    this.diagnostics.splice(
      0,
      this.diagnostics.length,
      ...this.diagnostics.filter((item) => item.messageArguments[0] !== path.basename(file)),
    );
    this.candidates.delete(file);
    const expected = this.expectedKind(project, file);
    if (expected !== undefined) {
      try {
        const parsed = parseArtifact(file, project.workspaceRoot);
        if (parsed.kind !== expected) throw new Error('kind');
        this.candidates.set(file, parsed);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT')
          this.diagnostics.push(
            diagnostic('ArtifactParseError', MESSAGES.parseError, path.basename(file)),
          );
      }
      this.materializeCandidates();
      this.resetRequirementStatuses(project.workspaceRoot, project.configuredPaths);
      this.rebuildRelations();
    } else if (
      file ===
      path.resolve(project.workspaceRoot, project.configuredPaths.requirements, 'STATUS.md')
    ) {
      // Lifecycle REQ принадлежит только canonical status projection: его
      // изменение не запускает scan artifacts, но обновляет derived statuses.
      this.resetRequirementStatuses(project.workspaceRoot, project.configuredPaths);
    }
    this.references.push(
      ...this.referencesForFile(project.workspaceRoot, project.configuredPaths, file),
    );
    this.rebuildReferenceDiagnostics();
  }

  get(id: string): Artifact | undefined {
    return this.byId.get(id);
  }
  snapshot(): ArtifactSnapshot {
    return {
      artifacts: [...this.byId.values()].sort((a, b) => a.id.localeCompare(b.id)),
      diagnostics: [...this.diagnostics],
      references: [...this.references],
    };
  }

  private expectedKind(project: ValidProjectState, file: string): ArtifactKind | undefined {
    for (const [directory, kind] of [
      [project.configuredPaths.taskDirectory, 'STEP'],
      [project.configuredPaths.requirements, 'REQ'],
      [project.configuredPaths.adrDirectory, 'ADR'],
      [project.configuredPaths.openQuestions, 'OQ'],
    ] as const) {
      if (
        contained(path.resolve(project.workspaceRoot, directory), file) &&
        isCandidateArtifact(file, kind)
      )
        return kind;
    }
    return undefined;
  }

  /** Хранит все корректные candidates: после удаления winning duplicate
   * следующий файл публикуется детерминированно без полного scan workspace. */
  private materializeCandidates(): void {
    this.byId.clear();
    this.diagnostics.splice(
      0,
      this.diagnostics.length,
      ...this.diagnostics.filter((item) => item.category !== 'DuplicateArtifactId'),
    );
    for (const candidate of [...this.candidates.values()].sort((left, right) =>
      left.file.localeCompare(right.file),
    )) {
      if (this.byId.has(candidate.id)) {
        this.diagnostics.push(
          diagnostic('DuplicateArtifactId', MESSAGES.duplicateId, candidate.id),
        );
      } else {
        this.byId.set(candidate.id, { ...candidate, incomingRelations: [] });
      }
    }
  }

  private resetRequirementStatuses(root: string, paths: ConfiguredPaths): void {
    for (const artifact of this.byId.values()) {
      if (artifact.kind === 'REQ') {
        this.byId.set(artifact.id, { ...artifact, status: undefined });
      }
    }
    this.applyRequirementStatuses(root, paths);
  }

  private rebuildRelations(): void {
    this.diagnostics.splice(
      0,
      this.diagnostics.length,
      ...this.diagnostics.filter((item) => item.category !== 'InvalidArtifactReference'),
    );
    for (const artifact of this.byId.values()) {
      this.byId.set(artifact.id, { ...artifact, incomingRelations: [] });
    }
    for (const artifact of this.byId.values()) {
      for (const relation of artifact.outgoingRelations) {
        const target = this.byId.get(relation);
        if (target === undefined)
          this.diagnostics.push(
            diagnostic('InvalidArtifactReference', MESSAGES.invalidReference, relation),
          );
        else
          this.byId.set(relation, {
            ...target,
            incomingRelations: [...target.incomingRelations, artifact.id].sort(),
          });
      }
    }
  }

  private rebuildReferenceDiagnostics(): void {
    this.diagnostics.splice(
      0,
      this.diagnostics.length,
      ...this.diagnostics.filter((item) => !item.detail.startsWith('reference:')),
    );
    for (const reference of this.references) {
      if (this.byId.has(reference.targetId)) continue;
      this.diagnostics.push({
        ...diagnostic('InvalidArtifactReference', MESSAGES.invalidReference, reference.targetId),
        detail: `reference:${reference.file}`,
      });
    }
  }

  private applyRequirementStatuses(root: string, paths: ConfiguredPaths): void {
    try {
      const statusPath = path.join(root, paths.requirements, 'STATUS.md');
      const source = readContainedMarkdown(root, statusPath);
      let parsedRows = 0;
      for (const row of source.split(/\r?\n/u)) {
        const cells = row.split('|').map((cell) => cell.trim());
        const id = /\b(REQ-\d+)\b/u.exec(cells[1] ?? '')?.[1];
        // Generated Harness STATUS имеет title во втором столбце и lifecycle
        // в третьем; короткий legacy-shaped fixture остаётся читаемым.
        const status = cells.length >= 6 ? cells[3] : cells[2];
        if (id === undefined || status === undefined || /^-+$/u.test(id)) continue;
        parsedRows += 1;
        const artifact = this.byId.get(id);
        if (artifact !== undefined)
          this.byId.set(artifact.id, { ...artifact, status: status.trim() });
      }
      if (source.includes('REQ-') && parsedRows === 0) throw new Error('ProjectionFormatError');
      this.diagnostics.splice(
        0,
        this.diagnostics.length,
        ...this.diagnostics.filter((item) => item.category !== 'ProjectionReadError'),
      );
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT')
        this.diagnostics.push(diagnostic('ProjectionReadError', MESSAGES.projectionError));
    }
  }

  private collectReferences(root: string, paths: ConfiguredPaths): ArtifactReference[] {
    const directories = ['.'];
    const references: ArtifactReference[] = [];
    const seen = new Set<string>();
    for (const directory of directories) {
      let files: string[];
      try {
        files = markdownFiles(root, directory, {
          // F-015: раньше единственный catch{continue} вокруг всего
          // markdownFiles-вызова означал, что одна недоступная поддиректория
          // где угодно под root обнуляла весь Reference Index без единого
          // diagnostic. Теперь поддерево изолируется внутри markdownFiles, а
          // здесь только сообщается диагностика; остальные references
          // по-прежнему собираются.
          onSubtreeError: (logicalPath) => {
            this.diagnostics.push(
              diagnostic('ArtifactDirectoryMissing', MESSAGES.directoryMissing, logicalPath),
            );
          },
        });
      } catch {
        this.diagnostics.push(
          diagnostic('ArtifactDirectoryMissing', MESSAGES.directoryMissing, directory),
        );
        continue;
      }
      for (const file of files.filter((item) => isHarnessAwareMarkdown(root, item, paths))) {
        if (seen.has(file)) continue;
        seen.add(file);
        references.push(...this.referencesForFile(root, paths, file));
      }
    }
    for (const relative of [
      paths.projectOverview,
      paths.architecture,
      paths.openQuestionsIndex,
      paths.roadmap,
      paths.status,
    ]) {
      const file = path.resolve(root, relative);
      if (!isHarnessAwareMarkdown(root, file, paths)) continue;
      if (!seen.has(file)) references.push(...this.referencesForFile(root, paths, file));
    }
    return references;
  }

  private referencesForFile(
    root: string,
    paths: ConfiguredPaths,
    file: string,
  ): ArtifactReference[] {
    if (!isHarnessAwareMarkdown(root, file, paths)) return [];
    try {
      const source = readContainedMarkdown(root, file);
      return [...source.matchAll(/\b(?:STEP|REQ|ADR|OQ)-\d+\b/gu)].map((match) => ({
        file,
        offset: match.index,
        length: match[0].length,
        targetId: match[0],
      }));
    } catch {
      // Удалённый или malformed reference-файл не отменяет остальные индексы.
      return [];
    }
  }
}

/**
 * Единственная точка, к которой сходятся все три обработчика (create/change/
 * delete) artifact `FileSystemWatcher` в `ProjectStateService`. Вынесена в
 * этот модуль (не зависящий от `vscode`) отдельной экспортируемой функцией,
 * чтобы связку "watcher event → инкрементальный `ArtifactIndex.updatePath`"
 * можно было проверить unit-тестом детерминированно, без реального Extension
 * Host и без зависимости от таймингов real filesystem watcher (F-021):
 * регрессия, которая заменит или уберёт вызов `updatePath` здесь (например,
 * на полный `rebuild`, либо вовсе уберёт delegation), ловится этим тестом
 * независимо от того, успел ли watcher в конкретном интеграционном прогоне
 * сработать быстрее watcher-only окна — end-to-end сценарий больше не
 * является единственным, что может обнаружить такую регрессию.
 */
export function handleArtifactWatcherEvent(
  index: ArtifactIndex,
  project: ValidProjectState,
  changedFsPath: string,
): void {
  index.updatePath(project, changedFsPath);
}
