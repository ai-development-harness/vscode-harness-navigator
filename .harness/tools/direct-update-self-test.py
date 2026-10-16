#!/usr/bin/env python3
"""#342: direct TO/latest и полная независимость установки от project artifacts."""
from pathlib import Path
import json
import os
import subprocess
import runpy
import tempfile
from unittest.mock import patch

from harness_update import apply_update, check_update

HELPERS = runpy.run_path(str(Path(__file__).with_name('update-engine-self-test.py')))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='harness-direct-update-') as tmp:
        root = Path(tmp)
        states = {
            'malformed-step': {'planning/tasks/STEP-001.md': b'---\nstatus: [broken\n'},
            'non-utf8-step': {'planning/tasks/STEP-001.md': b'\xff\x00\xfe'},
            'historical-review': {'planning/reviews/STEP-001/REVIEW-old.md': b'---\ncontract_basis: sha256:old\nverdict: pass\n---\nHistorical review without dependency basis.\n'},
            'stale-architecture': {'docs/architecture.md': b'Descriptive change after historical review.\n'},
            'stale-projections': {'planning/STATUS.md': b'outdated projection\n', 'docs/requirements/STATUS.md': b'outdated\n'},
            'missing-review': {'planning/tasks/STEP-001.md': b'---\nstatus: completed\n---\nNo REVIEW\n'},
            'cycle': {'planning/tasks/STEP-001.md': b'---\ndepends_on: [STEP-002]\n---\n', 'planning/tasks/STEP-002.md': b'---\ndepends_on: [STEP-001]\n---\n'},
            'failed-verification': {'planning/tasks/STEP-001.md': b'## Verification\n- command: `python3 .harness/tools/validate.py --mode manual`\n## Evidence\nFAIL\n'},
            'malformed-req-adr': {'docs/requirements/REQ-001.md': b'---\ninvalid: [\n', 'docs/adr/ADR-001.md': b'\xff'},
            'custom-template': {'planning/tasks/TEMPLATE.md': b'Project-owned template\n'},
        }
        for name, files in states.items():
            folder = root / name; folder.mkdir()
            source, project = HELPERS['synthetic_pair'](folder, base={}, target={'.harness/tools/harness_update.py': '# final target\n'})
            # Initialized state — локальная настройка manifest, а не project init.
            manifest = project / '.harness/manifest.yaml'
            manifest.write_text(manifest.read_text().replace('initialized: false', 'initialized: true'))
            for rel, content in files.items():
                path = project / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
            if name == 'non-utf8-step' and os.name != 'nt':
                odd = os.fsdecode(b'planning/tasks/STEP-raw-\xff.md')
                files[odd] = b'opaque user artifact filename\n'
                (project / odd).write_bytes(files[odd])
                subprocess.run(['git', 'add', '--', odd], cwd=project, check=True)
            index = (project / '.git/index').read_bytes()
            # Ни обход графа STEP, ни даже запуск старого/нового full validator
            # не должен произойти при CHECK или APPLY.
            with patch('planning_contract.step_completion_proof', side_effect=AssertionError('updater read STEP')):
                checked = check_update(project, source_url=str(source))
                assert checked['route'] == ['v1.0.0', 'v1.1.0'], checked
                result = apply_update(project, source_url=str(source))
            assert result['status'] == 'UPDATED' and result['current'] == 'v1.1.0', result
            assert result['reloadRequired'] is True
            assert len(result['reports']) == 1
            for rel, content in files.items():
                assert (project / rel).read_bytes() == content, (name, rel)
            assert (project / '.git/index').read_bytes() == index, name
            repeated = apply_update(project, source_url=str(source))
            assert repeated['status'] == 'NO_UPDATE' and not repeated['repositoryMutated'], repeated
        # Explicit TO вообще не читает moving catalog: повреждённая metadata
        # default branch не подменяет выбранный immutable tag и не строит route.
        folder = root / 'explicit'; folder.mkdir()
        source, project = HELPERS['synthetic_pair'](folder, base={}, target={})
        with patch('harness_update._read_graph', side_effect=AssertionError('explicit TO read catalog')):
            result = apply_update(project, target='v1.1.0', source_url=str(source))
        assert result['route'] == ['v1.0.0', 'v1.1.0']
        # Явный TO допускает осознанный возврат к immutable release.
        backward = apply_update(project, target='v1.0.0', source_url=str(source))
        assert backward['status'] == 'UPDATED' and backward['current'] == 'v1.0.0', backward
        assert json.loads((project / '.harness/harness.lock.json').read_text())['source']['ref'] == 'v1.0.0'
    print(f'DIRECT UPDATE SELF-TEST: PASS ({len(states)} artifact states, latest/TO/downgrade)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
