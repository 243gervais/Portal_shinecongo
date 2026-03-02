# Oracle Portal Automation

This script provisions an Oracle Always Free VM from scratch and deploys `portal_shinecongo` with AWS S3-enabled uploads.

Script:
- `scripts/create_oracle_portal.sh`

## Prerequisites

1. Install OCI CLI and configure API-key auth:
   - `oci setup config`
2. Ensure `jq` is installed.
3. Ensure you can run OCI API calls from this machine.

## Required Environment Variables

```bash
export OCI_COMPARTMENT_OCID="ocid1.compartment..."
export OCI_TENANCY_OCID="ocid1.tenancy..."
export OCI_REGION="us-ashburn-1"   # or your Oracle region

export PORTAL_SECRET_KEY="..."
export PORTAL_ALLOWED_HOSTS="your-oracle-ip,localhost,127.0.0.1"
export PORTAL_CSRF_TRUSTED_ORIGINS="http://your-oracle-ip"
export PORTAL_AWS_ACCESS_KEY_ID="..."
export PORTAL_AWS_SECRET_ACCESS_KEY="..."
export PORTAL_AWS_STORAGE_BUCKET_NAME="portal-shinecongo-media-975050025599"
export PORTAL_AWS_S3_REGION_NAME="us-east-1"
```

## Optional Environment Variables

```bash
export INSTANCE_NAME="portal-shinecongo-oracle"
export OCI_SHAPE="VM.Standard.A1.Flex"
export OCI_OCPUS="1"
export OCI_MEMORY_GB="6"
export OCI_IMAGE_OS="Canonical Ubuntu"
export OCI_IMAGE_VERSION="22.04"
export PROJECT_REPO="https://github.com/243gervais/Portal_shinecongo.git"
export PROJECT_BRANCH="main"
```

## Run

```bash
chmod +x scripts/create_oracle_portal.sh
./scripts/create_oracle_portal.sh
```

The script outputs:
- Oracle instance OCID
- Oracle public IP
- SSH key path
- Portal URL
