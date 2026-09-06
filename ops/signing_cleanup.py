import subprocess

from ops.deploy import run


def _any_app_container():
    """Both app replicas bind-mount the same host tmpfs (docker-stack.yml),
    so cleaning it through any single replica is enough -- unlike
    ops.backup.container_for, this does not require exactly one match.
    """
    ids = run(['docker', 'ps', '-q', '--filter',
               'label=com.docker.swarm.service.name=neurodoc_v1_app']).splitlines()
    if not ids:
        raise RuntimeError('No running app container found')
    return ids[0]


def main():
    container = _any_app_container()
    subprocess.run(
        ['docker', 'exec', container, 'python', 'manage.py', 'cleanup_signing_keys'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


if __name__ == '__main__':
    main()
