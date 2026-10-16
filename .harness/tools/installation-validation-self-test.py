#!/usr/bin/env python3
"""Installation checks stay strict for service files and ignore project artifacts."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
from unittest.mock import patch
from installation_validation import installation_errors, update_transaction_active
from update_recovery import UPDATE_TRANSACTION_ENV


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='harness-installation-') as tmp:
        root = Path(tmp)
        def write(rel, data):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.encode() if isinstance(data, str) else data)
            return path
        write('.harness/manifest.yaml', 'harness:\n  version: "1"\n  release: "1.0.0"\nrepository:\n  harnessUpdatePolicy: .harness/harness-update.toml\n')
        write('.harness/harness-update.toml', '''[source]
repository = "example/harness"
[state]
lock_file = ".harness/harness.lock.json"
[ownership]
harness_owned = [".harness/tools/**", ".harness/harness-policy.toml"]
shared = [".harness/manifest.yaml"]
marker_merge = []
''')
        lock = {'schemaVersion': 1, 'release': '1.0.0', 'source': {'repository': 'example/harness', 'ref': 'v1.0.0'}}
        write('.harness/harness.lock.json', json.dumps(lock))
        service = write('.harness/tools/required.py', 'VALUE = 1\n')
        write('.harness/harness-policy.toml', 'required_files = [".harness/tools/required.py", "planning/tasks/STEP-001.md"]\n')
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', 'add', '--', '.harness'], cwd=root, check=True)
        # Opaque project content and unknown ignored service-neighbor files do not
        # become installation input merely because a broad glob covers a folder.
        write('planning/tasks/STEP-001.md', b'\xff\x00invalid')
        write('planning/STATUS.md', 'outdated\n')
        write('.harness/tools/local-ignored.py', 'this is not python !!!\n')
        assert installation_errors(root) == []
        service.unlink()
        assert any('missing managed installation file' in e for e in installation_errors(root))
        service.write_text('def broken(:\n')
        assert any('invalid managed installation file' in e for e in installation_errors(root))
        service.write_text('VALUE = 1\n')
        lock['source']['ref'] = 'v9.9.9'
        write('.harness/harness.lock.json', json.dumps(lock))
        assert any('lock does not match' in e for e in installation_errors(root))
        lock['source']['ref'] = 'v1.0.0'
        write('.harness/harness.lock.json', json.dumps(lock))
        if os.name != 'nt':
            service.unlink()
            service.symlink_to('/nonexistent-service')
            assert any('installation file' in e for e in installation_errors(root))
        # Only the legacy engine's exact live verifying capability selects the
        # installation profile. Ordinary manual/ci project validation stays full.
        with patch.dict(os.environ, {UPDATE_TRANSACTION_ENV: 'transaction'}):
            for identity, phase, expected in [('other', 'verifying', False),
                                               ('transaction', 'applying', False),
                                               ('transaction', 'verifying', True)]:
                with patch('installation_validation.load_journal', return_value={
                        'transactionId': identity, 'state': phase}):
                    assert update_transaction_active(root) is expected
    print('INSTALLATION VALIDATION SELF-TEST: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
