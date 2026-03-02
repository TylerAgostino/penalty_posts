#!/bin/sh
set -e

# Generate secrets.toml from environment variables
if [ -n "$OIDC_CLIENT_ID" ] && [ -n "$OIDC_CLIENT_SECRET" ]; then
    echo "Setting up OIDC secrets..."
    if [ -f "/app/setup-secrets.sh" ]; then
        chmod +x /app/setup-secrets.sh
        /app/setup-secrets.sh
    else
        echo "Error: setup-secrets.sh not found. Please ensure it is mounted at runtime."
        exit 1
    fi
else
    echo "Warning: OIDC environment variables not set. Authentication may not work."
    echo "Please set OIDC_CLIENT_ID and OIDC_CLIENT_SECRET environment variables."
fi

# Start Streamlit
exec streamlit run /app/app.py
