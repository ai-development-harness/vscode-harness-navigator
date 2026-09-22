/**
 * Стабильные категории диагностики границы определения Harness-проекта.
 * Значения являются техническим контрактом для Output Channel и не зависят
 * от локали пользовательского интерфейса.
 */
export type ProjectDiagnosticCategory =
  | 'ValidHarnessProject'
  | 'NotHarnessProject'
  | 'InvalidManifest'
  | 'UnsupportedHarnessVersion'
  | 'UnsupportedSchema'
  | 'ConfigurationBlocked'
  | 'ArtifactDirectoryMissing'
  | 'ArtifactParseError'
  | 'DuplicateArtifactId'
  | 'InvalidArtifactReference'
  | 'ProjectionReadError'
  | 'UnexpectedInternalError';

export interface ProjectDiagnostic {
  readonly category: ProjectDiagnosticCategory;
  /** Ключ локализуемого объяснения, независимый от stable taxonomy category. */
  readonly message: string;
  readonly messageArguments: readonly (string | number)[];
  /** Безопасная техническая деталь для Output Channel; она не является UI-текстом. */
  readonly detail: string;
}

export interface ConfiguredPaths {
  readonly taskDirectory: string;
  readonly projectOverview: string;
  readonly requirements: string;
  readonly adrDirectory: string;
  readonly architecture: string;
  readonly openQuestions: string;
  readonly openQuestionsIndex: string;
  readonly roadmap: string;
  readonly status: string;
}

interface BaseProjectState {
  readonly workspaceRoot: string;
  readonly diagnostic: ProjectDiagnostic;
}

export interface NonHarnessProjectState extends BaseProjectState {
  readonly kind: 'nonHarness';
}

export interface InvalidManifestState extends BaseProjectState {
  readonly kind: 'invalidManifest';
}

export interface UnsupportedVersionState extends BaseProjectState {
  readonly kind: 'unsupportedVersion';
  readonly detectedRelease: string;
  readonly minimumRelease: '0.6.0';
}

export interface UnsupportedSchemaState extends BaseProjectState {
  readonly kind: 'unsupportedSchema';
  readonly detectedSchema: string;
}

export interface ConfigurationBlockedState extends BaseProjectState {
  readonly kind: 'configurationBlocked';
}

export interface ValidProjectState extends BaseProjectState {
  readonly kind: 'valid';
  readonly release: string;
  readonly configuredPaths: ConfiguredPaths;
}

export type ProjectState =
  | NonHarnessProjectState
  | InvalidManifestState
  | UnsupportedVersionState
  | UnsupportedSchemaState
  | ConfigurationBlockedState
  | ValidProjectState;
