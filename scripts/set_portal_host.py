"""Activate the verified portal domain without printing or replacing other secrets."""
from pathlib import Path

from dotenv import dotenv_values, set_key


def main():
    env_path = Path(__file__).resolve().parent.parent / '.env'
    if not env_path.is_file():
        raise SystemExit('Existing production .env is required')
    values = dotenv_values(env_path)
    hosts = [host.strip() for host in values.get('ALLOWED_HOSTS', '').split(',') if host.strip()]
    for host in ('portal.shinecongo.org', 'shinecongo-portal.8.229.62.95.sslip.io', '8-229-62-95.nip.io'):
        if host not in hosts:
            hosts.append(host)
    for name, value in {
        'ALLOWED_HOSTS': ','.join(hosts),
        'PORTAL_CANONICAL_HOST': 'portal.shinecongo.org',
        'SESSION_COOKIE_SECURE': 'True',
        'CSRF_COOKIE_SECURE': 'True',
    }.items():
        set_key(env_path, name, value)
    print('Canonical portal host and secure cookies configured; other environment values preserved.')


if __name__ == '__main__':
    main()
