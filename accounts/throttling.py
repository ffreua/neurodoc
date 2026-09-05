import time

from django.core.cache import cache

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900
MAX_DELAY_SECONDS = 2.0


def _key(email, ip):
    return f'login-throttle:{(email or "").strip().lower()}:{ip or ""}'


def is_throttled(email, ip):
    return cache.get(_key(email, ip), 0) >= MAX_ATTEMPTS


def register_failure(email, ip):
    key = _key(email, ip)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, WINDOW_SECONDS)
    return attempts


def clear_failures(email, ip):
    cache.delete(_key(email, ip))


def apply_progressive_delay(email, ip):
    attempts = cache.get(_key(email, ip), 0)
    delay = min(attempts * 0.5, MAX_DELAY_SECONDS)
    if delay > 0:
        time.sleep(delay)
