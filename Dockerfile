FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Copy the secrets setup script
COPY setup-secrets.sh .
RUN chmod +x setup-secrets.sh

# Expose Streamlit default port
EXPOSE 8501

# Set environment variables for Streamlit
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true

# Create entrypoint script that generates secrets before starting Streamlit
RUN echo '#!/bin/sh\n\
set -e\n\
\n\
# Generate secrets.toml from environment variables\n\
if [ -n "$OIDC_CLIENT_ID" ] && [ -n "$OIDC_CLIENT_SECRET" ]; then\n\
    echo "Setting up OIDC secrets..."\n\
    ./setup-secrets.sh\n\
else\n\
    echo "Warning: OIDC environment variables not set. Authentication may not work."\n\
    echo "Please set OIDC_CLIENT_ID and OIDC_CLIENT_SECRET environment variables."\n\
fi\n\
\n\
# Start Streamlit\n\
exec streamlit run /app/app.py\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Use the entrypoint script
CMD ["/app/entrypoint.sh"]
