FROM python:3.12-slim-bookworm

# pi CLI runs on Node ≥20.6; apt's nodejs on bookworm is too old, use NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git bash gnupg \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash app
USER app
WORKDIR /home/app

# pi CLI
RUN curl -fsSL https://pi.dev/install.sh | sh
ENV PATH="/home/app/.local/bin:${PATH}"

# Bake pi runtime config (settings + extensions) into ~/.pi/agent
COPY --chown=app:app pi/settings.json /home/app/.pi/agent/settings.json
COPY --chown=app:app pi/extensions /home/app/.pi/agent/extensions
RUN cd /home/app/.pi/agent/extensions && npm install --omit=dev

WORKDIR /workspace

EXPOSE 6006

# Idle by default. The FastAPI app will replace this via compose `command:`.
CMD ["sleep", "infinity"]
