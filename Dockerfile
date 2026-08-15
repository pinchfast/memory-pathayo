FROM python:3.14-slim AS builder

WORKDIR /tmp

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY kgmemory ./kgmemory
RUN uv export --no-dev --no-hashes --no-editable -o requirements.txt \
    && grep -v -E '^\.' requirements.txt > /tmp/req-clean.txt && mv /tmp/req-clean.txt requirements.txt

FROM python:3.14-slim

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

COPY --from=builder /tmp/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

COPY . /code

EXPOSE 8001

CMD ["python", "manage.py", "run-prod-server"]
