#!/usr/bin/env bash
set -euo pipefail

# Run on the production VM after adding portal.shinecongo.org's DNS A record.
[[ "$EUID" -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
config=/etc/nginx/sites-available/portal-shinecongo-domain
enabled=/etc/nginx/sites-enabled/portal-shinecongo-domain
backup_dir="$(mktemp -d /var/tmp/portal-https.XXXXXX)"
chmod 700 "$backup_dir"
if [[ -f "$config" ]]; then cp -p "$config" "$backup_dir/nginx.conf"; fi

rollback() {
    if [[ -f "$backup_dir/nginx.conf" ]]; then
        cp -p "$backup_dir/nginx.conf" "$config"
    else
        rm -f "$enabled" "$config"
    fi
    nginx -t && systemctl reload nginx
    echo "HTTPS setup failed; prior nginx config restored. Backup: $backup_dir" >&2
}
trap rollback ERR
install -d -m 755 /var/www/letsencrypt
install -m 644 "$repo_dir/deploy/nginx/portal-domain-http.conf" "$config"
if [[ -f /etc/letsencrypt/live/portal.shinecongo.org/fullchain.pem ]]; then
    cat "$repo_dir/deploy/nginx/portal-domain-tls.conf" >> "$config"
fi
ln -sfn "$config" "$enabled"
nginx -t
systemctl reload nginx
certbot certonly --webroot -w /var/www/letsencrypt --non-interactive \
    --keep-until-expiring --cert-name portal.shinecongo.org -d portal.shinecongo.org
cat "$repo_dir/deploy/nginx/portal-domain-http.conf" "$repo_dir/deploy/nginx/portal-domain-tls.conf" > "$config"
nginx -t
systemctl reload nginx
install -m 755 "$repo_dir/deploy/nginx/reload-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/portal-reload-nginx
trap - ERR
echo "HTTPS enabled for portal.shinecongo.org; nginx backup: $backup_dir"
