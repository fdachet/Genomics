from build_artifacts import read_record
from runtime_source_status import runtime_source_status


def compilation_status(state, component):
    kind = str(component.get('kind', '') or '').strip().lower()
    if kind != 'source':
        return {'required': 'No', 'status': 'NOT REQUIRED', 'version': '', 'detail': 'This component is not compiled by Tab 4.'}
    existing = runtime_source_status(state, component)
    if existing:
        return {'required': 'No' if existing['verified'] else 'Verify runtime',
                'status': 'INSTALLED IN RUNTIME' if existing['verified'] else 'UNVERIFIED IN RUNTIME', 'version': existing['version'],
                'detail': existing['path'] + ' — ' + existing['source']}
    if not component.get('enabled', True):
        return {'required': 'No (disabled)', 'status': 'DISABLED', 'version': '', 'detail': 'Enable this source component in Tab 3 to compile it.'}
    name = str(component.get('name', '') or '').strip()
    record, detail = read_record(state, component)
    failures = state.get('compilation_failures', {})
    failure = failures.get(name) if isinstance(failures, dict) else None
    if isinstance(failure, dict):
        return {'required': 'Yes', 'status': 'FAILED', 'version': '', 'detail': str(failure.get('error', '') or 'Previous compilation failed.')}
    if record:
        return {'required': 'Yes', 'status': 'COMPILED', 'version': str(record.get('version', '') or ''), 'detail': str(record.get('artifact', '') or '')}
    records = state.get('compiled_artifacts', {})
    previous = records.get(name) if isinstance(records, dict) else None
    if isinstance(previous, dict):
        return {'required': 'Yes', 'status': 'OUTDATED', 'version': '', 'detail': detail}
    return {'required': 'Yes', 'status': 'NOT COMPILED', 'version': '', 'detail': detail}
