FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY discord_helpers.py .
COPY draft_manager.py .

# Copy secrets script
COPY setup-secrets.sh .
RUN chmod +x setup-secrets.sh

# Copy entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Copy Streamlit pages
COPY pages/ pages/

# Create persistent data directories
RUN mkdir -p data/drafts data/posts data/draft_files

# Expose Streamlit default port
EXPOSE 8501

# Set environment variables for Streamlit
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true

# Use the entrypoint script
CMD ["/app/entrypoint.sh"]
