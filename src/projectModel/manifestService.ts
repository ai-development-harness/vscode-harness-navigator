import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
} from 'node:fs';
import path from 'node:path';
import { load } from 'js-yaml';
import type { ConfiguredPaths, ProjectDiagnostic, ProjectState } from './projectState';

const MINIMUM_RELEASE = '0.6.0';
const SUPPORTED_MANIFEST_VERSION = '1';
// Manifest является недоверенным входом workspace. 64 KiB достаточно для его
// declarative configuration и ограничивает память/время до запуска YAML parser.
export const MAXIMUM_MANIFEST_SIZE_BYTES = 64 * 1024;

// Единственный источник production diagnostic message этого слоя. Любой новый
// `diagnostic(...)`/`ManifestInputError` с незарегистрированным литералом не
// компилируется (см. `DiagnosticMessage` ниже) — это устраняет класс дефекта
// F-010 (пропущенный ключ в l10n bundle) структурно, а не тестовой дисциплиной.
export const DIAGNOSTIC_MESSAGES = {
  manifestAbsent: 'Harness manifest is absent.',
  manifestUnreadable: 'Harness manifest cannot be read.',
  manifestOutsideRoot: 'Manifest resolves outside of the workspace root.',
  manifestNotObject: 'Harness manifest must contain an object.',
  manifestNotRegularFile: 'Harness manifest must be a regular file.',
  manifestExceedsSize: 'Harness manifest exceeds {0} bytes.',
  manifestUnparsable: 'Harness manifest cannot be parsed.',
  missingRequiredField: 'Harness manifest is missing a required field: {0}.',
  unsupportedSchema: 'Harness manifest schema is not supported: {0}.',
  invalidRelease: 'Harness manifest contains an invalid release: {0}.',
  unsupportedRelease: 'Harness release is not supported: {0}.',
  configuredPathBlocked: 'A configured path is blocked by workspace containment.',
  manifestValid: 'Harness manifest is valid.',
} as const;
export type DiagnosticMessage = (typeof DIAGNOSTIC_MESSAGES)[keyof typeof DIAGNOSTIC_MESSAGES];
export const PRODUCTION_DIAGNOSTIC_MESSAGES: readonly DiagnosticMessage[] =
  Object.values(DIAGNOSTIC_MESSAGES);

interface RawManifest {
  readonly harness?: { readonly release?: unknown; readonly version?: unknown };
  readonly protocol?: { readonly taskDirectory?: unknown };
  readonly sources?: Record<string, unknown>;
}

/**
 * Platform capability для чтения manifest, наблюдаемая и инъецируемая целиком
 * (не подразумеваемая из `process.platform`/`constants.*` в разных местах).
 * По `docs/adr/ADR-005-platform-scoped-manifest-containment.md`:
 * - `noFollowFlag`/`nonBlockFlag` — реально доступные open-флаги на этой
 *   platform (POSIX-константы, которых `node:fs` не определяет на `win32`).
 * - `deriveOpenedPath` — canonical-path re-derivation уже открытого
 *   descriptor (`/proc/self/fd/<fd>`), доступная только на Linux; на любой
 *   другой platform (включая `darwin`) — `undefined`, поскольку portable
 *   эквивалента без native addon не существует.
 */
export interface ManifestOpenCapability {
  readonly noFollowFlag: number | undefined;
  readonly nonBlockFlag: number | undefined;
  readonly deriveOpenedPath: ((descriptor: number) => string) | undefined;
}

/**
 * Чистая функция: только параметры, без обращения к реальным `process`/`fs`.
 * Это позволяет unit-тестам сконструировать capability для любого сценария,
 * включая профиль, буквально соответствующий Windows (`{}`).
 */
export function resolveManifestOpenCapability(
  platform: NodeJS.Platform,
  posixConstants: { readonly O_NOFOLLOW?: number; readonly O_NONBLOCK?: number },
): ManifestOpenCapability {
  return {
    noFollowFlag: posixConstants.O_NOFOLLOW,
    nonBlockFlag: posixConstants.O_NONBLOCK,
    deriveOpenedPath:
      platform === 'linux'
        ? (descriptor: number) => realpathSync(`/proc/self/fd/${descriptor}`)
        : undefined,
  };
}

/**
 * Узкий тестовый барьер воспроизводит замену path именно после исходной
 * containment-проверки. В production он не передаётся и не добавляет I/O.
 * `capability` — опциональная инъекция всей platform capability целиком, для
 * детерминированной проверки каждого profile без реального non-Linux
 * раннера; в production не передаётся, и точка входа реального
 * `process.platform`/`constants` остаётся только в `detectProject`.
 */
export interface ManifestReadHooks {
  readonly beforeOpen?: () => void;
  readonly capability?: ManifestOpenCapability;
}

/**
 * Читает только `.harness/manifest.yaml` конкретного workspace root и
 * преобразует недоверенное содержимое в типизированное read-only состояние.
 * Этот слой не знает о parsing артефактов и не предоставляет операций записи.
 */
export function detectProject(workspaceRoot: string, hooks: ManifestReadHooks = {}): ProjectState {
  const manifestPath = path.join(workspaceRoot, '.harness', 'manifest.yaml');
  try {
    lstatSync(manifestPath);
  } catch (error) {
    if (isMissingPath(error)) {
      return state(
        workspaceRoot,
        'nonHarness',
        diagnostic('NotHarnessProject', DIAGNOSTIC_MESSAGES.manifestAbsent),
      );
    }
    return state(
      workspaceRoot,
      'configurationBlocked',
      diagnostic(
        'UnexpectedInternalError',
        DIAGNOSTIC_MESSAGES.manifestUnreadable,
        [],
        safeErrorDetail(error),
      ),
    );
  }

  try {
    const realRoot = realpathSync(workspaceRoot);
    const realManifest = realpathSync(manifestPath);
    if (!isContained(realRoot, realManifest)) {
      return state(
        workspaceRoot,
        'configurationBlocked',
        diagnostic('ConfigurationBlocked', DIAGNOSTIC_MESSAGES.manifestOutsideRoot),
      );
    }
    assertRegularManifest(realManifest);

    // Единственная точка входа реального (не тестового) platform/constants
    // значения в этот слой — `hooks.capability` существует только для
    // детерминированной unit-инъекции profile (ADR-005).
    const capability =
      hooks.capability ?? resolveManifestOpenCapability(process.platform, constants);
    const parsed = load(readBoundedManifest(realManifest, realRoot, capability, hooks.beforeOpen));
    if (!isObject(parsed)) {
      return state(
        workspaceRoot,
        'invalidManifest',
        diagnostic('InvalidManifest', DIAGNOSTIC_MESSAGES.manifestNotObject),
      );
    }

    return validateManifest(workspaceRoot, realRoot, parsed);
  } catch (error) {
    if (error instanceof ManifestContainmentError || isNoFollowViolation(error)) {
      return state(
        workspaceRoot,
        'configurationBlocked',
        diagnostic('ConfigurationBlocked', DIAGNOSTIC_MESSAGES.manifestOutsideRoot),
      );
    }
    if (error instanceof ManifestInputError) {
      return state(
        workspaceRoot,
        'invalidManifest',
        diagnostic('InvalidManifest', error.diagnosticMessage, error.messageArguments),
      );
    }
    if (error instanceof Error && error.name === 'YAMLException') {
      return state(
        workspaceRoot,
        'invalidManifest',
        diagnostic(
          'InvalidManifest',
          DIAGNOSTIC_MESSAGES.manifestUnparsable,
          [],
          safeErrorDetail(error),
        ),
      );
    }
    return state(
      workspaceRoot,
      'configurationBlocked',
      diagnostic(
        'UnexpectedInternalError',
        DIAGNOSTIC_MESSAGES.manifestUnreadable,
        [],
        safeErrorDetail(error),
      ),
    );
  }
}

function validateManifest(
  workspaceRoot: string,
  realRoot: string,
  manifest: RawManifest,
): ProjectState {
  const version = manifest.harness?.version;
  if (typeof version !== 'string') {
    return state(
      workspaceRoot,
      'invalidManifest',
      diagnostic('InvalidManifest', DIAGNOSTIC_MESSAGES.missingRequiredField, ['harness.version']),
    );
  }
  if (version !== SUPPORTED_MANIFEST_VERSION) {
    return {
      ...state(
        workspaceRoot,
        'unsupportedSchema',
        diagnostic('UnsupportedSchema', DIAGNOSTIC_MESSAGES.unsupportedSchema, [version]),
      ),
      detectedSchema: version,
    };
  }

  const release = manifest.harness?.release;
  if (typeof release !== 'string') {
    return state(
      workspaceRoot,
      'invalidManifest',
      diagnostic('InvalidManifest', DIAGNOSTIC_MESSAGES.missingRequiredField, ['harness.release']),
    );
  }
  const parsedRelease = parseRelease(release);
  if (parsedRelease === undefined) {
    return state(
      workspaceRoot,
      'invalidManifest',
      diagnostic('InvalidManifest', DIAGNOSTIC_MESSAGES.invalidRelease, [release]),
    );
  }
  if (!isReleaseAtLeast(parsedRelease, MINIMUM_RELEASE)) {
    return {
      ...state(
        workspaceRoot,
        'unsupportedVersion',
        diagnostic('UnsupportedHarnessVersion', DIAGNOSTIC_MESSAGES.unsupportedRelease, [release]),
      ),
      detectedRelease: release,
      minimumRelease: MINIMUM_RELEASE,
    };
  }

  const rawPaths: Record<keyof ConfiguredPaths, unknown> = {
    taskDirectory: manifest.protocol?.taskDirectory,
    projectOverview: manifest.sources?.projectOverview,
    requirements: manifest.sources?.requirements,
    adrDirectory: manifest.sources?.adrDirectory,
    architecture: manifest.sources?.architecture,
    openQuestions: manifest.sources?.openQuestions,
    openQuestionsIndex: manifest.sources?.openQuestionsIndex,
    roadmap: manifest.sources?.roadmap,
    status: manifest.sources?.status,
  };
  const configuredPaths = {} as Record<keyof ConfiguredPaths, string>;

  for (const [name, configuredPath] of Object.entries(rawPaths) as [
    keyof ConfiguredPaths,
    unknown,
  ][]) {
    if (typeof configuredPath !== 'string' || configuredPath.length === 0) {
      return state(
        workspaceRoot,
        'invalidManifest',
        diagnostic('InvalidManifest', DIAGNOSTIC_MESSAGES.missingRequiredField, [name]),
      );
    }
    const resolution = resolveContainedPath(realRoot, configuredPath);
    if (resolution !== undefined) {
      return state(
        workspaceRoot,
        'configurationBlocked',
        diagnostic(
          'ConfigurationBlocked',
          DIAGNOSTIC_MESSAGES.configuredPathBlocked,
          [],
          `${name}: ${resolution}`,
        ),
      );
    }
    configuredPaths[name] = configuredPath;
  }

  return {
    kind: 'valid',
    workspaceRoot,
    release,
    configuredPaths,
    diagnostic: diagnostic('ValidHarnessProject', DIAGNOSTIC_MESSAGES.manifestValid),
  };
}

/**
 * Проверяет путь до его чтения: абсолютные пути и syntactic traversal не
 * допускаются, а существующий symlink проверяется через realpath. Для
 * отсутствующего будущего каталога разрешается только contained ancestor.
 */
function resolveContainedPath(realRoot: string, configuredPath: string): string | undefined {
  if (path.isAbsolute(configuredPath)) {
    return 'Absolute paths are not allowed.';
  }
  if (configuredPath.split(/[\\/]+/u).includes('..')) {
    return 'Traversal paths are not allowed.';
  }

  const candidate = path.resolve(realRoot, configuredPath);
  if (!isContained(realRoot, candidate)) {
    return 'Path resolves outside of the workspace root.';
  }

  let existingAncestor = candidate;
  while (true) {
    try {
      lstatSync(existingAncestor);
      break;
    } catch (error) {
      if (!isMissingPath(error)) {
        return safeErrorDetail(error);
      }
    }

    const parent = path.dirname(existingAncestor);
    if (parent === existingAncestor || !isContained(realRoot, parent)) {
      return 'Path does not have a contained existing ancestor.';
    }
    existingAncestor = parent;
  }

  try {
    // `lstatSync` выше намеренно считает dangling symlink существующим. Тогда
    // `realpathSync` ниже fail-closed отклоняет его вместо обхода до parent,
    // который позволил бы отложенное чтение external target (F-012).
    if (!isContained(realRoot, realpathSync(existingAncestor))) {
      return 'Path resolves outside of the workspace root.';
    }
  } catch (error) {
    return safeErrorDetail(error);
  }
  return undefined;
}

function state<TKind extends Exclude<ProjectState['kind'], 'valid'>>(
  workspaceRoot: string,
  kind: TKind,
  diagnosticValue: ProjectDiagnostic,
): Extract<ProjectState, { kind: TKind }> {
  return { workspaceRoot, kind, diagnostic: diagnosticValue } as Extract<
    ProjectState,
    { kind: TKind }
  >;
}

function diagnostic(
  category: ProjectDiagnostic['category'],
  message: DiagnosticMessage,
  messageArguments: readonly (string | number)[] = [],
  detail = '',
): ProjectDiagnostic {
  return { category, message, messageArguments, detail };
}

function isContained(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative === '' ||
    (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
  );
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

interface SemanticVersion {
  readonly major: number;
  readonly minor: number;
  readonly patch: number;
  readonly prerelease: readonly string[];
}

function isReleaseAtLeast(actualVersion: SemanticVersion, minimum: string): boolean {
  const minimumVersion = parseRelease(minimum);
  if (minimumVersion === undefined) {
    return false;
  }
  for (const [actualPart, minimumPart] of [
    [actualVersion.major, minimumVersion.major],
    [actualVersion.minor, minimumVersion.minor],
    [actualVersion.patch, minimumVersion.patch],
  ] as const) {
    if (actualPart !== minimumPart) {
      return actualPart > minimumPart;
    }
  }
  return comparePrerelease(actualVersion.prerelease, minimumVersion.prerelease) >= 0;
}

function parseRelease(release: string): SemanticVersion | undefined {
  const match =
    /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/u.exec(
      release,
    );
  if (match === null) {
    return undefined;
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4]?.split('.') ?? [],
  };
}

function comparePrerelease(actual: readonly string[], minimum: readonly string[]): number {
  if (actual.length === 0 || minimum.length === 0) {
    return actual.length === minimum.length ? 0 : actual.length === 0 ? 1 : -1;
  }
  for (let index = 0; index < Math.max(actual.length, minimum.length); index += 1) {
    const actualIdentifier = actual[index];
    const minimumIdentifier = minimum[index];
    if (actualIdentifier === undefined || minimumIdentifier === undefined) {
      return actualIdentifier === undefined ? -1 : 1;
    }
    if (actualIdentifier === minimumIdentifier) {
      continue;
    }
    const actualNumeric = /^\d+$/u.test(actualIdentifier);
    const minimumNumeric = /^\d+$/u.test(minimumIdentifier);
    if (actualNumeric && minimumNumeric) {
      return Number(actualIdentifier) > Number(minimumIdentifier) ? 1 : -1;
    }
    if (actualNumeric !== minimumNumeric) {
      return actualNumeric ? -1 : 1;
    }
    return actualIdentifier > minimumIdentifier ? 1 : -1;
  }
  return 0;
}

class ManifestInputError extends Error {
  constructor(
    readonly diagnosticMessage: DiagnosticMessage,
    readonly messageArguments: readonly (string | number)[] = [],
  ) {
    super(diagnosticMessage);
  }
}

class ManifestContainmentError extends Error {}

function assertRegularManifest(manifestPath: string): void {
  if (!lstatSync(manifestPath).isFile()) {
    throw new ManifestInputError(DIAGNOSTIC_MESSAGES.manifestNotRegularFile);
  }
}

/**
 * Собирает open-флаги только из тех, что реально доступны в этой capability —
 * без `flag | undefined`, который в JS беззвучно даёт `flag | 0`.
 */
function composeOpenFlags(capability: ManifestOpenCapability): number {
  let flags: number = constants.O_RDONLY;
  if (capability.nonBlockFlag !== undefined) {
    flags |= capability.nonBlockFlag;
  }
  if (capability.noFollowFlag !== undefined) {
    flags |= capability.noFollowFlag;
  }
  return flags;
}

function readBoundedManifest(
  manifestPath: string,
  realRoot: string,
  capability: ManifestOpenCapability,
  beforeOpen: (() => void) | undefined,
): string {
  beforeOpen?.();

  // O_NOFOLLOW (когда доступен) не позволяет подменить последний path
  // component symlink-ом между realpath и open. После открытия проверяем
  // именно descriptor: это связывает containment с объектом, чьё содержимое
  // будет передано YAML parser-у, независимо от того, доступен ли O_NOFOLLOW
  // на этой platform.
  const descriptor = openSync(manifestPath, composeOpenFlags(capability));
  try {
    const manifestStats = fstatSync(descriptor);
    if (!manifestStats.isFile()) {
      throw new ManifestInputError(DIAGNOSTIC_MESSAGES.manifestNotRegularFile);
    }
    assertOpenedManifestContained(
      descriptor,
      manifestPath,
      realRoot,
      manifestStats.dev,
      manifestStats.ino,
      capability,
    );
    const size = manifestStats.size;
    if (!Number.isSafeInteger(size) || size < 0 || size > MAXIMUM_MANIFEST_SIZE_BYTES) {
      throw new ManifestInputError(DIAGNOSTIC_MESSAGES.manifestExceedsSize, [
        MAXIMUM_MANIFEST_SIZE_BYTES,
      ]);
    }
    const buffer = Buffer.alloc(size);
    const bytesRead = readSync(descriptor, buffer, 0, size, 0);
    if (bytesRead !== size) {
      throw new Error('The manifest changed while it was being read.');
    }
    return buffer.toString('utf8');
  } finally {
    closeSync(descriptor);
  }
}

/**
 * Портируемая (все platform) identity-проверка открытого descriptor через
 * `dev`/`ino` против текущего `lstat` того же path — это единственная часть,
 * закрывающая подмену финального path component (F-008 symlink-swap regression),
 * и она не зависит от `capability.deriveOpenedPath`.
 *
 * Если `capability.deriveOpenedPath` доступна (только Linux сегодня),
 * дополнительно требуем containment canonical path уже открытого descriptor —
 * это ловит гонку с подменой промежуточного ancestor directory между
 * containment check и open. На platform без этой re-derivation (macOS,
 * Windows) отсутствие такой проверки — осознанно принятый остаточный риск по
 * `docs/adr/ADR-005-platform-scoped-manifest-containment.md`, а не пропущенная
 * проверка.
 */
function assertOpenedManifestContained(
  descriptor: number,
  manifestPath: string,
  realRoot: string,
  device: number,
  inode: number,
  capability: ManifestOpenCapability,
): void {
  const currentPathStats = lstatSync(manifestPath);
  if (
    !currentPathStats.isFile() ||
    currentPathStats.dev !== device ||
    currentPathStats.ino !== inode
  ) {
    throw new ManifestContainmentError('Opened manifest identity is not contained.');
  }
  if (capability.deriveOpenedPath !== undefined) {
    const descriptorPath = capability.deriveOpenedPath(descriptor);
    if (!isContained(realRoot, descriptorPath)) {
      throw new ManifestContainmentError('Opened manifest identity is not contained.');
    }
  }
}

function safeErrorDetail(error: unknown): string {
  return error instanceof Error ? error.name : 'UnknownError';
}

function isMissingPath(error: unknown): boolean {
  return (error as NodeJS.ErrnoException).code === 'ENOENT';
}

function isNoFollowViolation(error: unknown): boolean {
  // Linux возвращает ELOOP, когда O_NOFOLLOW встречает подменённый symlink.
  // Это ожидаемое containment-отклонение, а не внутренний сбой Extension Host.
  return (error as NodeJS.ErrnoException).code === 'ELOOP';
}
