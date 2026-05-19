FROM python:3.12-slim

# Install system dependencies for Cursor CLI (must run as root)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    ssh \
    git \
    ripgrep \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with fixed UID=1000.
# The image is expected to run as this user; align host UID accordingly
# (or override at runtime with `docker run --user`).
RUN useradd -m -u 1000 -s /bin/bash agent

# Hand /home/agent ownership to agent so SessionManager can create
# sessions.json / sessions.json.lock and --update-model can rewrite models.json.
WORKDIR /home/agent
RUN chown -R agent:agent /home/agent
ENV HOME=/home/agent

# Switch to non-root user for the rest of the build and runtime.
USER agent

# Cursor CLI installs to $HOME/.local/bin; venv lives in $HOME/venv.
ENV PATH="/home/agent/.local/bin:/home/agent/venv/bin:$PATH"

# Install Cursor CLI under agent's HOME (avoids /root 700 traversal issues
# and lets cursor-agent write its own state under ~/.cursor).
RUN curl https://cursor.com/install -fsS | bash

# Create venv in agent's HOME to avoid PEP 668 system-package limits.
RUN python -m venv /home/agent/venv

# Install Python dependencies into the venv.
COPY --chown=agent:agent requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (owned by agent so --update-model can rewrite it).
COPY --chown=agent:agent src/ ./src/
COPY --chown=agent:agent models.json ./models.json

CMD ["python", "-m", "src.main"]
