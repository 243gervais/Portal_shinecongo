# Production HTTPS

The canonical portal address is https://portal.shinecongo.org/. Its DNS A record
points to the existing VM, 8.229.62.95. The portal and public shinecongo.org website
remain separate nginx virtual hosts and applications.

The old sslip.io address produced invalid TLS records from the client network,
while the same nginx listener and valid certificate worked from the server and
through its nip.io alias. This isolated a hostname/network-path failure before
Django, not a browser-cache or login failure. Moving to the company's own domain
avoids that dependency. A failed TLS handshake cannot be fixed with JavaScript or
an HTTP redirect because the request never reaches the application.

Provisioning (after DNS is configured and this code is pulled on the VM):

```sh
venv/bin/fab configure-https
```

The task installs the dedicated HTTP challenge endpoint, obtains a Let's Encrypt
certificate using the existing ACME account, validates/reloads nginx, configures
the canonical Django host and secure cookies, restarts the existing service and
tests fresh HTTPS connections. Unrelated environment settings and nginx sites
are preserved. nginx changes have a root-only backup and are restored on setup
failure. No schema or data changes are involved.

Certbot's existing timer renews the certificate. A deploy hook validates and
reloads nginx after renewal. The ACME HTTP challenge path remains available;
other HTTP requests redirect to HTTPS. Keep the certificate/private key outside
Git. The DNS record is DNS-only; do not enable a proxy using Flexible TLS, which
would cause an HTTP/HTTPS redirect loop.

The two legacy portal hosts redirect GET/HEAD navigation to the canonical domain
when their TLS handshake succeeds. POSTs are never forwarded across hosts. Users
must sign in once at the new address because authentication cookies are
host-specific; do not broaden their cookie domain or transfer credentials in URLs.
Existing printed QR codes using the old hostname should be regenerated.

nginx must overwrite X-Forwarded-Proto (the production proxy_params already does).
Django trusts that header for secure generated links and CSRF origin checking.
Keep Gunicorn on its existing private Unix socket.

Every Fabric deployment now runs three fresh certificate-validating HTTPS checks.
For a manual check from a client network or the production VM:

```sh
venv/bin/python scripts/check_https.py --attempts 10
```

Checks fail on network/TLS/hostname/chain errors, a certificate expiring within
seven days, or a login response other than HTTP 200. Verification is never disabled.
For diagnostics inspect /var/log/nginx/portal-shinecongo.error.log and
`systemctl status certbot.timer`.
