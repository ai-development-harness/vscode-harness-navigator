import type { DependencyGraphPresentation } from './dependencyGraphPresentation';
import type { GraphFilters, GraphPreset, GraphViewTools } from './dependencyGraphViewModel';
import type { layoutDependencyGraph } from './dependencyGraphLayout';

/** Самодостаточный DOM runtime использует те же helpers, что unit tests; Host предоставляет только snapshot и navigation intent. */
export function dependencyGraphRuntime(
  api: { postMessage(message: unknown): void },
  labels: Readonly<Record<string, string>>,
  initialModel: DependencyGraphPresentation,
  root: string,
  tools: GraphViewTools,
  layout: typeof layoutDependencyGraph,
): void {
  const el = (id: string) => {
    const value = document.getElementById(id);
    if (!value) throw new Error(id);
    return value;
  };
  const label = (key: string) => labels[key] ?? key;
  const node = (tag: string, text?: string, parent?: Element) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    parent?.append(n);
    return n;
  };
  const button = (parent: Element, key: string, action: () => void) => {
    const b = node('button', label(key), parent);
    b.onclick = action;
    return b;
  };
  const svg = el('graph') as unknown as SVGSVGElement,
    ns = 'http://www.w3.org/2000/svg';
  const item = (tag: string, attrs: Record<string, string | number>, parent: Element = svg) => {
    const n = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, `${v}`));
    parent.append(n);
    return n;
  };
  const send = (type: string, id?: string) =>
    api.postMessage(id === undefined ? { type } : { type, id });
  let model = initialModel,
    filters: GraphFilters = tools.defaults(model.focusId),
    selected = model.selectedId;
  let navigation = model.navigationRevision ?? 0,
    chainOn = false,
    firstReady = true,
    bounds: readonly number[] = [0, 0, 1000, 600];
  let fingerprint = '',
    drag: { x: number; y: number; box: number[] } | undefined;
  const groups = new Map<string, Element>(),
    edges: { element: Element; from: string; to: string; type: string }[] = [];
  const search = el('search') as HTMLInputElement;
  const status = el('status-filter') as HTMLSelectElement;
  const presets: readonly [GraphPreset, string][] = [
    ['full', 'full'],
    ['steps', 'mode'],
    ['blockers', 'blockers'],
    ['cycles', 'cycles'],
    ['missing', 'missingReferences'],
    ['uncovered', 'uncovered'],
    ['isolated', 'isolated'],
  ];
  const presetButtons = new Map<GraphPreset, HTMLElement>();
  const setPreset = (preset: GraphPreset) => {
    const { focusId: _focus, ...rest } = filters;
    filters = { ...rest, preset };
    drawGraph(true);
  };
  presets.forEach(([value, key]) => {
    const b = button(el('presets'), key, () => setPreset(value));
    b.setAttribute('data-preset', value);
    presetButtons.set(value, b);
  });
  button(el('toolbar'), 'refresh', () => send('refresh'));
  button(el('toolbar'), 'reset', () => {
    filters = tools.defaults();
    selected = undefined;
    search.value = '';
    status.value = '';
    chainOn = false;
    send('reset');
    renderSnapshot(true);
  });
  const fit = () => svg.setAttribute('viewBox', bounds.join(' '));
  button(el('toolbar'), 'fit', fit);
  const zoom = (scale: number) => {
    const b = svg.viewBox.baseVal;
    svg.setAttribute(
      'viewBox',
      [
        b.x + (b.width * (1 - scale)) / 2,
        b.y + (b.height * (1 - scale)) / 2,
        b.width * scale,
        b.height * scale,
      ].join(' '),
    );
  };
  button(el('toolbar'), 'zoomIn', () => zoom(0.8));
  button(el('toolbar'), 'zoomOut', () => zoom(1.25));
  const chain = button(el('toolbar'), 'longest', () => {
    chainOn = !chainOn;
    decorate();
  });
  search.oninput = () => {
    filters = { ...filters, search: search.value };
    const exact = tools
      .visible(model, filters)
      .nodes.find((n) => n.id.toLowerCase() === search.value.trim().toLowerCase());
    if (exact) selected = exact.id;
    drawGraph(true);
  };
  status.onchange = () => {
    filters = { ...filters, statuses: status.value ? [status.value] : [] };
    drawGraph(true);
  };
  const toggleList = (
    host: HTMLElement,
    values: readonly string[],
    enabled: readonly string[],
    count: (value: string) => number,
    change: (next: string[]) => void,
  ) => {
    host.replaceChildren();
    values.forEach((value) => {
      const wrap = node('label', undefined, host);
      wrap.className = 'toggle';
      const input = node('input', undefined, wrap) as HTMLInputElement;
      input.type = 'checkbox';
      input.id = `${host.id}-${value}`;
      input.checked = enabled.includes(value);
      input.setAttribute('aria-label', value);
      input.onchange = () =>
        change(input.checked ? [...enabled, value] : enabled.filter((v) => v !== value));
      if (host.id === 'relations')
        node('span', undefined, wrap).className = 'relation-swatch ' + value;
      node('span', value, wrap);
      node('span', `${count(value)}`, wrap).className = 'count';
    });
  };
  const updateFilters = () => {
    // При локальном redraw checkbox заменяется вместе с counters; сохраняем keyboard focus.
    const focusedFilter = document.activeElement?.id;
    toggleList(
      el('kinds'),
      tools.kinds,
      filters.kinds,
      (v) => model.nodes.filter((n) => n.kind === v).length,
      (next) => {
        filters = { ...filters, kinds: next as GraphFilters['kinds'] };
        drawGraph(true);
      },
    );
    const types = tools.relations.filter((v) => model.edges.some((e) => e.type === v));
    toggleList(
      el('relations'),
      types,
      filters.relations,
      (v) => model.edges.filter((e) => e.type === v).length,
      (next) => {
        filters = { ...filters, relations: next as GraphFilters['relations'] };
        drawGraph(true);
      },
    );
    status.replaceChildren();
    const all = node('option', label('all'), status) as HTMLOptionElement;
    all.value = '';
    // Сохраняем выбранный status даже при нуле matches после watcher update.
    [...new Set([...filters.statuses, ...model.nodes.flatMap((n) => (n.status ? [n.status] : []))])]
      .sort()
      .forEach((value) => {
        const o = node('option', value, status) as HTMLOptionElement;
        o.value = value;
      });
    status.value = filters.statuses[0] ?? '';
    presetButtons.forEach((b, p) => b.setAttribute('aria-pressed', `${filters.preset === p}`));
    if (focusedFilter?.startsWith('kinds-') || focusedFilter?.startsWith('relations-'))
      document.getElementById(focusedFilter)?.focus();
  };
  const overview = () => {
    const data = tools.overview(model),
      host = el('overview');
    host.replaceChildren();
    el('project-name').textContent = data.projectName ?? root;
    el('root').textContent = root;
    el('release').textContent = data.release ? `Harness ${data.release}` : '';
    const metric = (key: string, value: string | number, problem = false) => {
      const card = node('div', undefined, host);
      card.className = `metric${problem ? ' problem' : ''}`;
      node('span', label(key), card).className = 'metric-label';
      node('strong', `${value}`, card);
    };
    if (data.integrity) metric('integrity', data.integrity, data.integrity === 'degraded');
    for (const key of ['artifacts', 'relationships', 'blockers', 'missingReferences'] as const) {
      const value = data[key];
      if (value !== undefined)
        metric(key, value, ['blockers', 'missingReferences'].includes(key) && value > 0);
    }
    if (data.relationshipCoveragePercent !== undefined)
      metric('relationshipCoverage', `${data.relationshipCoveragePercent}%`);
    if (data.cycles !== undefined) metric('cycles', data.cycles, data.cycles > 0);
  };
  const health = () => {
    const h = tools.health(model),
      host = el('health-values');
    host.replaceChildren();
    const shortcuts: Record<string, GraphPreset> = {
      blockers: 'blockers',
      missingReferences: 'missing',
      uncovered: 'uncovered',
      isolated: 'isolated',
      cycles: 'cycles',
    };
    Object.entries(h.counts).forEach(([key, value]) => {
      if (value === undefined) return;
      const b = button(host, key, () => {
        const preset = shortcuts[key];
        if (preset) setPreset(preset);
        else el('diagnostics').scrollIntoView({ block: 'nearest' });
      });
      b.textContent = `${label(key)} · ${value}`;
      b.className = value > 0 ? 'health-count problem' : 'health-count';
    });
    const summary = tools.overview(model);
    for (const key of ['reviews', 'skills'] as const) {
      if (summary[key] !== undefined) node('span', `${label(key)} · ${summary[key]}`, host);
    }
    const coverage = el('coverage');
    coverage.replaceChildren();
    h.coverage.forEach((v) => node('span', `${label(v.key)}: ${v.value}`, coverage));
    const diagnostics = el('diagnostics');
    diagnostics.replaceChildren();
    tools.diagnosticLines(model).forEach((d) => {
      const row = node('div', undefined, diagnostics);
      row.className = 'diagnostic';
      node('strong', d.code, row);
      d.fields.forEach((f) => node('div', `${label(f.key)}: ${f.value}`, row));
    });
    if (!model.diagnostics?.length)
      node('p', label('noDiagnostics'), diagnostics).className = 'muted';
  };
  const choose = (id: string, notify = true) => {
    selected = id;
    decorate();
    inspector();
    if (notify) send('select', id);
  };
  function inspector(): void {
    const host = el('graph-inspector');
    host.replaceChildren();
    const data = tools.inspector(model, selected);
    if (!data) {
      node('p', label('emptyInspector'), host).className = 'empty-inspector';
      return;
    }
    node('span', data.kind, host).className = `type-badge kind-${data.kind}`;
    node('h3', data.id, host);
    if (data.title) node('p', data.title, host).className = 'artifact-title';
    if (data.status)
      node('span', data.status, host).className = `status-badge status-${data.status}`;
    if (data.kind === 'MISSING') node('p', label('missing'), host).className = 'problem';
    if (data.path) button(host, 'open', () => send('open', data.id));
    button(host, 'related', () => {
      filters = { ...tools.defaults(data.id) };
      search.value = '';
      drawGraph(true);
      send('related', data.id);
    });
    const dl = node('dl', undefined, host);
    if (data.path) {
      node('dt', label('path'), dl);
      node('dd', data.path, dl);
    }
    data.fields.forEach((f) => {
      node('dt', label(f.key), dl);
      node('dd', f.value, dl);
    });
    if (data.impact !== undefined) {
      node('dt', label('downstreamImpact'), dl);
      node('dd', `${data.impact}`, dl);
    }
    if (data.causes.length) {
      node('h4', label('planStaleCauses'), host);
      const list = node('ul', undefined, host);
      data.causes.forEach((c) => node('li', c, list));
    }
    if (data.remediation) {
      node('h4', label('planRemediation'), host);
      const text = node('input', undefined, host) as HTMLInputElement;
      text.readOnly = true;
      text.value = data.remediation;
      text.setAttribute('aria-label', label('planRemediation'));
      text.className = 'remediation';
      button(host, 'copy', () => {
        text.focus();
        text.select();
        void navigator.clipboard?.writeText(data.remediation ?? '').catch(() => {
          /* Выделенный текст остаётся доступен для Ctrl+C, если clipboard API недоступен. */
        });
      });
    }
    if (data.groups.length) {
      node('h4', label('executionGroups'), host);
      data.groups.forEach((g) => {
        const block = node('div', undefined, host);
        block.className = 'execution-group';
        node('strong', g.id, block);
        if (g.count !== undefined) node('div', `${label('stepsCount')}: ${g.count}`, block);
        if (g.parallel !== undefined)
          node('div', `${label('parallel')}: ${label(g.parallel ? 'yes' : 'no')}`, block);
        if (g.dependsOn.length)
          node('div', `${label('dependsOn')}: ${g.dependsOn.join(', ')}`, block);
      });
    }
    if (data.kind === 'MISSING')
      tools
        .diagnosticLines(model)
        .filter((d) => d.fields.some((f) => f.key === 'target' && `MISSING:${f.value}` === data.id))
        .forEach((d) => {
          node('strong', d.code, host);
          d.fields.forEach((f) => node('p', `${label(f.key)}: ${f.value}`, host));
        });
    for (const [direction, list] of [
      ['incoming', data.incoming],
      ['outgoing', data.outgoing],
    ] as const) {
      if (!list.length) continue;
      node('h4', label(direction), host);
      for (const type of tools.relations) {
        const related = list.filter((e) => e.type === type);
        if (!related.length) continue;
        node('span', type, host).className = 'relation-type';
        related.forEach((e) => {
          const other = e.from === data.id ? e.to : e.from;
          const b = button(host, 'related', () => {
            const shown = tools.visible(model, filters);
            if (!shown.nodes.some((n) => n.id === other)) {
              filters = tools.defaults();
              search.value = '';
              drawGraph(true);
            }
            choose(other);
          });
          b.className = 'relation';
          b.textContent = `${e.from} → ${e.to}`;
          node('small', `${label('provenance')}: ${e.declaredBy.join(', ')}`, b);
        });
      }
    }
  }
  function decorate(): void {
    const cycles = new Set(tools.cycleMembers(model)),
      members = new Set(tools.longestChain(model)),
      related = new Set<string>(selected ? [selected] : []);
    model.edges.forEach((e) => {
      if (e.from === selected) related.add(e.to);
      if (e.to === selected) related.add(e.from);
    });
    groups.forEach((g, id) => {
      const n = model.nodes.find((v) => v.id === id);
      if (!n) return;
      g.setAttribute(
        'class',
        `node kind-${n.kind} status-${n.status ?? ''}${cycles.has(id) ? ' cycle' : ''}${chainOn && members.has(id) ? ' chain' : ''}${selected && !related.has(id) ? ' dim' : ''}${selected === id ? ' selected' : ''}`,
      );
      g.setAttribute('aria-pressed', `${selected === id}`);
    });
    const ordered = tools.longestChain(model),
      // STEP-019/F-001: API задаёт порядок chain независимо от wire direction depends_on.
      // Подсвечиваем только существующее canonical edge между соседними IDs, не меняя его direction.
      chainPairs = new Set(
        ordered.slice(0, -1).map((id, index) => [id, ordered[index + 1]].sort().join('\0')),
      );
    edges.forEach((e) =>
      e.element.setAttribute(
        'class',
        `edge ${e.type}${chainOn && e.type === 'depends_on' && chainPairs.has([e.from, e.to].sort().join('\0')) ? ' chain' : ''}${selected && e.from !== selected && e.to !== selected ? ' dim' : ''}${selected && (e.from === selected || e.to === selected) ? ' selected' : ''}`,
      ),
    );
    chain.setAttribute('aria-pressed', `${chainOn}`);
    (chain as HTMLButtonElement).disabled = !ordered.length;
  }
  function drawGraph(resetViewport = false): void {
    updateFilters();
    svg.replaceChildren();
    groups.clear();
    edges.splice(0);
    const graph = tools.visible(model, filters),
      geometry = layout(graph);
    bounds = geometry.bounds;
    const state = el('state');
    state.textContent = model.error ?? (!graph.nodes.length ? label('empty') : '');
    state.className = model.error ? 'problem' : 'muted';
    const defs = item('defs', {}),
      marker = item(
        'marker',
        {
          id: 'arrow',
          viewBox: '0 0 10 10',
          refX: 9,
          refY: 5,
          markerWidth: 6,
          markerHeight: 6,
          orient: 'auto',
        },
        defs,
      );
    item(
      'path',
      { d: 'M 0 0 L 10 5 L 0 10 z', fill: 'var(--vscode-descriptionForeground)' },
      marker,
    );
    const clip = item('clipPath', { id: 'node-label-clip' }, defs);
    item('rect', { x: 8, y: 0, width: 204, height: 96 }, clip);
    const positions = new Map(geometry.nodes.map((n) => [n.id, n]));
    tools.kinds.forEach((kind) => {
      const lane = geometry.nodes.filter((n) => n.lane === kind);
      if (!lane.length) return;
      const h = item('text', {
        x: Math.min(...lane.map((n) => n.x)),
        y: Math.min(...lane.map((n) => n.y)) - 14,
        class: 'lane-label',
      });
      h.textContent = `${kind} · ${lane.length}`;
    });
    graph.edges.forEach((e) => {
      const a = positions.get(e.from),
        b = positions.get(e.to);
      if (!a || !b) return;
      const ax = a.x + a.width / 2,
        ay = a.y + a.height / 2,
        bx = b.x + b.width / 2,
        by = b.y + b.height / 2;
      const dx = bx - ax,
        dy = by - ay,
        scale = Math.min(
          (a.width / 2 + 7) / (Math.abs(dx) || 1),
          (a.height / 2 + 7) / (Math.abs(dy) || 1),
        );
      const endScale = Math.min(
        (b.width / 2 + 9) / (Math.abs(dx) || 1),
        (b.height / 2 + 9) / (Math.abs(dy) || 1),
      );
      const sx = ax + dx * scale,
        sy = ay + dy * scale,
        tx = bx - dx * endScale,
        ty = by - dy * endScale;
      const reverse = graph.edges.some((v) => v.from === e.to && v.to === e.from),
        curve = reverse ? 28 : 12;
      const d =
        e.from === e.to
          ? `M ${a.x + a.width - 20} ${a.y} C ${a.x + a.width + 60} ${a.y - 65} ${a.x + a.width + 60} ${a.y + a.height + 65} ${a.x + a.width + 9} ${a.y + a.height / 2}`
          : `M ${sx} ${sy} Q ${(sx + tx) / 2 - (dy / Math.max(1, Math.hypot(dx, dy))) * curve} ${(sy + ty) / 2 + (dx / Math.max(1, Math.hypot(dx, dy))) * curve} ${tx} ${ty}`;
      const path = item('path', {
        d,
        class: `edge ${e.type}`,
        'marker-end': 'url(#arrow)',
        'data-source': e.from,
        'data-target': e.to,
      });
      item('title', {}, path).textContent =
        `${e.from} → ${e.to} · ${e.type} · ${label('provenance')}: ${e.declaredBy.join(', ')}`;
      edges.push({ element: path, from: e.from, to: e.to, type: e.type });
    });
    graph.nodes.forEach((n) => {
      const p = positions.get(n.id);
      if (!p) return;
      const g = item('g', {
        transform: `translate(${p.x},${p.y})`,
        tabindex: 0,
        role: 'button',
        'aria-label': `${n.id}${n.title ? ` ${n.title}` : ''}`,
        'aria-description': n.title ?? n.kind,
      });
      groups.set(n.id, g);
      item('rect', { width: p.width, height: p.height, rx: 6 }, g);
      item('rect', { width: 5, height: p.height, rx: 2, class: 'type-stripe' }, g);
      const line = (value: string, y: number, cls = '') => {
        const t = item(
          'text',
          { x: 12, y, 'clip-path': 'url(#node-label-clip)', class: cls },
          g,
        ) as SVGTextElement;
        t.textContent = value;
        // Binary search ограничивает синхронные SVG measurements для больших snapshots.
        if (t.getComputedTextLength() > 198) {
          const characters = Array.from(value);
          let low = 0,
            high = characters.length;
          while (low < high) {
            const middle = Math.ceil((low + high) / 2);
            t.textContent = characters.slice(0, middle).join('') + '…';
            if (t.getComputedTextLength() <= 198) low = middle;
            else high = middle - 1;
          }
          t.textContent = characters.slice(0, low).join('') + '…';
        }
        return t;
      };
      line(n.id, 23, 'node-id');
      line(n.title ?? n.kind, 46);
      line(n.kind, 70, 'node-kind');
      if (n.status) line(n.status, 86, 'node-status');
      item('title', {}, g).textContent = `${n.id}\n${n.title ?? ''}\n${n.status ?? ''}`;
      const target = g;
      target.onclick = () => choose(n.id);
      target.ondblclick = () => {
        if (n.kind !== 'MISSING' && n.path) send('open', n.id);
      };
      target.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          choose(n.id);
        }
      };
    });
    decorate();
    inspector();
    if (resetViewport || firstReady) {
      // Начальный масштаб сохраняет читаемый текст; обзор всех regions доступен отдельным Fit.
      const rect = svg.getBoundingClientRect();
      const width = Math.min(Math.max(440, rect.width / 0.8), bounds[2] ?? 1000),
        height = Math.min(Math.max(320, rect.height / 0.8), bounds[3] ?? 600);
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const focus = filters.focusId ? positions.get(filters.focusId) : undefined;
      if (focus)
        svg.setAttribute(
          'viewBox',
          `${Math.max(0, focus.x - width / 2)} ${Math.max(0, focus.y - height / 2)} ${width} ${height}`,
        );
    }
    if (model.state === 'ready') firstReady = false;
  }
  const dataKey = (m: DependencyGraphPresentation) =>
    JSON.stringify([
      m.state,
      m.error,
      m.nodes,
      m.edges,
      m.summary,
      m.insights,
      m.diagnostics,
      m.project,
      m.integrity,
    ]);
  function renderSnapshot(reset = false): void {
    overview();
    health();
    drawGraph(reset);
    fingerprint = dataKey(model);
  }
  svg.onwheel = (e) => {
    e.preventDefault();
    zoom(e.deltaY > 0 ? 1.12 : 0.89);
  };
  // Pan доступен также без pointer; Enter на node по-прежнему выбирает canonical ID.
  svg.setAttribute('aria-keyshortcuts', 'ArrowUp ArrowDown ArrowLeft ArrowRight Home');
  svg.setAttribute('aria-description', label('canvasHelp'));
  svg.onkeydown = (e) => {
    if (e.key === 'Home') {
      e.preventDefault();
      fit();
      return;
    }
    const direction: Record<string, readonly [number, number]> = {
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
    };
    const offset = direction[e.key];
    if (!offset) return;
    e.preventDefault();
    const b = svg.viewBox.baseVal;
    svg.setAttribute(
      'viewBox',
      [b.x + offset[0] * b.width * 0.1, b.y + offset[1] * b.height * 0.1, b.width, b.height].join(
        ' ',
      ),
    );
  };
  svg.onpointerdown = (e) => {
    if ((e.target as Element).closest('.node')) return;
    const b = svg.viewBox.baseVal;
    drag = { x: e.clientX, y: e.clientY, box: [b.x, b.y, b.width, b.height] };
    svg.setPointerCapture(e.pointerId);
  };
  svg.onpointermove = (e) => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect(),
      [x = 0, y = 0, w = 1000, h = 600] = drag.box;
    svg.setAttribute(
      'viewBox',
      [
        x - ((e.clientX - drag.x) * w) / rect.width,
        y - ((e.clientY - drag.y) * h) / rect.height,
        w,
        h,
      ].join(' '),
    );
  };
  svg.onpointerup = () => {
    drag = undefined;
  };
  svg.onpointercancel = () => {
    drag = undefined;
  };
  window.addEventListener(
    'message',
    (e: MessageEvent<{ type: string; model: DependencyGraphPresentation }>) => {
      if (e.data?.type !== 'model') return;
      const next = e.data.model,
        newNavigation = (next.navigationRevision ?? 0) !== navigation,
        changed = dataKey(next) !== fingerprint;
      model = next;
      navigation = next.navigationRevision ?? 0;
      if (newNavigation) {
        filters = tools.defaults(next.focusId);
        selected = next.selectedId;
        search.value = '';
        status.value = '';
        chainOn = false;
      } else {
        // Только ready snapshot может подтвердить исчезновение ID; loading/error не отменяет intent.
        if (model.state === 'ready') {
          if (!model.nodes.some((n) => n.id === selected)) selected = undefined;
          if (filters.focusId && !model.nodes.some((n) => n.id === filters.focusId)) {
            const { focusId: _focus, ...rest } = filters;
            filters = rest;
          }
        }
      }
      if (changed || newNavigation) renderSnapshot(newNavigation);
      else {
        decorate();
        inspector();
      }
    },
  );
  renderSnapshot(true);
}
