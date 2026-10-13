FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 webtools \
    && mkdir -p /data/downloads && chown -R webtools:webtools /data /opt/browsers
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
USER webtools
EXPOSE 8000
CMD ["python", "-m", "web_tools"]
