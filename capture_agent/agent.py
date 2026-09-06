"""Local folder-watching capture agent (S13-T09).

Runs on the scanning workstation (Windows, per P-08 -- the actual scanner
software/driver and each clinic's output directory are pending, see
docs/homologation/reports-capture.md). This script has no dependency on
that pending piece: it watches a plain local folder for finished image
files and POSTs them to the session-scoped upload endpoint
(integrations.capture_urls) over HTTPS. It was never run against a real
scanner; the logic below (stability detection, local queue, retry,
never-delete-by-default) was tested directly with plain files on disk.
"""

import hashlib
import json
import time
from pathlib import Path
from urllib import error, request

STABILITY_CHECKS = 2
STABILITY_INTERVAL_SECONDS = 1.0
UPLOAD_TIMEOUT_SECONDS = 30
QUEUE_FILENAME = '.capture_agent_queue.json'


class FileStillWriting(Exception):
    """Raised when a candidate file's size is still changing -- the agent
    must never read/hash/send a file the scanner software has not finished
    writing yet.
    """


def is_stable(path, checks=STABILITY_CHECKS, interval=STABILITY_INTERVAL_SECONDS):
    """A file is considered "done" only once its size stops changing
    across `checks` consecutive samples -- the simplest signal available
    without any scanner-specific "done" marker (P-08 has not defined one).
    """
    sizes = []
    for _ in range(checks):
        try:
            sizes.append(path.stat().st_size)
        except FileNotFoundError:
            return False
        time.sleep(interval)
    return len(set(sizes)) == 1 and sizes[0] > 0


def _load_queue(queue_path):
    if queue_path.exists():
        return json.loads(queue_path.read_text())
    return {'pending': [], 'sent': []}


def _save_queue(queue_path, queue):
    queue_path.write_text(json.dumps(queue, indent=2))


def scan_folder(watch_dir, queue_path):
    """Returns the list of file paths (as strings) newly found stable and
    not already recorded as sent -- never touches or deletes the original
    files; the local queue file is the only agent-owned state.
    """
    queue = _load_queue(queue_path)
    sent = set(queue['sent'])
    found = []
    for candidate in sorted(Path(watch_dir).iterdir()):
        if not candidate.is_file() or candidate.name == QUEUE_FILENAME:
            continue
        key = str(candidate)
        if key in sent:
            continue
        if is_stable(candidate):
            found.append(key)
    return found, queue


def upload_page(base_url, session_token, file_path, page_number, timeout=UPLOAD_TIMEOUT_SECONDS):
    """A single POST per page; the server (integrations.capture_views.
    BatchUploadView) is the one that enforces session scope, hash
    deduplication and quarantine/AV -- this agent only transports bytes.
    """
    content = Path(file_path).read_bytes()
    boundary = hashlib.sha256(content[:64] + str(time.time()).encode()).hexdigest()
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="page_number"\r\n\r\n{page_number}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="page"; filename="{Path(file_path).name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ).encode() + content + f'\r\n--{boundary}--\r\n'.encode()

    url = f'{base_url.rstrip("/")}/capture/upload/{session_token}/'
    req = request.Request(url, data=body, method='POST', headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    })
    with request.urlopen(req, timeout=timeout) as response:
        return response.status, json.loads(response.read())


def run_once(base_url, session_token, watch_dir, queue_path):
    found, queue = scan_folder(watch_dir, queue_path)
    for index, file_path in enumerate(found, start=len(queue['sent']) + 1):
        try:
            status, payload = upload_page(base_url, session_token, file_path, index)
        except error.URLError:
            queue['pending'].append(file_path)
            _save_queue(queue_path, queue)
            continue
        queue['sent'].append(file_path)
        _save_queue(queue_path, queue)
    return queue
