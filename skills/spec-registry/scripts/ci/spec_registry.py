#!/usr/bin/env python3
"""SPEC Registry governance CLI. Stdlib only. Does not modify project files."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

STATES = {'DISCOVERED','DRAFT','IN_REVIEW','APPROVED','IMPLEMENTING','VERIFIED','FROZEN','SUPERSEDED','CANCELLED'}
DEV_READY = {'APPROVED','IMPLEMENTING','VERIFIED','FROZEN'}
RELEASE_READY = {'VERIFIED','FROZEN'}
ID = re.compile(r'^SPEC-(\d+)$')
PREFIX = re.compile(r'(?i)^spec[-_](\d+)(?:\D|$)')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or '\\' in rel or ':' in rel or rel.startswith('/'):
        raise ValueError(f'Unsafe relative path: {rel!r}')
    full = (root / rel).resolve()
    if not full.is_relative_to(root.resolve()):
        raise ValueError(f'Path traversal: {rel!r}')
    return full


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('specs'), list):
        raise ValueError('Registry must be an object containing a specs list')
    return data


def check_registry(data: dict, root: Path, metadata_only: bool = False) -> list[str]:
    problems = []
    if data.get('schema_version') != '1.0':
        problems.append('schema_version must be 1.0')
    entries = data.get('specs', [])
    seen_id = set()
    seen_path = set()
    id_map = {}
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(f'Entry #{i}: expected an object')
            continue
        sid = item.get('spec_id')
        label = f'Entry #{i} {sid}'
        if not isinstance(sid, str) or not ID.fullmatch(sid):
            problems.append(f'{label}: invalid spec_id')
        if sid in seen_id:
            problems.append(f'{label}: duplicate spec_id')
        seen_id.add(sid)
        id_map[sid] = item
        state = item.get('status')
        if state not in STATES:
            problems.append(f'{label}: invalid status {state!r}')
        if not isinstance(item.get('title'), str) or not item['title'].strip():
            problems.append(f'{label}: title required')
        rel = item.get('path')
        if rel in seen_path:
            problems.append(f'{label}: duplicate path')
        seen_path.add(rel)
        try:
            file = safe_path(root, rel)
            if not metadata_only and not file.is_file():
                problems.append(f'{label}: missing file {rel}')
            digest = item.get('spec_sha256')
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                problems.append(f'{label}: invalid spec_sha256')
            if digest and not metadata_only and file.is_file() and sha256(file) != digest:
                problems.append(f'{label}: DRIFT file hash differs from frozen hash')
        except (TypeError, ValueError) as e:
            problems.append(f'{label}: {e}')
        for key in ('dependencies', 'verify_paths', 'qa_paths'):
            if not isinstance(item.get(key, []), list):
                problems.append(f'{label}: {key} must be a list')
                continue
            if key != 'dependencies':
                for p in item.get(key, []):
                    try:
                        safe_path(root, p)
                    except (TypeError, ValueError) as e:
                        problems.append(f'{label}: {key}: {e}')
        if state in DEV_READY and (not item.get('approved_by') or not item.get('approval_ref') or not item.get('spec_sha256')):
            problems.append(f'{label}: {state} needs human approval metadata and SHA-256')
    for item in entries:
        if not isinstance(item, dict):
            continue
        for dep in item.get('dependencies', []):
            if dep not in id_map:
                problems.append(f'{item.get("spec_id")}: dependency not indexed {dep}')
    return problems


def gate(data: dict, root: Path, sid: str, phase: str) -> list[str]:
    problems = check_registry(data, root)
    entries = {e['spec_id']: e for e in data['specs'] if isinstance(e, dict) and 'spec_id' in e}
    if sid not in entries:
        return problems + [f'Unknown spec ID: {sid}']
    e = entries[sid]
    required = DEV_READY if phase == 'dev' else RELEASE_READY
    if e.get('status') not in required:
        problems.append(f'{sid}: state {e.get("status")} not permitted for {phase} gate')
    for dep in e.get('dependencies', []):
        de = entries.get(dep)
        if not de or de.get('status') not in DEV_READY:
            problems.append(f'{sid}: unresolved dependency {dep}')
    if phase == 'release':
        if not e.get('verify_paths') or not e.get('qa_paths'):
            problems.append(f'{sid}: release requires tests and QA evidence')
        for k in ('verify_paths', 'qa_paths'):
            for rel in e.get(k, []):
                try:
                    if not safe_path(root, rel).is_file():
                        problems.append(f'{sid}: missing {k} artifact {rel}')
                except (TypeError, ValueError) as error:
                    problems.append(f'{sid}: invalid {k} path: {error}')
    return problems


def inventory(root: Path) -> list[dict]:
    out = []
    for d in ('handoff', 'docs', 'doc'):
        base = root / d
        if not base.is_dir():
            continue
        for file in sorted(base.rglob('*')):
            if not file.is_file() or file.suffix.lower() not in {'.md', '.txt'}:
                continue
            match = PREFIX.match(file.name)
            if match:
                out.append({'spec_id': f'SPEC-{int(match.group(1))}', 'path': file.relative_to(root).as_posix(), 'sha256': sha256(file)})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Read-only SPEC Registry checker (human approval never created by this script)')
    p.add_argument('command', choices=['inventory', 'validate', 'gate', 'summary'])
    p.add_argument('--root', type=Path, default=Path('.'), help='Root of AI Council repository')
    p.add_argument('--registry', type=Path, default=Path('registry/spec_registry.json'))
    p.add_argument('--metadata-only', action='store_true', help='Validate metadata without requiring referenced repository files')
    p.add_argument('--spec', help='SPEC-123, required for gate')
    p.add_argument('--phase', choices=['dev','release'], default='dev')
    a = p.parse_args(argv)
    if a.command == 'inventory':
        items = inventory(a.root.resolve())
        print(json.dumps({'files':len(items),'items':items}, ensure_ascii=False, indent=2))
        return 0
    try:
        data = load_registry(a.registry)
        if a.command == 'summary':
            print(json.dumps({'total':len(data['specs']), 'states':dict(Counter(e.get('status','UNKNOWN') for e in data['specs']))}, ensure_ascii=False, indent=2))
            return 0
        if a.command == 'gate':
            if not a.spec:
                p.error('--spec is required for gate')
            problems = gate(data, a.root.resolve(), a.spec, a.phase)
        else:
            problems = check_registry(data, a.root.resolve(), a.metadata_only)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 2
    if problems:
        for error in problems:
            print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print(f'PASS: SPEC Registry {a.command}')
    if a.command == 'gate':
        print('NOTICE: textual approval metadata is not proof of consent; require protected GitHub review/CODEOWNERS externally.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
