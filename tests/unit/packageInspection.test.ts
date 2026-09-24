import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as zlib from 'node:zlib';
import { ZipFormatError, readZipEntries, readZipEntryData } from '../../scripts/packageArchive';
import { encodePng, pngChunk, renderIconRgba, PNG_SIGNATURE } from '../../scripts/iconEncoder';
import {
  ALLOWED_ENTRIES,
  compareReadmeWithSource,
  inspectPackage,
  inspectReadmeText,
  type PackageInspectionInput,
} from '../../scripts/packageInspection';

const validManifest = {
  main: './dist/extension.js',
  l10n: './l10n',
  icon: 'resources/icon.png',
  galleryBanner: { color: '#1f2937', theme: 'dark' },
  contributes: {},
};

function png(side: number, width: number = side): Buffer {
  return encodePng(
    width,
    side,
    renderIconRgba(Math.max(width, side)).subarray(0, width * side * 4),
  );
}
const validIcon = png(256);
const ICON_ENTRY = 'extension/resources/icon.png';
const cleanBundle =
  'var a=require("vscode");var b=require("node:fs");var c=require("node:path");module.exports={};';

function input(overrides: Partial<PackageInspectionInput> = {}): PackageInspectionInput {
  return {
    entryNames: [...ALLOWED_ENTRIES],
    archiveBytes: 50_000,
    packageJson: validManifest,
    bundle: cleanBundle,
    textEntries: new Map(),
    binaryEntries: new Map([[ICON_ENTRY, validIcon]]),
    ...overrides,
  };
}

test('эталонный allowlist проходит inspection без нарушений', () => {
  assert.deepEqual(inspectPackage(input()), []);
});

test('лишние и запрещённые entries дают violations', () => {
  const violations = inspectPackage(
    input({
      entryNames: [
        ...ALLOWED_ENTRIES,
        'extension/src/extension.ts',
        'extension/dist/extension.js.map',
        'extension/node_modules/x/index.js',
        'extension/.env',
      ],
    }),
  );
  for (const expected of ['src/', '*.ts', '*.map', 'node_modules/', '.env*'])
    assert.ok(
      violations.some((item) => item.includes(expected)),
      `expected violation for ${expected}: ${violations.join(' | ')}`,
    );
});

test('отсутствующий обязательный entry и слишком большой архив дают violations', () => {
  const violations = inspectPackage(
    input({ entryNames: ALLOWED_ENTRIES.slice(1), archiveBytes: 50 * 1024 * 1024 }),
  );
  assert.ok(violations.some((item) => item.includes('required entry is missing')));
  assert.ok(violations.some((item) => item.includes('too large')));
});

test('запрещённые модули и токены bundle дают violations', () => {
  for (const bundle of [
    'require("child_process").exec("x")',
    'require("node:http")',
    'const r = fetch("https://x")',
    'vscode.window.createTerminal()',
    'fs.writeFileSync(a,b)',
    '//# sourceMappingURL=extension.js.map',
  ])
    assert.ok(inspectPackage(input({ bundle })).length > 0, bundle);
});

test('manifest с enabledApiProposals, extensionDependencies и authentication даёт violations', () => {
  const violations = inspectPackage(
    input({
      packageJson: {
        ...validManifest,
        enabledApiProposals: ['x'],
        extensionDependencies: ['a.b'],
        contributes: { authentication: [] },
      },
    }),
  );
  assert.equal(violations.length, 3);
  assert.ok(inspectPackage(input({ packageJson: { main: './x.js', l10n: './l10n' } })).length > 0);
});

test('secret heuristics находят PRIVATE KEY блок и токены', () => {
  // Маркер собирается из частей, чтобы тест сам не содержал литерал приватного ключа.
  const dashes = '-'.repeat(5);
  const key = `${dashes}BEGIN RSA ${'PRIVATE'} KEY${dashes}\nabc\n${dashes}END RSA ${'PRIVATE'} KEY${dashes}`;
  assert.ok(
    inspectPackage(input({ textEntries: new Map([['extension/readme.md', key]]) })).some((item) =>
      item.includes('PRIVATE KEY'),
    ),
  );
  assert.ok(
    inspectPackage(
      input({ textEntries: new Map([['extension/readme.md', `ghp_${'a'.repeat(30)}`]]) }),
    ).some((item) => item.includes('ghp_')),
  );
});

interface Entry {
  name: string;
  data: Buffer;
  method?: 0 | 8;
  flags?: number;
}

/** Минимальный ZIP-сериализатор для тестов (stored/deflate), без внешних зависимостей. */
function buildZip(entries: Entry[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const entry of entries) {
    const method = entry.method ?? 0;
    const payload = method === 8 ? zlib.deflateRawSync(entry.data) : entry.data;
    const name = Buffer.from(entry.name);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(entry.flags ?? 0, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(payload.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, payload);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(entry.flags ?? 0, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(payload.length, 20);
    central.writeUInt32LE(entry.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += 30 + name.length + payload.length;
  }
  const directory = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(directory.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, eocd]);
}

test('archive reader читает stored и deflate entries', () => {
  const zip = buildZip([
    { name: 'extension/a.txt', data: Buffer.from('stored') },
    { name: 'extension/b.txt', data: Buffer.from('deflated '.repeat(20)), method: 8 },
  ]);
  const entries = readZipEntries(zip);
  assert.deepEqual(
    entries.map((entry) => entry.name),
    ['extension/a.txt', 'extension/b.txt'],
  );
  assert.equal(readZipEntryData(zip, entries[0] as never).toString(), 'stored');
  assert.equal(readZipEntryData(zip, entries[1] as never).toString(), 'deflated '.repeat(20));
});

test('archive reader отвергает zip-slip, абсолютные пути, backslash и шифрование', () => {
  for (const name of ['../evil.txt', 'extension/../../evil.txt', '/etc/passwd', 'C:/x', 'a\\b'])
    assert.throws(
      () => readZipEntries(buildZip([{ name, data: Buffer.from('x') }])),
      ZipFormatError,
      name,
    );
  assert.throws(
    () => readZipEntries(buildZip([{ name: 'extension/x', data: Buffer.from('x'), flags: 1 }])),
    ZipFormatError,
  );
  assert.throws(() => readZipEntries(Buffer.from('not a zip')), ZipFormatError);
});

test('bundle: запрещены workspace.fs, async fs write, openExternal, saveAll, save/edit', () => {
  for (const bundle of [
    'vscode.workspace.fs.delete(u)',
    'vscode.workspace.fs.rename(a,b)',
    'vscode.workspace.fs.createDirectory(u)',
    'fs.rm(p,cb)',
    'fs.unlink(p,cb)',
    'fs.mkdir(p,cb)',
    'fs.rename(a,b,cb)',
    'fs.copyFile(a,b,cb)',
    'fs.symlink(a,b,cb)',
    'fs.chmod(p,1,cb)',
    'fs.promises.writeFile(p,d)',
    'vscode.env.openExternal(u)',
    'vscode.workspace.saveAll()',
    'doc.save()',
    'editor.edit(cb)',
  ])
    assert.ok(
      inspectPackage(input({ bundle: `${cleanBundle}${bundle}` })).length > 0,
      `expected violation for ${bundle}`,
    );
});

test('bundle: нелитеральный require, backtick и module.require дают violations', () => {
  for (const bundle of [
    'require(`child_process`)',
    'require(name)',
    'require( x + "y")',
    'module.require("fs")',
  ])
    assert.ok(
      inspectPackage(input({ bundle: `${cleanBundle}${bundle}` })).length > 0,
      `expected violation for ${bundle}`,
    );
});

test('archive reader ограничивает объём распаковки', () => {
  const bomb = buildZip([
    { name: 'extension/bomb.txt', data: Buffer.alloc(9 * 1024 * 1024), method: 8 },
  ]);
  assert.throws(() => readZipEntries(bomb), ZipFormatError);

  // Заявленный size меньше реального: inflate обязан упереться в maxOutputLength.
  const lying = buildZip([
    { name: 'extension/lie.txt', data: Buffer.from('a'.repeat(4096)), method: 8 },
  ]);
  const entries = readZipEntries(lying);
  assert.throws(
    () => readZipEntryData(lying, { ...(entries[0] as never as object), size: 10 } as never),
    ZipFormatError,
  );

  // Суммарный объём выше лимита при допустимых отдельных entries.
  const many = buildZip(
    Array.from({ length: 3 }, (_, index) => ({
      name: `extension/part${index}.bin`,
      data: Buffer.alloc(7 * 1024 * 1024),
      method: 8 as const,
    })),
  );
  assert.throws(() => readZipEntries(many), ZipFormatError);

  assert.throws(() => readZipEntries(Buffer.alloc(9 * 1024 * 1024)), ZipFormatError);
});

test('bundle: деструктуризация workspace, write-флаги, конкатенация require и executeCommand вне allowlist', () => {
  for (const bundle of [
    'let{fs:c}=n.workspace;await c.delete(e,{recursive:!0})',
    'let{fs:c}=n.workspace;await c.copy(e,e)',
    'n.workspace["fs"]',
    'i.openSync(p,"w")',
    'i.openSync(p,i.constants.O_WRONLY)',
    'process.binding("fs")',
    'require("node:child_"+"process")',
    'n.commands.executeCommand("workbench.action.terminal.sendSequence",x)',
    'n.commands.executeCommand("workbench.action.tasks.runTask")',
    'n.commands.executeCommand(name)',
  ])
    assert.ok(
      inspectPackage(input({ bundle: `${cleanBundle}${bundle}` })).length > 0,
      `expected violation for ${bundle}`,
    );
});

test('bundle: executeCommand с литеральными внутренними id проходит', () => {
  const bundle =
    'n.commands.executeCommand("vscode.open",U.file(f));n.commands.executeCommand("harnessNavigator.findAllReferences",{a:1});n.commands.executeCommand("editor.action.peekLocations",u,p,l,"peek")';
  assert.deepEqual(inspectPackage(input({ bundle: `${cleanBundle}${bundle}` })), []);
});

function withIcon(data: Uint8Array): PackageInspectionInput {
  return input({ binaryEntries: new Map([[ICON_ENTRY, data]]) });
}

/** Вставляет чанк перед IEND валидного PNG. */
function insertChunk(base: Buffer, chunk: Buffer): Buffer {
  return Buffer.concat([
    base.subarray(0, base.length - 12),
    chunk,
    base.subarray(base.length - 12),
  ]);
}

test('иконка: валидный PNG проходит, размеры 128 и 1024 допустимы', () => {
  assert.deepEqual(inspectPackage(withIcon(validIcon)), []);
  assert.deepEqual(inspectPackage(withIcon(png(128))), []);
  assert.deepEqual(
    inspectPackage(withIcon(png(1024))).filter((item) => !item.includes('too large')),
    [],
  );
});

test('иконка: нарушения размеров, формата и метаданных', () => {
  const cases: [string, Uint8Array, string][] = [
    ['64x64', png(64), 'icon side'],
    ['неквадратная', png(200, 256), 'square'],
    ['больше 1024', png(1025), 'icon side'],
    ['не PNG', Buffer.from('GIF89a not a png at all'), 'bad signature'],
    ['tEXt', insertChunk(validIcon, pngChunk('tEXt', Buffer.from('k\0v'))), 'tEXt'],
    ['iTXt', insertChunk(validIcon, pngChunk('iTXt', Buffer.from('k\0v'))), 'iTXt'],
    ['zTXt', insertChunk(validIcon, pngChunk('zTXt', Buffer.from('k\0v'))), 'zTXt'],
    [
      'больше 200 KiB',
      insertChunk(validIcon, pngChunk('prVt', Buffer.alloc(201 * 1024))),
      'too large',
    ],
    ['обрезанный', validIcon.subarray(0, 40), 'IEND'],
    ['без IHDR первым', Buffer.concat([PNG_SIGNATURE, pngChunk('IEND', Buffer.alloc(0))]), 'IHDR'],
  ];
  for (const [label, data, expected] of cases) {
    const violations = inspectPackage(withIcon(data));
    assert.ok(
      violations.some((item) => item.includes(expected)),
      `${label}: ${violations.join(' | ')}`,
    );
  }
});

test('иконка: путь manifest.icon, отсутствие entry и лишние изображения', () => {
  assert.ok(
    inspectPackage(input({ packageJson: { ...validManifest, icon: 'images/icon.png' } })).some(
      (item) => item.includes('manifest icon must be'),
    ),
  );
  assert.ok(
    inspectPackage(input({ packageJson: { ...validManifest, icon: undefined } })).some((item) =>
      item.includes('manifest icon must be'),
    ),
  );
  assert.ok(
    inspectPackage(input({ binaryEntries: new Map() })).some((item) =>
      item.includes('icon entry is missing'),
    ),
  );
  for (const extra of [
    'extension/resources/logo.svg',
    'extension/a.gif',
    'extension/a.ico',
    'extension/a.jpg',
    'extension/a.jpeg',
    'extension/a.webp',
    'extension/resources/second.png',
  ])
    assert.ok(
      inspectPackage(input({ entryNames: [...ALLOWED_ENTRIES, extra] })).some((item) =>
        item.includes(extra),
      ),
      extra,
    );
});

test('galleryBanner: некорректные color и theme дают violations', () => {
  for (const galleryBanner of [
    { color: 'red', theme: 'dark' },
    { color: '#fff', theme: 'dark' },
    { color: '#1f2937', theme: 'blue' },
    { color: '#1f2937' },
    'dark',
  ])
    assert.ok(
      inspectPackage(input({ packageJson: { ...validManifest, galleryBanner } })).some((item) =>
        item.includes('galleryBanner'),
      ),
      JSON.stringify(galleryBanner),
    );
  assert.deepEqual(
    inspectPackage(input({ packageJson: { ...validManifest, galleryBanner: undefined } })),
    [],
  );
});

test('README: Harness-managed блок и относительные приватные ссылки дают violations', () => {
  const readme = (text: string): PackageInspectionInput =>
    input({ textEntries: new Map([['extension/readme.md', text]]) });
  assert.deepEqual(inspectPackage(readme('# Title\n[repo](https://github.com/a/b)')), []);
  for (const text of [
    '<!-- PROJECT:START -->',
    'x <!-- PROJECT:END -->',
    '[a](docs/x.md)',
    '[a](planning/x.md)',
    '[a](.harness/x.yaml)',
    '[a](./docs/x.md)',
  ])
    assert.ok(inspectPackage(readme(text)).length > 0, text);
});

test('иконка: данные после IEND, отсутствие IDAT и битый CRC', () => {
  const noIdat = Buffer.concat([
    PNG_SIGNATURE,
    validIcon.subarray(8, 33),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
  const badCrc = Buffer.from(validIcon);
  badCrc[29] = (badCrc[29] ?? 0) ^ 0xff; // CRC чанка IHDR
  const cases: [string, Uint8Array, string][] = [
    [
      'tEXt после IEND',
      Buffer.concat([validIcon, pngChunk('tEXt', Buffer.from('k\0v'))]),
      'trailing',
    ],
    ['хвост байтов', Buffer.concat([validIcon, Buffer.from([1, 2, 3])]), 'trailing'],
    ['без IDAT', noIdat, 'no IDAT'],
    ['битый CRC', badCrc, 'bad CRC'],
  ];
  for (const [label, data, expected] of cases) {
    const violations = inspectPackage(withIcon(data));
    assert.ok(
      violations.some((item) => item.includes(expected)),
      `${label}: ${violations.join(' | ')}`,
    );
  }
  assert.deepEqual(inspectPackage(withIcon(validIcon)), []);
});

test('README: расширенные формы относительных ссылок и переписанная vsce форма', () => {
  const bad = [
    '[a](docs/x.md)',
    '[a](/docs/x.md)',
    '[a](../docs/x.md)',
    '[a](../../planning/x.md)',
    '[a](/.harness/x.yaml)',
    '[a](other.md)',
    '<img src="images/a.png">',
    "<a href='docs/a.md'>x</a>",
    '[ref]: docs/x.md',
    'see #12 for details',
    '[a](https://github.com/o/r/blob/HEAD/docs/x.md)',
    'https://github.com/o/r/blob/HEAD/planning/x.md',
    'https://github.com/o/r/blob/HEAD/.harness/x.yaml',
  ];
  for (const text of bad) assert.ok(inspectReadmeText(text).length > 0, text);
  const good = [
    '# Title\n[a](https://github.com/o/r)',
    '<a href="https://example.com">x</a>',
    '[a](#section)',
    '[ref]: https://example.com/x',
    'Issue-free text with STEP-010',
  ];
  for (const text of good) assert.deepEqual(inspectReadmeText(text), [], text);
});

test('README: сравнение с исходником — equal, differs, source-missing', () => {
  assert.equal(compareReadmeWithSource('a', 'a').status, 'equal');
  assert.equal(compareReadmeWithSource('a', 'b').status, 'differs');
  const missing = compareReadmeWithSource('a', undefined);
  assert.equal(missing.status, 'source-missing');
  assert.match(missing.message, /skipped/u);
  assert.equal(compareReadmeWithSource(undefined, 'a').status, 'packaged-missing');
});
