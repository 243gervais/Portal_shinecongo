"""Validate real, fresh HTTPS connections, including hostname and chain verification."""
import argparse
import http.client
import ssl
import sys
from datetime import datetime, timezone
from time import monotonic, sleep


def wait_until_ready(host, seconds, context):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        connection = http.client.HTTPSConnection(host, timeout=2, context=context)
        try:
            connection.request('HEAD', '/login/')
            if connection.getresponse().status == 200:
                return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        sleep(0.5)
    raise SystemExit('Application did not become HTTPS-ready before the startup deadline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='portal.shinecongo.org')
    parser.add_argument('--attempts', type=int, default=5)
    parser.add_argument('--wait-ready', type=int, default=0, help='Allow application startup before strict checks')
    args = parser.parse_args()
    failures = 0
    context = ssl.create_default_context()
    if args.wait_ready > 0:
        wait_until_ready(args.host, args.wait_ready, context)
    for attempt in range(max(1, args.attempts)):
        connection = http.client.HTTPSConnection(args.host, timeout=10, context=context)
        started = monotonic()
        try:
            connection.connect()
            certificate = connection.sock.getpeercert()
            expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate['notAfter']), timezone.utc)
            if (expires - datetime.now(timezone.utc)).days < 7:
                raise ValueError('Certificate expires in less than seven days')
            version = connection.sock.version()
            connection.request('HEAD', '/login/')
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f'Expected login HTTP 200, received {response.status}')
            print(f'{attempt + 1}: OK {version} HTTP 200 {monotonic() - started:.2f}s expires={expires.date()}')
        except (OSError, ValueError, http.client.HTTPException) as error:
            failures += 1
            print(f'{attempt + 1}: FAILED {type(error).__name__}: {error}', file=sys.stderr)
        finally:
            connection.close()
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
