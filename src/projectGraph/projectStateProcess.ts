import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { realpathSync, statSync } from 'node:fs';
import * as path from 'node:path';

export const PROJECT_STATE_TIMEOUT_MS = 10_000;
export const PROJECT_STATE_MAX_OUTPUT_BYTES = 1024 * 1024;
export type ProcessFailure =
  'missingTool' | 'missingPython' | 'timeout' | 'cancelled' | 'oversizedOutput' | 'processError';
export type ProjectStateProcessResult =
  | { readonly kind: 'success'; readonly stdout: string }
  | {
      readonly kind: 'error';
      readonly reason: ProcessFailure;
      readonly detail: string;
      readonly stdout?: string;
    };
export interface ProjectStateProcessOptions {
  readonly executable?: string;
  readonly timeoutMs?: number;
  readonly outputLimitBytes?: number;
  readonly killGraceMs?: number;
  readonly spawn?: typeof spawn;
}

/** Единственный fixed argv ADR-008; configurable executable предназначен для owning-layer tests. */
export function projectStateArguments(root: string, executable = 'python3') {
  return { command: executable, args: ['.harness/tools/project-state.py', '--json'], cwd: root };
}

export class ProjectStateProcess {
  constructor(private readonly options: ProjectStateProcessOptions = {}) {}

  async run(root: string, signal?: AbortSignal): Promise<ProjectStateProcessResult> {
    const fail = (reason: ProcessFailure, detail: string): ProjectStateProcessResult => ({
      kind: 'error',
      reason,
      detail,
    });
    if (signal?.aborted) return fail('cancelled', '');
    let canonicalRoot: string;
    try {
      canonicalRoot = realpathSync(root);
      const tool = realpathSync(path.join(canonicalRoot, '.harness/tools/project-state.py'));
      const relative = path.relative(canonicalRoot, tool);
      if (
        relative.startsWith(`..${path.sep}`) ||
        relative === '..' ||
        path.isAbsolute(relative) ||
        !statSync(tool).isFile()
      )
        return fail('missingTool', '');
    } catch {
      return fail('missingTool', '');
    }
    const invocation = projectStateArguments(canonicalRoot, this.options.executable);
    return new Promise((resolve) => {
      let child: ChildProcessWithoutNullStreams;
      try {
        child = (this.options.spawn ?? spawn)(invocation.command, invocation.args, {
          cwd: invocation.cwd,
          shell: false,
          windowsHide: true,
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
        });
      } catch (error) {
        resolve(fail('processError', String(error)));
        return;
      }
      const stdout: Buffer[] = [],
        stderr: Buffer[] = [];
      let outBytes = 0,
        errBytes = 0,
        failure: ProjectStateProcessResult | undefined;
      let killTimer: ReturnType<typeof setTimeout> | undefined;
      const limit = this.options.outputLimitBytes ?? PROJECT_STATE_MAX_OUTPUT_BYTES;
      // Решаем Promise только после close: следующий запрос не перекрывает ещё живой child.
      const terminate = (reason: ProcessFailure) => {
        if (failure) return;
        failure = fail(reason, '');
        child.kill('SIGTERM');
        killTimer = setTimeout(() => child.kill('SIGKILL'), this.options.killGraceMs ?? 250);
      };
      const cancel = () => terminate('cancelled');
      const timeout = setTimeout(
        () => terminate('timeout'),
        this.options.timeoutMs ?? PROJECT_STATE_TIMEOUT_MS,
      );
      signal?.addEventListener('abort', cancel, { once: true });
      if (signal?.aborted) cancel();
      child.on('error', (error: NodeJS.ErrnoException) => {
        failure = fail(error.code === 'ENOENT' ? 'missingPython' : 'processError', error.message);
      });
      child.stdout.on('data', (chunk: Buffer) => {
        if (failure) return;
        outBytes += chunk.length;
        if (outBytes > limit) terminate('oversizedOutput');
        else stdout.push(chunk);
      });
      child.stderr.on('data', (chunk: Buffer) => {
        if (failure) return;
        errBytes += chunk.length;
        if (errBytes > limit) terminate('oversizedOutput');
        else stderr.push(chunk);
      });
      child.on('close', (code) => {
        clearTimeout(timeout);
        if (killTimer) clearTimeout(killTimer);
        signal?.removeEventListener('abort', cancel);
        resolve(
          failure ??
            (code === 0
              ? { kind: 'success', stdout: Buffer.concat(stdout).toString('utf8') }
              : {
                  kind: 'error',
                  reason: 'processError',
                  detail: Buffer.concat(stderr).toString('utf8').slice(0, 4096),
                  stdout: Buffer.concat(stdout).toString('utf8'),
                }),
        );
      });
    });
  }
}
