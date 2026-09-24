// Чистые правила inspection VSIX: entries + extension/package.json +
// extension/dist/extension.js -> список violations. Без I/O и без сети.

import { crc32 } from './iconEncoder';

export const ALLOWED_ENTRIES: readonly string[] = [
  'extension.vsixmanifest',
  '[Content_Types].xml',
  'extension/package.json',
  'extension/package.nls.json',
  'extension/package.nls.ru.json',
  'extension/l10n/bundle.l10n.json',
  'extension/l10n/bundle.l10n.ru.json',
  'extension/dist/extension.js',
  'extension/readme.md',
  'extension/LICENSE.txt',
  'extension/resources/icon.png',
];

export const ICON_MANIFEST_PATH = 'resources/icon.png';
export const MINIMUM_ICON_SIDE = 128;
export const MAXIMUM_ICON_SIDE = 1024;
export const MAXIMUM_ICON_BYTES = 200 * 1024;

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const FORBIDDEN_PNG_CHUNKS: ReadonlySet<string> = new Set(['tEXt', 'iTXt', 'zTXt']);

export const MAXIMUM_ARCHIVE_BYTES = 2 * 1024 * 1024;

const FORBIDDEN_ENTRY_PATTERNS: readonly [RegExp, string][] = [
  [/(^|\/)src\//u, 'src/'],
  [/(^|\/)tests?\//u, 'tests/'],
  [/(^|\/)out\//u, 'out/'],
  [/(^|\/)node_modules\//u, 'node_modules/'],
  [/(^|\/)\.harness\//u, '.harness/'],
  [/(^|\/)planning\//u, 'planning/'],
  [/(^|\/)docs\//u, 'docs/'],
  [/(^|\/)\.vscode[^/]*(\/|$)/u, '.vscode*'],
  [/(^|\/)\.env[^/]*$/u, '.env*'],
  [/\.map$/u, '*.map'],
  [/\.ts$/u, '*.ts'],
  [/\.(svg|gif|jpe?g|ico|webp|bmp|avif)$/iu, 'image other than the icon'],
  [/\.vsix$/u, '*.vsix'],
  [/(^|\/)(AGENTS|CLAUDE|PROJECT_BRIEF)[^/]*$/u, 'AGENTS*/CLAUDE*/PROJECT_BRIEF*'],
  [/\.(pem|key|p12|pfx|crt|cer)$/u, 'key or certificate'],
  [/(^|\/)id_(rsa|dsa|ecdsa|ed25519)/u, 'ssh key'],
];

const ALLOWED_REQUIRES: ReadonlySet<string> = new Set(['vscode', 'node:fs', 'node:path']);

const FORBIDDEN_BUNDLE_MODULES = [
  'child_process',
  'http',
  'https',
  'http2',
  'net',
  'tls',
  'dgram',
  'dns',
  'worker_threads',
  'cluster',
  'inspector',
];

const FORBIDDEN_BUNDLE_TOKENS: readonly [RegExp, string][] = [
  [/\bcreateTerminal\b/u, 'createTerminal'],
  [/\bexecuteTask\b/u, 'executeTask'],
  [/\bcreateWebviewPanel\b/u, 'createWebviewPanel'],
  [/\bregisterWebviewViewProvider\b/u, 'registerWebviewViewProvider'],
  [/\bfetch\(/u, 'fetch('],
  [/\bXMLHttpRequest\b/u, 'XMLHttpRequest'],
  [/\bWebSocket\b/u, 'WebSocket'],
  [/\bauthentication\.getSession\b/u, 'authentication.getSession'],
  [/\bapplyEdit\b/u, 'applyEdit'],
  [/\bcreateTelemetryLogger\b|\btelemetry\b/iu, 'telemetry logger'],
  [/\bsourceMappingURL\b/u, 'sourceMappingURL'],
  [/\bsourcesContent\b/u, 'sourcesContent'],
  [
    /\b(writeFile(Sync)?|appendFile(Sync)?|createWriteStream|rmSync|rmdirSync|unlinkSync|mkdirSync|renameSync|copyFileSync|truncateSync|symlinkSync|chmodSync)\b/u,
    'fs write API',
  ],
  [/\bworkspace\.fs\b/u, 'workspace.fs'],
  [
    /\.(rm|unlink|mkdir|rename|copyFile|cp|symlink|link|chmod|chown|truncate|utimes|rmdir)\(/u,
    'async fs write API',
  ],
  [/\.promises\b/u, 'fs promises'],
  [/\bopenExternal\b/u, 'openExternal'],
  [/\bsaveAll\b/u, 'saveAll'],
  [/\.save\(/u, '.save('],
  [/\.edit\(/u, '.edit('],
  [/\bmodule\.require\b/u, 'module.require'],
  // Деструктуризация и bracket-доступ к workspace обходят токен workspace.fs.
  [/\bcreateDirectory\b/u, 'createDirectory'],
  [/\.copy\(/u, '.copy('],
  [/\}=[\w$]+\.workspace\b/u, 'destructuring from workspace'],
  [/\.workspace\[/u, 'workspace[...] access'],
  // Открытие файла на запись/создание/усечение.
  [/\bO_(WRONLY|RDWR|CREAT|TRUNC|APPEND)\b/u, 'fs write open flag'],
  [/\bopenSync\([^,()]+,\s*["'`]/u, 'openSync with string flags'],
  [/\bprocess\.(binding|dlopen)\b|\bcreateRequire\b/u, 'process.binding/dlopen/createRequire'],
  [/\brequire\(\s*["'][^"']*["']\s*\+/u, 'concatenated require'],
];

const ALLOWED_COMMAND_IDS: readonly RegExp[] = [
  /^vscode\.open$/u,
  /^editor\.action\.peekLocations$/u,
  /^harnessNavigator\./u,
  /^workbench\.view\.extension\.harnessNavigator$/u,
];

const SECRET_PATTERNS: readonly [RegExp, string][] = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/u, 'PRIVATE KEY block'],
  [/\bghp_[A-Za-z0-9]{20,}/u, 'ghp_ token'],
  [/\bgithub_pat_[A-Za-z0-9_]{20,}/u, 'github_pat_ token'],
  [/\bAKIA[0-9A-Z]{16}\b/u, 'AKIA access key'],
];

export interface PackageInspectionInput {
  readonly entryNames: readonly string[];
  readonly archiveBytes: number;
  /** Разобранный extension/package.json. */
  readonly packageJson: unknown;
  /** Текст extension/dist/extension.js. */
  readonly bundle: string;
  /** Все прочие текстовые entries (для secret heuristics), имя -> текст. */
  readonly textEntries: ReadonlyMap<string, string>;
  /** Бинарные entries (PNG), имя -> байты; не декодируются как текст. */
  readonly binaryEntries: ReadonlyMap<string, Uint8Array>;
}

/** Разбор только заголовка и списка чанков PNG; пиксели не декодируются. */
function inspectIcon(data: Uint8Array | undefined, manifest: Record<string, unknown>): string[] {
  const violations: string[] = [];
  if (manifest['icon'] !== ICON_MANIFEST_PATH)
    violations.push(`manifest icon must be ${ICON_MANIFEST_PATH}`);
  if (data === undefined) return [...violations, 'icon entry is missing or not read'];
  if (data.length > MAXIMUM_ICON_BYTES) violations.push(`icon is too large: ${data.length} bytes`);
  if (data.length < 8 || PNG_SIGNATURE.some((byte, index) => data[index] !== byte))
    return [...violations, 'icon is not a PNG (bad signature)'];
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  let offset = 8;
  let index = 0;
  let ended = false;
  let idatCount = 0;
  while (offset + 12 <= data.length) {
    const length = view.getUint32(offset);
    const type = String.fromCharCode(...data.subarray(offset + 4, offset + 8));
    if (offset + 12 + length > data.length) {
      violations.push('icon PNG chunk is truncated');
      break;
    }
    if (index === 0) {
      if (type !== 'IHDR' || length !== 13) {
        violations.push('icon PNG must start with a 13-byte IHDR chunk');
        break;
      }
      const width = view.getUint32(offset + 8);
      const height = view.getUint32(offset + 12);
      if (width !== height) violations.push(`icon must be square: ${width}x${height}`);
      for (const side of [width, height])
        if (side < MINIMUM_ICON_SIDE || side > MAXIMUM_ICON_SIDE) {
          violations.push(
            `icon side must be ${MINIMUM_ICON_SIDE}..${MAXIMUM_ICON_SIDE}: ${width}x${height}`,
          );
          break;
        }
    }
    if (FORBIDDEN_PNG_CHUNKS.has(type)) violations.push(`icon PNG contains a ${type} chunk`);
    if (type === 'IDAT') idatCount++;
    const expectedCrc = view.getUint32(offset + 8 + length);
    if (crc32(data.subarray(offset + 4, offset + 8 + length)) !== expectedCrc)
      violations.push(`icon PNG chunk ${type} has a bad CRC`);
    offset += 12 + length;
    index++;
    if (type === 'IEND') {
      ended = true;
      break;
    }
  }
  if (!ended) violations.push('icon PNG has no IEND chunk');
  else {
    if (offset !== data.length)
      violations.push(`icon PNG has ${data.length - offset} trailing bytes after IEND`);
    if (idatCount === 0) violations.push('icon PNG has no IDAT chunk');
  }
  return violations;
}

function inspectGalleryBanner(value: unknown): string[] {
  if (value === undefined) return [];
  if (!isRecord(value)) return ['manifest galleryBanner must be an object'];
  const violations: string[] = [];
  if (typeof value['color'] !== 'string' || !/^#[0-9A-Fa-f]{6}$/u.test(value['color']))
    violations.push('manifest galleryBanner.color must be #RRGGBB');
  if (value['theme'] !== 'light' && value['theme'] !== 'dark')
    violations.push('manifest galleryBanner.theme must be light or dark');
  return violations;
}

const README_ENTRY = 'extension/readme.md';

const PRIVATE_PATH = String.raw`(?:docs|planning|\.harness)`;
const URL_SCHEME = /^[a-z][a-z0-9+.-]*:/iu;

function isRelativeTarget(target: string): boolean {
  const value = target.trim().replace(/^<|>$/gu, '');
  return (
    value !== '' && !URL_SCHEME.test(value) && !value.startsWith('#') && !value.startsWith('//')
  );
}

/** Правила README: применяются и к тексту из архива, и к исходнику docs/marketplace/README.md. */
export function inspectReadmeText(text: string): string[] {
  const violations: string[] = [];
  if (/PROJECT:(START|END)/u.test(text)) violations.push('readme contains a Harness-managed block');
  const privateLink = new RegExp(`\\]\\(\\s*<?(?:\\.{1,2}/|/)*(${PRIVATE_PATH})/`, 'u').exec(text);
  if (privateLink !== null) violations.push(`readme links to a private path: ${privateLink[1]}/`);
  // vsce переписывает относительные ссылки в https://github.com/.../blob/HEAD/<путь>.
  const rewritten = new RegExp(`/blob/HEAD/(${PRIVATE_PATH})/`, 'u').exec(text);
  if (rewritten !== null)
    violations.push(`readme links to a private path (rewritten by vsce): ${rewritten[1]}/`);
  for (const match of text.matchAll(/\]\(\s*([^)\s]*)/gu))
    if (isRelativeTarget(match[1] ?? ''))
      violations.push(`readme has a relative link: ${match[1]}`);
  for (const match of text.matchAll(/\b(?:src|href)\s*=\s*["']?\s*([^"'\s>]*)/giu))
    if (isRelativeTarget(match[1] ?? ''))
      violations.push(`readme has a relative HTML src/href: ${match[1]}`);
  for (const match of text.matchAll(/^ {0,3}\[[^\]\n]+\]:\s*(\S+)/gmu))
    if (isRelativeTarget(match[1] ?? ''))
      violations.push(`readme has a relative reference-style link: ${match[1]}`);
  if (/(^|[^\w&/#])#\d+\b/u.test(text))
    violations.push('readme contains a #<number> issue reference');
  return violations;
}

function inspectReadme(text: string | undefined): string[] {
  return text === undefined ? [] : inspectReadmeText(text);
}

export interface ReadmeComparison {
  readonly status: 'equal' | 'differs' | 'source-missing' | 'packaged-missing';
  readonly message: string;
}

/** Сравнение README из архива с исходником; отсутствие источника не скрывается. */
export function compareReadmeWithSource(
  packaged: string | undefined,
  source: string | undefined,
): ReadmeComparison {
  if (packaged === undefined)
    return { status: 'packaged-missing', message: 'extension/readme.md is missing in the archive' };
  if (source === undefined)
    return {
      status: 'source-missing',
      message: 'readme comparison skipped: docs/marketplace/README.md not found',
    };
  return packaged === source
    ? { status: 'equal', message: 'extension/readme.md equals docs/marketplace/README.md' }
    : { status: 'differs', message: 'extension/readme.md differs from docs/marketplace/README.md' };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Возвращает список нарушений; пустой список означает PASS. */
export function inspectPackage(input: PackageInspectionInput): string[] {
  const violations: string[] = [];
  const names = input.entryNames.filter((name) => !name.endsWith('/'));

  for (const name of names) {
    for (const [pattern, label] of FORBIDDEN_ENTRY_PATTERNS)
      if (pattern.test(name)) violations.push(`forbidden entry (${label}): ${name}`);
    if (!ALLOWED_ENTRIES.includes(name)) violations.push(`entry outside the allowlist: ${name}`);
    if (/\.png$/iu.test(name) && name !== 'extension/resources/icon.png')
      violations.push(`forbidden entry (png other than the icon): ${name}`);
  }
  for (const required of ALLOWED_ENTRIES)
    if (!names.includes(required)) violations.push(`required entry is missing: ${required}`);
  if (input.archiveBytes > MAXIMUM_ARCHIVE_BYTES)
    violations.push(`archive is too large: ${input.archiveBytes} bytes`);

  const manifest = isRecord(input.packageJson) ? input.packageJson : {};
  if (manifest['main'] !== './dist/extension.js')
    violations.push('manifest main must be ./dist/extension.js');
  if (manifest['l10n'] !== './l10n') violations.push('manifest l10n must be ./l10n');
  for (const key of ['enabledApiProposals', 'extensionDependencies', 'extensionPack'])
    if (manifest[key] !== undefined) violations.push(`manifest must not declare ${key}`);
  violations.push(
    ...inspectIcon(input.binaryEntries.get('extension/resources/icon.png'), manifest),
    ...inspectGalleryBanner(manifest['galleryBanner']),
    ...inspectReadme(input.textEntries.get(README_ENTRY)),
  );
  const contributes = isRecord(manifest['contributes']) ? manifest['contributes'] : {};
  for (const key of [
    'authentication',
    'taskDefinitions',
    'terminal',
    'terminalProfiles',
    'problemMatchers',
  ])
    if (contributes[key] !== undefined) violations.push(`manifest must not contribute ${key}`);

  for (const match of input.bundle.matchAll(/\brequire\(\s*["']([^"']+)["']\s*\)/gu)) {
    const target = match[1] ?? '';
    if (!ALLOWED_REQUIRES.has(target))
      violations.push(`bundle requires a forbidden module: ${target}`);
  }
  // Любой require(...), первый аргумент которого не строковый литерал в
  // кавычках (backtick, переменная, выражение), недопустим.
  if (/\brequire\(\s*[^"'\s)]/u.test(input.bundle))
    violations.push('bundle contains a non-literal require(');
  for (const module of FORBIDDEN_BUNDLE_MODULES)
    if (new RegExp(`["'](node:)?${module}["']`, 'u').test(input.bundle))
      violations.push(`bundle references forbidden module: ${module}`);
  for (const [pattern, label] of FORBIDDEN_BUNDLE_TOKENS)
    if (pattern.test(input.bundle)) violations.push(`bundle contains forbidden token: ${label}`);

  // executeCommand разрешён только для внутренних команд и навигации UI (literal id из allowlist).
  for (const match of input.bundle.matchAll(/\bexecuteCommand\(\s*([^,)]*)/gu)) {
    const raw = (match[1] ?? '').trim();
    const literal = /^["']([^"']+)["']$/u.exec(raw)?.[1];
    if (literal === undefined) violations.push(`bundle calls executeCommand with a non-literal id`);
    else if (!ALLOWED_COMMAND_IDS.some((allowed) => allowed.test(literal)))
      violations.push(`bundle calls executeCommand with a forbidden id: ${literal}`);
  }

  const texts = new Map(input.textEntries);
  texts.set('extension/dist/extension.js', input.bundle);
  for (const [name, text] of texts)
    for (const [pattern, label] of SECRET_PATTERNS)
      if (pattern.test(text)) violations.push(`secret heuristic (${label}) in ${name}`);

  return violations;
}
