import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as zlib from 'node:zlib';
import { ZipFormatError, readZipEntries, readZipEntryData } from '../../scripts/packageArchive';
import {
  ALLOWED_ENTRIES,
  inspectPackage,
  type PackageInspectionInput,
} from '../../scripts/packageInspection';

const validManifest = { main: './dist/extension.js', l10n: './l10n', contributes: {} };
const cleanBundle =
  'var a=require("vscode");var b=require("node:fs");var c=require("node:path");module.exports={};';

function input(overrides: Partial<PackageInspectionInput> = {}): PackageInspectionInput {
  return {
    entryNames: [...ALLOWED_ENTRIES],
    archiveBytes: 50_000,
    packageJson: validManifest,
    bundle: cleanBundle,
    textEntries: new Map(),
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
