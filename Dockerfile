FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
RUN pip install --no-cache-dir .
ENTRYPOINT ["aiip"]
CMD ["examples/retail-ai-rfp.json", "--as-of", "2026-09-06"]

