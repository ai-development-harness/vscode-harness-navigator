import type { ProjectDiagnosticCategory } from '../projectModel/projectState';

/** Общий контракт локализованных ошибок panel и diagnostics по REQ-008/REQ-011. */
export const PROJECT_STATE_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  unavailable: 'Harness project configuration is unavailable.',
  unsupportedHarness: 'Dependency Graph requires Harness 0.10.3 or newer.',
  untrusted: 'Project State API requires a trusted workspace.',
  missingTool: 'Project State API tool is unavailable.',
  missingPython: 'Python 3 is unavailable.',
  timeout: 'Project State API timed out.',
  cancelled: 'Project State API request was cancelled.',
  oversizedOutput: 'Project State API output exceeds the size limit.',
  processError: 'Project State API process failed.',
  malformed: 'Project State API returned malformed JSON.',
  unsupportedSchema: 'Project State API schema is unsupported.',
  blocked: 'Project State API is BLOCKED.',
  loading: 'Loading Project State API.',
};

export const PROJECT_STATE_ERROR_CATEGORIES: Readonly<Record<string, ProjectDiagnosticCategory>> = {
  missingTool: 'ProjectStateUnavailable',
  missingPython: 'ProjectStatePythonUnavailable',
  timeout: 'ProjectStateTimeout',
  oversizedOutput: 'ProjectStateOutputTooLarge',
  unsupportedSchema: 'ProjectStateUnsupportedSchema',
  blocked: 'ProjectStateBlocked',
  untrusted: 'ProjectStateUnavailable',
};
