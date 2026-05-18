FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads logs database

EXPOSE 5000

ENV FLASK_APP=run.py
ENV FLASK_ENV=production

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000')" || exit 1

# --timeout must exceed the longest in-process urllib timeout (LLM call in
# llm_manager.py is 1200s) so urllib fails gracefully instead of gunicorn
# killing the worker mid-call. 4 workers so one slow LLM call doesn't lock
# out the rest of the app.
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "--timeout", "1500", "run:app"]
