#!/usr/bin/env python3
"""Release gate: direct install on disposable copies of initialized canary.

Deliberately invalid project documents must survive byte-for-byte. No full
project validator is a gate for these copies; the pristine qualification lane
continues to validate normal project operation separately.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from harness_config import (task_directory, review_directory, requirements_directory,
                            adr_directory, architecture_path, status_path, update_report_directory,
                            load_update_policy)
from harness_update import _ownership, _classify
from document_contract import markdown_headings
from planning_contract import architecture_refs, read_task, planning_context_basis, _heading_slug


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        # Git executor возвращает причину в JSON stdout. Сохраняем только
        # machine code, чтобы qualification не теряла blocker и не раскрывала
        # произвольные diagnostics/пути из дочернего процесса.
        reason = 'SUBPROCESS_FAILED'
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            payload = None
        code = payload.get('reasonCode') if isinstance(payload, dict) else None
        if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', code):
            reason = code
        raise RuntimeError(f'canary command failed ({result.returncode}): {reason}')
    return result.stdout.strip()


def snapshot(root: Path, policies: list[dict]) -> dict:
    """Unmanaged content, symlink targets and modes, including dirty/untracked files."""
    reports = update_report_directory(root).relative_to(root).as_posix() + '/'
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in {'.git', '__pycache__'}]
        for name in files + [name for name in dirs if (Path(directory) / name).is_symlink()]:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if (rel.startswith(('.harness/local/', reports)) or rel == '.harness/harness.lock.json'
                    or any(_classify(rel, policy) for policy in policies)):
                continue
            data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            result[rel] = [hashlib.sha256(data).hexdigest(), stat.S_IMODE(path.lstat().st_mode)]
    return result


def qualify(baseline: Path, mirror: Path, target: str) -> dict:
    engine = Path(__file__).with_name('harness-update.py')
    candidate_policy = _ownership(load_update_policy(Path(__file__).resolve().parents[2]))
    states = ('unchanged', 'historical-review', 'historical-review-stale-architecture',
              'stale-projections', 'missing-step', 'malformed-step', 'non-utf8-step',
              'cyclic-steps', 'missing-review', 'failed-verification', 'malformed-req-adr',
              'custom-templates', 'dirty-staged-untracked', 'artifact-symlink',
              'unmerged-artifact-index', 'non-utf8-artifact-name',
              'publication-history', 'publication-history-stale-architecture',
              'shared-project-regular', 'shared-project-executable',
              'shared-project-dirty', 'shared-project-filemode-disabled',
              'shared-project-deleted')
    records = []
    with tempfile.TemporaryDirectory(prefix='harness-artifact-canary-') as temporary:
        for number, state in enumerate(states):
            work = Path(temporary) / state
            run(['git', 'clone', '--quiet', '--no-local', str(baseline), str(work)], baseline)
            policies = [_ownership(load_update_policy(work)), candidate_policy]
            tasks, reviews = task_directory(work), review_directory(work)
            reqs, adrs = requirements_directory(work), adr_directory(work)
            steps = sorted(tasks.glob('STEP-*.md'))
            subject = steps[0] if steps else tasks / 'STEP-991.md'
            def write(path: Path, content: bytes):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            if state == 'publication-history-stale-architecture':
                # Меняем prose существующего referenced раздела; REVIEW и его
                # basis остаются настоящими неизменёнными артефактами canary.
                task = next(read_task(work, path.stem) for path in steps
                            if architecture_refs(read_task(work, path.stem)))
                sid = task['frontmatter']['id']
                ref = architecture_refs(task)[0]
                rel, _, anchor = ref.partition('#')
                path = work / rel
                text = path.read_text(encoding='utf-8')
                lines = text.splitlines(keepends=True)
                selected = next(index for index, _level, title in markdown_headings(text)
                                if not anchor or _heading_slug(title) == anchor)
                prior_basis = planning_context_basis(work, sid)
                lines.insert(selected + 1, '\nУточнение описания после исторической приёмки.\n')
                path.write_text(''.join(lines), encoding='utf-8')
                assert planning_context_basis(work, sid) != prior_basis, ref
            if state.startswith('publication-history'):
                # Подготовка disposable baseline отделена от публикации update.
                # Все последующие commit/push исполняет настоящий Git executor.
                # Actions checkout exact SHA не обязан иметь локальные ветки.
                # Публикационный fixture создаёт собственную disposable ветку;
                # production DETACHED_HEAD gate при этом остаётся строгим.
                run(['git', 'switch', '-c', 'codex/qualification-publication'], work)
                run(['git', 'config', 'user.name', 'Harness Canary'], work)
                run(['git', 'config', 'user.email', 'canary@example.invalid'], work)
                if state.endswith('architecture'):
                    run(['git', 'add', '--', str(path.relative_to(work))], work)
                    run(['git', 'commit', '-m', 'docs: уточнить описание архитектуры'], work)
                remote = Path(temporary) / (state + '.git')
                run(['git', 'clone', '--quiet', '--bare', str(work), str(remote)], work)
                run(['git', 'remote', 'set-url', 'origin', str(remote)], work)
            if state.startswith('historical-review'):
                # Immutable legacy reports lack fields introduced by newer contracts.
                for report in reviews.glob('STEP-*/REVIEW-*.md'):
                    text = report.read_text()
                    text = re.sub(r'(?m)^(?:dependency_completion_basis|reviewed_subject_content_hash):.*\n', '', text)
                    report.write_text(text)
                write(reviews / 'STEP-991/REVIEW-historical.md',
                      b'---\nverdict: PASS\ncontract_basis: sha256:historical\n---\nHistorical immutable review.\n')
                if state.endswith('architecture'):
                    path = architecture_path(work)
                    write(path, path.read_bytes() + b'\nDescriptive architecture change after review.\n')
            elif state == 'stale-projections':
                write(status_path(work), b'outdated project status\n')
                write(reqs / 'STATUS.md', b'outdated requirements status\n')
            elif state == 'missing-step':
                subject.unlink(missing_ok=True)
            elif state == 'malformed-step':
                write(subject, b'---\nstatus: [invalid\n')
            elif state == 'non-utf8-step':
                write(subject, b'\xff\x00\xfe')
            elif state == 'cyclic-steps':
                write(tasks / 'STEP-991.md', b'---\nid: STEP-991\ndepends_on: [STEP-992]\n---\n')
                write(tasks / 'STEP-992.md', b'---\nid: STEP-992\ndepends_on: [STEP-991]\n---\n')
            elif state == 'missing-review':
                for report in reviews.glob('STEP-*/REVIEW-*.md'):
                    report.unlink()
            elif state == 'failed-verification':
                write(subject, b'---\nstatus: completed\n---\n## Verification\n- `python3 .harness/tools/validate.py --mode manual`\n## Evidence\nFAIL\n')
            elif state == 'malformed-req-adr':
                write(reqs / 'REQ-991-invalid.md', b'---\nstatus: [\n')
                write(adrs / 'ADR-991-invalid.md', b'\xff')
            elif state == 'custom-templates':
                for folder in (tasks, reviews, reqs, adrs):
                    write(folder / 'TEMPLATE.md', b'Project-specific template, older schema\n')
            elif state == 'dirty-staged-untracked':
                write(subject, subject.read_bytes() + b'\nstaged user change\n' if subject.exists() else b'staged\n')
                run(['git', 'add', '--', str(subject.relative_to(work))], work)
                write(subject, subject.read_bytes() + b'\nunstaged user change\n')
                write(tasks / 'STEP-992.md', b'untracked incomplete draft\n')
            elif state == 'unmerged-artifact-index':
                rel = subject.relative_to(work).as_posix()
                objects = [run(['git', 'hash-object', '-w', '--', str(subject)], work)]
                # Distinct valid blob objects in three conflict stages; the
                # working file and conflict index must remain untouched.
                for content in (b'ours\n', b'theirs\n'):
                    proc = subprocess.run(['git', 'hash-object', '-w', '--stdin'], cwd=work,
                                          input=content, capture_output=True, check=True)
                    objects.append(proc.stdout.decode().strip())
                data = f'0 {"0" * 40}\t{rel}\n' + ''.join(
                    f'100644 {oid} {stage}\t{rel}\n'
                    for stage, oid in enumerate(objects, 1))
                subprocess.run(['git', 'update-index', '--index-info'], cwd=work,
                               input=data.encode(), check=True)
            elif state == 'non-utf8-artifact-name':
                if os.name == 'nt':
                    records.append({'state': state, 'status': 'UNSUPPORTED_PLATFORM'})
                    continue
                odd = tasks / os.fsdecode(b'STEP-opaque-\xff.md')
                write(odd, b'user document with opaque filename\n')
                run(['git', 'add', '--', str(odd.relative_to(work))], work)
            elif state == 'artifact-symlink':
                if os.name == 'nt':
                    records.append({'state': state, 'status': 'UNSUPPORTED_PLATFORM'})
                    continue
                subject.unlink(missing_ok=True)
                subject.symlink_to('missing-user-artifact.md')
            shared_path = work / '.github/local-update-mode-repro.yml'
            shared_before = None
            if state.startswith('shared-project-'):
                # #352: настоящий tracked shared path, отсутствующий в BASE и
                # TARGET. Отдельный snapshot нужен: общий исключает shared.
                rel = shared_path.relative_to(work).as_posix()
                assert all(_classify(rel, policy) == 'shared' for policy in policies), rel
                for ref in (run(['git', 'rev-parse', 'HEAD'], work), target):
                    repository = work if ref != target else mirror
                    entry = run(['git', '-C', str(repository), 'ls-tree', ref, '--', rel], work)
                    assert not entry, (state, ref, entry)
                run(['git', 'config', 'core.filemode',
                     'false' if state.endswith('disabled') else 'true'], work)
                write(shared_path, b'version: 2\nupdates: []\n')
                shared_path.chmod(0o755 if state.endswith('executable') else 0o644)
                run(['git', 'add', '--', rel], work)
                run(['git', '-c', 'user.name=Harness Canary',
                     '-c', 'user.email=canary@example.invalid', 'commit', '-m',
                     'test: добавить проектный shared-файл'], work)
                if state.endswith('dirty'):
                    write(shared_path, b'version: 2\nupdates: []\n# staged\n')
                    run(['git', 'add', '--', rel], work)
                    with shared_path.open('ab') as stream:
                        stream.write(b'# unstaged\r\n')
                elif state.endswith('deleted'):
                    shared_path.unlink()
                if shared_path.exists():
                    shared_before = (shared_path.read_bytes(),
                                     stat.S_IMODE(shared_path.stat().st_mode),
                                     shared_path.stat().st_mtime_ns)
            def assert_shared_preserved():
                if not state.startswith('shared-project-'):
                    return
                actual = None if not shared_path.exists() else (
                    shared_path.read_bytes(), stat.S_IMODE(shared_path.stat().st_mode),
                    shared_path.stat().st_mtime_ns)
                assert actual == shared_before, (state, 'shared bytes/mode/mtime changed')
            before = snapshot(work, policies)
            index = (work / '.git/index').read_bytes()
            current = json.loads((work / '.harness/harness.lock.json').read_text())['source']['ref']
            # Alternate latest and explicit TO against the same exact candidate mirror.
            common = ['--root', str(work), '--source-url', str(mirror), '--json']
            if number % 2:
                common += ['--to', target]
            checked = json.loads(run([sys.executable, str(engine), 'check', *common], work))
            assert checked['status'] == 'PASS' and checked['route'] == [current, target], checked
            assert_shared_preserved()
            assert snapshot(work, policies) == before
            assert (work / '.git/index').read_bytes() == index
            applied = json.loads(run([sys.executable, str(engine), 'apply', *common], work))
            assert applied['status'] == 'UPDATED' and applied['current'] == target, applied
            assert applied['route'] == [current, target] and len(applied['reports']) == 1, applied
            assert_shared_preserved()
            assert snapshot(work, policies) == before, state
            assert (work / '.git/index').read_bytes() == index, state
            repeat = json.loads(run([sys.executable, str(engine), 'apply', *common], work))
            assert repeat['status'] == 'NO_UPDATE' and not repeat['repositoryMutated'], repeat
            assert_shared_preserved()
            assert snapshot(work, policies) == before, state
            assert (work / '.git/index').read_bytes() == index, state
            publication = {}
            if state.startswith('publication-history'):
                immutable = {str(path.relative_to(work)): path.read_bytes()
                             for path in reviews.rglob('*.md')}
                run([sys.executable, str(work / '.harness/tools/sync-projections.py')], work)
                if state.endswith('architecture'):
                    # Тот же настоящий исторический PASS допускает публикацию,
                    # но не становится актуальным prerequisite новой работы.
                    code = ("import sys; from pathlib import Path; "
                            "sys.path.insert(0, '.harness/tools'); "
                            "from planning_contract import step_completion_proof, historical_completion_projection_proof; "
                            f"assert not step_completion_proof(Path.cwd(), {sid!r})['complete']; "
                            f"assert historical_completion_projection_proof(Path.cwd(), {sid!r})['complete']")
                    run([sys.executable, '-c', code], work)
                for mode in ('commit', 'ci'):
                    run([sys.executable, str(work / '.harness/tools/validate.py'), '--mode', mode], work)
                message = work / '.harness/local/git/commit-message.txt'
                write(message, 'chore: обновить Harness\n\nУстановлено обновление; исторические REVIEW сохранены.\n'.encode('utf-8'))
                # Executor получает exact staged scope и повторяет validator
                # перед commit и push; remote существует только в temporary dir.
                run(['git', 'add', '--all'], work)
                committed = json.loads(run([sys.executable, str(work / '.harness/tools/git-action.py'),
                    'commit', '--commit-type', 'chore', '--slug', 'historical-update',
                    '--message-file', str(message), '--json'], work))
                assert committed['status'] == 'SUCCESS', committed
                pushed = json.loads(run([sys.executable, str(work / '.harness/tools/git-action.py'),
                    'push', '--json'], work))
                assert pushed['status'] == 'SUCCESS', pushed
                for rel, content in immutable.items():
                    assert (work / rel).read_bytes() == content, rel
                publication = {'commit': 'PASS', 'push': 'PASS', 'ciValidation': 'PASS',
                               'immutableReviews': len(immutable)}
            records.append({'state': state, 'status': 'PASS', 'protectedFiles': len(before),
                            **publication})
    return {'status': 'PASS', 'count': len(states), 'cases': records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-project', required=True, type=Path)
    parser.add_argument('--source-mirror', required=True, type=Path)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    try:
        payload = qualify(args.baseline_project.resolve(), args.source_mirror.resolve(), args.target)
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}))
        return 1
    print(json.dumps(payload))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
