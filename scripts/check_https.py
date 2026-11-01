"""Validate real, fresh HTTPS connections, including hostname and chain verification."""
import argparse
import http.client
import ssl
import sys
from datetime import datetime, timezone
from time import monotonic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='portal.shinecongo.org')
    parser.add_argument('--attempts', type=int, default=5)
    args = parser.parse_args()
    failures = 0
    context = ssl.create_default_context()
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
