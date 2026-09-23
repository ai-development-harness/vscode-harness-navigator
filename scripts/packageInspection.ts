// Чистые правила inspection VSIX: entries + extension/package.json +
// extension/dist/extension.js -> список violations. Без I/O и без сети.

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
];

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
