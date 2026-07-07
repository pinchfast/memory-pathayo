FROM python:3.14-slim AS builder

WORKDIR /tmp

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv export --no-dev --no-hashes -o requirements.txt

FROM python:3.14-slim

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

COPY --from=builder /tmp/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

COPY . /code

EXPOSE 80

CMD ["python", "manage.py", "run-prod-server"]
