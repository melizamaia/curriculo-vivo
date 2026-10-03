# Uma imagem para a API e para o worker; o compose troca só o comando.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app app app
COPY --chown=app:app data data
COPY --chown=app:app eval eval
COPY --chown=app:app scripts scripts
COPY --chown=app:app tests tests
RUN mkdir dashboard && chown app:app dashboard

USER app

# O harness roda no build: alerta sem citação ou invariante violada reprova
# a imagem, e o painel em /painel já sai pronto.
RUN python -m eval.run_eval

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
