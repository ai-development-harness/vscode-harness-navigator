/** Реальная wire-форма schemaVersion 1; fixtures не повторяют parser Harness. */
export function projectStateFixture() {
  return {
    schemaVersion: 1,
    status: 'PASS',
    integrity: 'degraded',
    project: { name: 'fixture', initialized: true, harnessRelease: '0.10.3' },
    summary: { relationshipCoveragePercent: 75 },
    insights: {
      dependency: { longestChain: ['STEP-002', 'STEP-001'], cycles: [['STEP-001', 'STEP-002']] },
      blockers: [{ id: 'STEP-002', reasons: ['MISSING:REQ-999'] }],
      uncoveredRequirements: ['REQ-001'],
      isolatedArtifacts: ['OQ-001'],
    },
    diagnostics: [{ category: 'MissingReference', message: 'REQ-999', artifactId: 'STEP-002' }],
    sources: { steps: 'planning/tasks', requirements: 'docs/requirements' },
    graph: {
      rootNodeId: 'PROJECT:fixture',
      nodes: [
        {
          id: 'PROJECT:fixture',
          artifactId: 'PROJECT',
          type: 'PROJECT',
          title: 'fixture',
          metadata: {},
        },
        {
          id: 'STEP-001',
          artifactId: 'STEP-001',
          type: 'STEP',
          status: 'in_progress',
          title: 'Первый шаг',
          path: 'planning/tasks/STEP-001.md',
          metadata: { priority: 'high', phase: 'mvp', planFreshness: 'fresh', executionGroups: [] },
        },
        {
          id: 'STEP-002',
          artifactId: 'STEP-002',
          type: 'STEP',
          status: 'blocked',
          title: 'Второй шаг',
          path: 'planning/tasks/STEP-002.md',
          metadata: {
            planFreshness: 'stale',
            planStaleCauses: ['requirements'],
            planRemediation: 'STEP PLAN STEP-002',
            downstreamImpact: 4,
          },
        },
        {
          id: 'REQ-001',
          artifactId: 'REQ-001',
          type: 'REQ',
          path: 'docs/requirements/REQ-001.md',
          metadata: {},
        },
        { id: 'ADR-001', artifactId: 'ADR-001', type: 'ADR', metadata: {} },
        { id: 'OQ-001', artifactId: 'OQ-001', type: 'OQ', metadata: {} },
        { id: 'REVIEW:1', artifactId: 'REVIEW:1', type: 'REVIEW', metadata: {} },
        { id: 'SKILL:1', artifactId: 'SKILL:1', type: 'SKILL', metadata: {} },
        {
          id: 'MISSING:REQ-999',
          artifactId: 'REQ-999',
          type: 'MISSING',
          metadata: { referencedId: 'REQ-999' },
        },
      ],
      edges: [
        {
          source: 'STEP-002',
          target: 'STEP-001',
          relation: 'depends_on',
          declaredBy: ['STEP-002'],
        },
        {
          source: 'STEP-001',
          target: 'STEP-002',
          relation: 'depends_on',
          declaredBy: ['STEP-001'],
        },
        {
          source: 'REQ-001',
          target: 'STEP-001',
          relation: 'implemented_by',
          declaredBy: ['REQ-001', 'STEP-001'],
        },
        {
          source: 'STEP-002',
          target: 'MISSING:REQ-999',
          relation: 'addresses',
          declaredBy: ['STEP-002'],
        },
        { source: 'ADR-001', target: 'STEP-001', relation: 'governs', declaredBy: ['ADR-001'] },
        { source: 'OQ-001', target: 'REQ-001', relation: 'affects', declaredBy: ['OQ-001'] },
        { source: 'REVIEW:1', target: 'STEP-001', relation: 'reviews', declaredBy: ['REVIEW:1'] },
      ],
    },
  };
}
