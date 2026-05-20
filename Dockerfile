FROM python:3.12-slim-bookworm

# pi CLI runs on Node ≥20.6; apt's nodejs on bookworm is too old, use NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git bash gnupg \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Python deps (installed system-wide while still root)
COPY pyproject.toml /tmp/pyproject.toml
RUN uv pip install --system --no-cache -r /tmp/pyproject.toml && rm /tmp/pyproject.toml

RUN useradd -m -u 1000 -s /bin/bash app \
  && mkdir -p /workspace /home/app/.pi/agent \
  && chown -R app:app /workspace /home/app/.pi
USER app
WORKDIR /home/app

# pi CLI
RUN curl -fsSL https://pi.dev/install.sh | sh
ENV PATH="/home/app/.local/bin:${PATH}"

# pi settings
COPY --chown=app:app pi/settings.json /home/app/.pi/agent/settings.json

# Install pi extensions into a non-bind-mounted cache path so the build
# survives the bind mount at /workspace; `make build` copies node_modules
# from this cache to the host so the IDE sees them too.
COPY --chown=app:app pi/extensions /home/app/.cache/pi-extensions
RUN cd /home/app/.cache/pi-extensions && npm install \
  && ln -s /workspace/pi/extensions /home/app/.pi/agent/extensions

# pi packages (user-scoped npm install, no root needed at runtime). `pi install`
# both fetches the package and adds it to settings.json's `packages` array.
ENV PATH="/home/app/.npm-global/bin:${PATH}"
RUN mkdir -p /home/app/.npm-global \
  && npm config set prefix /home/app/.npm-global \
  && pi install npm:@hdkiller/pi-langfuse

WORKDIR /workspace

EXPOSE 6006

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6006"]
