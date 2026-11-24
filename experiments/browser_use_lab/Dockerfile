# RESEARCH ONLY. Build context is this directory, not the application home.
# Review and pin base digest, model artifacts and SBOM before wider use.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium ca-certificates fontconfig fonts-liberation \
    libnss3 libatk-bridge2.0-0 libgtk-3-0 libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "browser-use==1.0.7" "playwright==1.53.0"
RUN useradd --uid 10001 --home-dir /home/lab --create-home lab

WORKDIR /opt/autumn
COPY __init__.py agent.py policy.py bounded_planner.py /opt/autumn/experiments/browser_use_lab/
ENV PYTHONPATH=/opt/autumn \
    HOME=/tmp/lab-home \
    XDG_CACHE_HOME=/tmp/lab-cache \
    BROWSER_USE_AUTO_LOGIN=false \
    ANONYMIZED_TELEMETRY=false \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["python", "-m", "experiments.browser_use_lab.agent"]
