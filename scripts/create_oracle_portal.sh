#!/usr/bin/env bash
set -euo pipefail

# Create an Oracle Always Free VM and deploy portal_shinecongo on it.
# Prerequisites:
#   - OCI CLI configured (`oci setup config`)
#   - Required env vars exported (see required_env function below)

required_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

json() {
  jq -r "$1"
}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

if ! cmd_exists oci; then
  echo "OCI CLI is required but not installed. Install it first: https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm" >&2
  exit 1
fi

if ! cmd_exists jq; then
  echo "jq is required but not installed." >&2
  exit 1
fi

# OCI auth inputs
required_env OCI_COMPARTMENT_OCID
required_env OCI_TENANCY_OCID
required_env OCI_REGION

# VM + app inputs
INSTANCE_NAME="${INSTANCE_NAME:-portal-shinecongo-oracle}"
OCI_SHAPE="${OCI_SHAPE:-VM.Standard.A1.Flex}"
OCI_OCPUS="${OCI_OCPUS:-1}"
OCI_MEMORY_GB="${OCI_MEMORY_GB:-6}"
OCI_IMAGE_OS="${OCI_IMAGE_OS:-Canonical Ubuntu}"
OCI_IMAGE_VERSION="${OCI_IMAGE_VERSION:-22.04}"
SSH_PUBLIC_KEY_FILE="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/portal_oracle_ed25519.pub}"
SSH_PRIVATE_KEY_FILE="${SSH_PRIVATE_KEY_FILE:-$HOME/.ssh/portal_oracle_ed25519}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/portal_shinecongo}"
PROJECT_REPO="${PROJECT_REPO:-https://github.com/243gervais/Portal_shinecongo.git}"
PROJECT_BRANCH="${PROJECT_BRANCH:-main}"

# Portal runtime env (S3-backed)
required_env PORTAL_SECRET_KEY
required_env PORTAL_ALLOWED_HOSTS
required_env PORTAL_CSRF_TRUSTED_ORIGINS
required_env PORTAL_AWS_ACCESS_KEY_ID
required_env PORTAL_AWS_SECRET_ACCESS_KEY
required_env PORTAL_AWS_STORAGE_BUCKET_NAME
required_env PORTAL_AWS_S3_REGION_NAME

export OCI_CLI_REGION="${OCI_REGION}"

if [[ ! -f "$SSH_PUBLIC_KEY_FILE" || ! -f "$SSH_PRIVATE_KEY_FILE" ]]; then
  log "Generating Oracle SSH keypair at $SSH_PRIVATE_KEY_FILE"
  mkdir -p "$(dirname "$SSH_PRIVATE_KEY_FILE")"
  ssh-keygen -t ed25519 -f "$SSH_PRIVATE_KEY_FILE" -N "" -C "portal-oracle"
fi

log "Looking up availability domain"
AD_NAME="$(oci iam availability-domain list \
  --compartment-id "$OCI_TENANCY_OCID" \
  --query 'data[0].name' \
  --raw-output)"

if [[ -z "$AD_NAME" || "$AD_NAME" == "null" ]]; then
  echo "Could not resolve availability domain" >&2
  exit 1
fi

log "Creating network resources"
VCN_OCID="$(oci network vcn create \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --cidr-block "10.0.0.0/16" \
  --display-name "${INSTANCE_NAME}-vcn" \
  --dns-label "portalvcn" \
  --query 'data.id' --raw-output)"

IGW_OCID="$(oci network internet-gateway create \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" \
  --is-enabled true \
  --display-name "${INSTANCE_NAME}-igw" \
  --query 'data.id' --raw-output)"

RT_OCID="$(oci network route-table create \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" \
  --display-name "${INSTANCE_NAME}-rt" \
  --route-rules "[{\"cidrBlock\":\"0.0.0.0/0\",\"networkEntityId\":\"$IGW_OCID\"}]" \
  --query 'data.id' --raw-output)"

SL_OCID="$(oci network security-list create \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" \
  --display-name "${INSTANCE_NAME}-sl" \
  --ingress-security-rules '[
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":80,"max":80}}},
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":443,"max":443}}}
  ]' \
  --egress-security-rules '[{"protocol":"all","destination":"0.0.0.0/0"}]' \
  --query 'data.id' --raw-output)"

SUBNET_OCID="$(oci network subnet create \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" \
  --cidr-block "10.0.1.0/24" \
  --display-name "${INSTANCE_NAME}-subnet" \
  --dns-label "portalsub" \
  --security-list-ids "[\"$SL_OCID\"]" \
  --route-table-id "$RT_OCID" \
  --prohibit-public-ip-on-vnic false \
  --query 'data.id' --raw-output)"

log "Resolving latest Oracle-compatible Ubuntu image"
IMAGE_OCID="$(oci compute image list \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --operating-system "$OCI_IMAGE_OS" \
  --operating-system-version "$OCI_IMAGE_VERSION" \
  --shape "$OCI_SHAPE" \
  --sort-by TIMECREATED \
  --sort-order DESC \
  --query 'data[0].id' \
  --raw-output)"

if [[ -z "$IMAGE_OCID" || "$IMAGE_OCID" == "null" ]]; then
  echo "Could not resolve image for shape=$OCI_SHAPE os=$OCI_IMAGE_OS $OCI_IMAGE_VERSION" >&2
  exit 1
fi

log "Launching instance $INSTANCE_NAME"
INSTANCE_OCID="$(oci compute instance launch \
  --availability-domain "$AD_NAME" \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --shape "$OCI_SHAPE" \
  --shape-config "{\"ocpus\":${OCI_OCPUS},\"memoryInGBs\":${OCI_MEMORY_GB}}" \
  --display-name "$INSTANCE_NAME" \
  --source-details "{\"sourceType\":\"image\",\"imageId\":\"$IMAGE_OCID\"}" \
  --create-vnic-details "{\"subnetId\":\"$SUBNET_OCID\",\"assignPublicIp\":true}" \
  --metadata "{\"ssh_authorized_keys\":\"$(cat "$SSH_PUBLIC_KEY_FILE")\"}" \
  --query 'data.id' --raw-output)"

log "Waiting for instance to reach RUNNING"
oci compute instance get --instance-id "$INSTANCE_OCID" --wait-for-state RUNNING >/dev/null

PUBLIC_IP="$(oci compute instance list-vnics \
  --instance-id "$INSTANCE_OCID" \
  --compartment-id "$OCI_COMPARTMENT_OCID" \
  --query 'data[0]."public-ip"' \
  --raw-output)"

if [[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "null" ]]; then
  echo "Could not resolve public IP for instance $INSTANCE_OCID" >&2
  exit 1
fi

log "Waiting for SSH on $PUBLIC_IP"
for _ in {1..30}; do
  if ssh -i "$SSH_PRIVATE_KEY_FILE" -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" "echo ok" >/dev/null 2>&1; then
    break
  fi
  sleep 10
done

PORTAL_ENV_CONTENT="$(cat <<EOF
SECRET_KEY=${PORTAL_SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${PORTAL_ALLOWED_HOSTS}
CSRF_TRUSTED_ORIGINS=${PORTAL_CSRF_TRUSTED_ORIGINS}
USE_S3=True
AWS_ACCESS_KEY_ID=${PORTAL_AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${PORTAL_AWS_SECRET_ACCESS_KEY}
AWS_STORAGE_BUCKET_NAME=${PORTAL_AWS_STORAGE_BUCKET_NAME}
AWS_S3_REGION_NAME=${PORTAL_AWS_S3_REGION_NAME}
EOF
)"

PORTAL_ENV_B64="$(printf '%s' "$PORTAL_ENV_CONTENT" | base64)"

log "Deploying portal_shinecongo on Oracle VM"
ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" "bash -s" <<'EOF'
set -euo pipefail
sudo apt update -y
sudo apt install -y python3-venv python3-pip nginx git
EOF

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" \
  "mkdir -p '$PROJECT_DIR' && if [ ! -d '$PROJECT_DIR/.git' ]; then git clone '$PROJECT_REPO' '$PROJECT_DIR'; fi && cd '$PROJECT_DIR' && git fetch origin && git checkout '$PROJECT_BRANCH' && git pull origin '$PROJECT_BRANCH'"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" \
  "cd '$PROJECT_DIR' && python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" \
  "cd '$PROJECT_DIR' && echo '$PORTAL_ENV_B64' | base64 -d > .env && chmod 640 .env"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" \
  "cd '$PROJECT_DIR' && source venv/bin/activate && python manage.py migrate --noinput && python manage.py collectstatic --noinput"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" "sudo tee /etc/systemd/system/portal-shinecongo.service > /dev/null <<'UNIT'
[Unit]
Description=portal-shinecongo gunicorn
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
RuntimeDirectory=portal-shinecongo
RuntimeDirectoryMode=775
ExecStartPre=/bin/rm -f /run/portal-shinecongo/gunicorn.sock
ExecStart=${PROJECT_DIR}/venv/bin/gunicorn --access-logfile - --error-logfile - --workers 3 --bind unix:/run/portal-shinecongo/gunicorn.sock shinecongo.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" "sudo tee /etc/nginx/sites-available/portal-shinecongo > /dev/null <<'NGINX'
server {
    listen 80;
    server_name _;

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/portal-shinecongo/gunicorn.sock;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
    }

    add_header X-Frame-Options \"SAMEORIGIN\" always;
    add_header X-Content-Type-Options \"nosniff\" always;
    add_header Referrer-Policy \"strict-origin-when-cross-origin\" always;
    add_header Permissions-Policy \"geolocation=(), microphone=(), camera=()\" always;
    client_max_body_size 100M;
}
NGINX"

ssh -i "$SSH_PRIVATE_KEY_FILE" -o StrictHostKeyChecking=accept-new ubuntu@"$PUBLIC_IP" "sudo ln -sf /etc/nginx/sites-available/portal-shinecongo /etc/nginx/sites-enabled/portal-shinecongo && sudo nginx -t && sudo systemctl daemon-reload && sudo systemctl enable portal-shinecongo && sudo systemctl restart portal-shinecongo && sudo systemctl reload nginx"

log "Oracle VM created and portal deployed"
echo "INSTANCE_OCID=$INSTANCE_OCID"
echo "PUBLIC_IP=$PUBLIC_IP"
echo "SSH_KEY=$SSH_PRIVATE_KEY_FILE"
echo "PORTAL_URL=http://$PUBLIC_IP/login/"
