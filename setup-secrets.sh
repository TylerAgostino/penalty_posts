#!/bin/sh
# setup-secrets.sh
# Script to generate .streamlit/secrets.toml from environment variables
# This allows secrets to be injected at build/run time without committing them to git

set -e

SECRETS_DIR=".streamlit"
SECRETS_FILE="${SECRETS_DIR}/secrets.toml"

# Ensure .streamlit directory exists
mkdir -p "${SECRETS_DIR}"

# Check if required environment variables are set
if [ -z "${OIDC_CLIENT_ID}" ] || [ -z "${OIDC_CLIENT_SECRET}" ]; then
    echo "Error: Required environment variables not set"
    echo "Please set the following environment variables:"
    echo "  - OIDC_CLIENT_ID"
    echo "  - OIDC_CLIENT_SECRET"
    echo ""
    echo "Optional environment variables:"
    echo "  - OIDC_ISSUER_URL (defaults to https://accounts.google.com)"
    echo "  - OIDC_ALLOWED_DOMAINS (comma-separated list)"
    echo "  - OIDC_ALLOWED_EMAILS (comma-separated list)"
    exit 1
fi

# Set default issuer URL if not provided
OIDC_ISSUER_URL="${OIDC_ISSUER_URL:-https://accounts.google.com}"

echo "Generating secrets.toml..."

# Create secrets.toml file
cat > "${SECRETS_FILE}" << EOF
# Auto-generated secrets.toml
# Generated at: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# DO NOT commit this file to version control

[auth.oidc]
client_id = "${OIDC_CLIENT_ID}"
client_secret = "${OIDC_CLIENT_SECRET}"
issuer_url = "${OIDC_ISSUER_URL}"
EOF

# Add allowed domains if specified
if [ -n "${OIDC_ALLOWED_DOMAINS}" ]; then
    echo "" >> "${SECRETS_FILE}"
    echo "# Allowed email domains" >> "${SECRETS_FILE}"
    echo "allowed_domains = [" >> "${SECRETS_FILE}"

    # Split comma-separated domains and format as TOML array
    echo "${OIDC_ALLOWED_DOMAINS}" | tr ',' '\n' | while IFS= read -r domain; do
        domain=$(echo "$domain" | xargs)  # Trim whitespace
        if [ -n "$domain" ]; then
            echo "  \"${domain}\"," >> "${SECRETS_FILE}"
        fi
    done

    echo "]" >> "${SECRETS_FILE}"
fi

# Add allowed emails if specified
if [ -n "${OIDC_ALLOWED_EMAILS}" ]; then
    echo "" >> "${SECRETS_FILE}"
    echo "# Allowed email addresses" >> "${SECRETS_FILE}"
    echo "allowed_emails = [" >> "${SECRETS_FILE}"

    # Split comma-separated emails and format as TOML array
    echo "${OIDC_ALLOWED_EMAILS}" | tr ',' '\n' | while IFS= read -r email; do
        email=$(echo "$email" | xargs)  # Trim whitespace
        if [ -n "$email" ]; then
            echo "  \"${email}\"," >> "${SECRETS_FILE}"
        fi
    done

    echo "]" >> "${SECRETS_FILE}"
fi

echo "✓ secrets.toml created successfully at ${SECRETS_FILE}"
echo ""
echo "Configuration:"
echo "  Client ID: ${OIDC_CLIENT_ID}"
echo "  Issuer URL: ${OIDC_ISSUER_URL}"
[ -n "${OIDC_ALLOWED_DOMAINS}" ] && echo "  Allowed Domains: ${OIDC_ALLOWED_DOMAINS}" || true
[ -n "${OIDC_ALLOWED_EMAILS}" ] && echo "  Allowed Emails: ${OIDC_ALLOWED_EMAILS}" || true
