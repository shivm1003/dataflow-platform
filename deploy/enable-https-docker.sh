#!/usr/bin/env bash
# Run on the VPS as teamcrawlers AFTER DNS A record exists:
#   dashboard.teamcrawlers.com → this server's public IP
#
# Starts/renews Let's Encrypt cert via Docker, reloads Nginx container,
# then flips SESSION_HTTPS_ONLY=1 and restarts dataflow-api.
set -euo pipefail

DOMAIN=dashboard.teamcrawlers.com
ENV_FILE="${HOME}/teamcrawlers/dataflow-platform/.env"
NGINX_CONF="${HOME}/deploy/nginx/dashboard.conf"
WWW="${HOME}/deploy/certbot/www"
CONF="${HOME}/deploy/certbot/conf"

echo "Checking DNS for ${DOMAIN}…"
resolved=$(python3 -c "import socket; print(socket.gethostbyname('${DOMAIN}'))")
echo "  resolves to ${resolved}"
# Compare to first non-loopback IPv4 on the host
my_ip=$(hostname -I | awk '{print $1}')
echo "  host IP ${my_ip}"
if [[ "${resolved}" != "${my_ip}" ]]; then
  echo "DNS does not point at this host yet. Add A record ${DOMAIN} → ${my_ip} in Wix DNS, wait, re-run."
  exit 1
fi

echo "Requesting certificate…"
docker run --rm --network host \
  -v "${WWW}:/var/www/certbot" \
  -v "${CONF}:/etc/letsencrypt" \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d "${DOMAIN}" --agree-tos --non-interactive \
  --register-unsafely-without-email \
  --keep-until-expiring

echo "Writing HTTPS Nginx config…"
cat > "${NGINX_CONF}" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 120s;
    }
}
NGINX

docker exec dataflow-nginx nginx -s reload

# Secure cookies only after TLS is live
sed -i 's/^SESSION_HTTPS_ONLY=.*/SESSION_HTTPS_ONLY=1/' "${ENV_FILE}"
PID=$(pgrep -f '/.venv/bin/dataflow-api' | head -1)
kill "${PID}"
for i in $(seq 1 15); do
  sleep 1
  curl -sf http://127.0.0.1:8000/health >/dev/null && break
done

echo "Done. Open https://${DOMAIN}/login"
echo "Optional later: firewall public :8000; set API_HOST=127.0.0.1 and restart."
