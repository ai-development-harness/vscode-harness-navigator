import * as path from 'node:path';
import * as vscode from 'vscode';
import { isBundleOriginated } from './stackAttribution';

// Патчатся реальные module objects (а не копии `import * as`, которые TS
// создаёт с getter-only свойствами), поэтому используется require: bundle
// расширения вызывает те же встроенные модули.
/* eslint-disable @typescript-eslint/no-require-imports, @typescript-eslint/no-unsafe-assignment */
const childProcess: object = require('node:child_process');
const dns: object = require('node:dns');
const fs: typeof import('node:fs') = require('node:fs');
const http: object = require('node:http');
const https: object = require('node:https');
const net: object = require('node:net');
const tls: object = require('node:tls');
/* eslint-enable @typescript-eslint/no-require-imports, @typescript-eslint/no-unsafe-assignment */

export type SpyKind = 'forbidden' | 'observed';

export interface SpyRecord {
  readonly api: string;
  readonly kind: SpyKind;
  /** Результат stackAttribution: есть ли кадр bundle расширения. */
  readonly extensionOriginated: boolean;
  /** `true`, если вызов завершён sentinel без call-through. */
  readonly sentinel: boolean;
}

/** Sentinel нарушения: исключение вместо исполнения shell/network/write из bundle. */
export class BoundaryViolationSentinel extends Error {
  constructor(api: string) {
    super(`boundary violation sentinel: ${api}`);
    this.name = 'BoundaryViolationSentinel';
  }
}

interface Target {
  readonly api: string;
  readonly owner: object;
  readonly key: string;
  readonly kind: SpyKind;
}

const asRecord = (value: unknown): Record<string, unknown> => value as Record<string, unknown>;

function targets(): Target[] {
  const list: Target[] = [];
  const add = (prefix: string, owner: unknown, keys: readonly string[], kind: SpyKind) => {
    if (typeof owner !== 'object' && typeof owner !== 'function') return;
    for (const key of keys)
      if (typeof asRecord(owner)[key] === 'function')
        list.push({ api: `${prefix}.${key}`, owner: owner as object, key, kind });
  };
  add(
    'child_process',
    childProcess,
    ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork'],
    'forbidden',
  );
  add('http', http, ['request', 'get'], 'forbidden');
  add('https', https, ['request', 'get'], 'forbidden');
  add('net', net, ['connect', 'createConnection'], 'forbidden');
  add('tls', tls, ['connect'], 'forbidden');
  add('dns', dns, ['lookup'], 'forbidden');
  add('globalThis', globalThis, ['fetch'], 'forbidden');
  const writeNames = Object.keys(fs).filter((name) =>
    /^(writeFile|appendFile|rename|unlink|rm|mkdir|rmdir|write|truncate|ftruncate|copyFile|cp|symlink|link|chmod|chown|utimes|mkdtemp)(Sync)?$/u.test(
      name,
    ),
  );
  add('fs', fs, writeNames, 'forbidden');
  add(
    'fs.promises',
    fs.promises,
    Object.keys(fs.promises).filter((name) =>
      /^(writeFile|appendFile|rename|unlink|rm|mkdir|rmdir|truncate|copyFile|cp|symlink|link|chmod|chown|utimes|mkdtemp)$/u.test(
        name,
      ),
    ),
    'forbidden',
  );
  add('vscode.window', vscode.window, ['createTerminal'], 'forbidden');
  add('vscode.tasks', vscode.tasks, ['executeTask'], 'forbidden');
  add('vscode.authentication', vscode.authentication, ['getSession'], 'forbidden');
  add(
    'vscode.workspace.fs',
    vscode.workspace.fs,
    ['writeFile', 'delete', 'rename', 'createDirectory', 'copy'],
    'forbidden',
  );
  add('vscode.workspace', vscode.workspace, ['applyEdit'], 'forbidden');
  add(
    'fs',
    fs,
    [
      'readFileSync',
      'openSync',
      'readSync',
      'statSync',
      'lstatSync',
      'fstatSync',
      'readdirSync',
      'opendirSync',
      'readFile',
      'open',
      'stat',
      'readdir',
    ],
    'observed',
  );
  add('vscode.window', vscode.window, ['showQuickPick'], 'observed');
  return list;
}

/**
 * Runtime spies границы расширения. Forbidden API, вызванный из bundle
 * расширения (stackAttribution), фиксируется и завершается sentinel без
 * call-through; вызов не из bundle (тест, mocha, built-in расширения, сам
 * VS Code) фиксируется как extension-originated=false и проходит call-through.
 * Observed API только записывается и проходит call-through.
 */
export class BoundarySpies {
  readonly records: SpyRecord[] = [];
  readonly unpatched: { api: string; reason: string }[] = [];
  /** Violation-path control: временно считать эти observed API forbidden. */
  escalatedApis = new Set<string>();
  private readonly restorers: (() => void)[] = [];
  private previousStackTraceLimit = Error.stackTraceLimit;
  private bundleFile = '';

  install(bundleFile: string): void {
    this.bundleFile = path.normalize(bundleFile);
    this.previousStackTraceLimit = Error.stackTraceLimit;
    Error.stackTraceLimit = 100;
    for (const target of targets()) this.patch(target);
  }

  restore(): void {
    for (const restore of this.restorers.splice(0).reverse()) restore();
    Error.stackTraceLimit = this.previousStackTraceLimit;
    this.escalatedApis = new Set();
  }

  reset(): void {
    this.records.length = 0;
  }

  /** Forbidden-записи, атрибутированные bundle. */
  violations(): SpyRecord[] {
    return this.records.filter(
      (record) => record.kind === 'forbidden' && record.extensionOriginated,
    );
  }

  recordsFor(api: string): SpyRecord[] {
    return this.records.filter((record) => record.api === api);
  }

  /** Сообщает о вызове с произвольным (например имитированным) stack без исполнения API. */
  classifyStack(stack: string): boolean {
    return isBundleOriginated(stack, this.bundleFile);
  }

  private patch(target: Target): void {
    const owner = asRecord(target.owner);
    const original = owner[target.key] as (...args: unknown[]) => unknown;
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const spies = this;
    const wrapper = function (this: unknown, ...args: unknown[]): unknown {
      const extensionOriginated = isBundleOriginated(new Error().stack ?? '', spies.bundleFile);
      const forbidden = target.kind === 'forbidden' || spies.escalatedApis.has(target.api);
      const sentinel = forbidden && extensionOriginated;
      spies.records.push({
        api: target.api,
        kind: forbidden ? 'forbidden' : target.kind,
        extensionOriginated,
        sentinel,
      });
      if (sentinel) throw new BoundaryViolationSentinel(target.api);
      return original.apply(this, args);
    };
    try {
      owner[target.key] = wrapper;
      if (owner[target.key] !== wrapper) throw new Error('assignment ignored');
    } catch {
      try {
        Object.defineProperty(target.owner, target.key, {
          value: wrapper,
          configurable: true,
          writable: true,
        });
      } catch (error) {
        this.unpatched.push({
          api: target.api,
          reason: error instanceof Error ? error.message : 'not writable',
        });
        return;
      }
    }
    this.restorers.push(() => {
      try {
        owner[target.key] = original;
        if (owner[target.key] !== original)
          Object.defineProperty(target.owner, target.key, {
            value: original,
            configurable: true,
            writable: true,
          });
      } catch {
        // Восстановление best-effort: невосстановимое свойство фиксируется тестом через unpatched.
      }
    });
  }
}
