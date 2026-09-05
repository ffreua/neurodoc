import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_env(path):
    result = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError(f'Invalid environment key at line {number}')
        if key in result:
            raise ValueError(f'Duplicate environment key: {key}')
        if value.startswith('"'):
            value = json.loads(value)
        if not isinstance(value, str) or any(c in value for c in '\x00\r\n'):
            raise ValueError(f'Invalid environment value for {key}')
        result[key] = value
    return result


def secret(name, required=True):
    file_name = os.environ.get(f'{name}_FILE')
    direct = os.environ.get(name)
    if file_name and direct is not None:
        raise ValueError(f'Ambiguous secret configuration: {name}')
    value = Path(file_name).read_text().rstrip('\r\n') if file_name else direct
    if required and (not value or value == 'DISABLED'):
        raise ValueError(f'Missing secret: {name}')
    return value or ''


def write_env(path, values):
    lines = []
    for key, value in values.items():
        value = str(value)
        # Generated env_files contain non-sensitive configuration only.
        if any(c in value for c in '\r\n\x00$'):
            raise ValueError(f'Unsafe Docker env_file interpolation: {key}')
        lines.append(f'{key}={value}')
    Path(path).write_text('\n'.join(lines) + '\n')
    Path(path).chmod(0o600)
