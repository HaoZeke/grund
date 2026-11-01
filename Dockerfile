# Frozen Grund image.
# Python 3.12.12, Ruby 3.2.6, and Node.js 22.23.4 are pinned by image tag.
# Node compiles the chat page and is not part of the running container.
# Vangrail 0.3.0 is cloned from the public repository at a pinned commit.
# The multilingual-e5-small int8 weights are fetched from the public Xenova
# repository at a pinned revision and checked against the frozen sha256 values.
# data/index and data/index-e5-small are the copies committed in this repository.
# data/index-lang is built here from the committed catalogue.
# PxWeb is public. This image sets no API key.

FROM node:22.23.4-bookworm-slim AS ui
WORKDIR /src
COPY app/web/package.json app/web/package-lock.json ./
COPY app/web/index.html app/web/vite.config.ts app/web/tsconfig.json app/web/tsconfig.app.json app/web/tsconfig.node.json ./
COPY app/web/src ./src
COPY app/web/public ./public
RUN npm ci && npm run build

FROM ruby:3.2.6-slim-bookworm AS ruby

FROM python:3.12.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libffi8 \
        libgmp10 \
        libcrypt1 \
        libncurses6 \
        libreadline8 \
        libssl3 \
        libyaml-0-2 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -c 'import sys; assert sys.version.startswith("3.12.12"), sys.version'

COPY --from=ruby /usr/local/bin/ruby /usr/local/bin/ruby
COPY --from=ruby /usr/local/lib/libruby.so /usr/local/lib/libruby.so
COPY --from=ruby /usr/local/lib/libruby.so.3.2 /usr/local/lib/libruby.so.3.2
COPY --from=ruby /usr/local/lib/libruby.so.3.2.6 /usr/local/lib/libruby.so.3.2.6
COPY --from=ruby /usr/local/lib/ruby /usr/local/lib/ruby
RUN ldconfig \
    && ruby -e 'raise RUBY_VERSION unless RUBY_VERSION == "3.2.6"' \
    && ruby -e 'require "json"; require "socket"'

WORKDIR /app

RUN python3 -m pip install \
        'fastapi==0.162.0' \
        'uvicorn==0.54.0' \
        'pydantic==2.14.2' \
        'numpy==2.5.4' \
        'httpx==0.28.1' \
        'onnxruntime==1.31.1' \
        'tokenizers==0.23.3'

COPY app ./app
COPY indexer ./indexer
COPY evalset ./evalset
COPY rails ./rails
COPY lang ./lang
COPY script ./script
COPY data/catalogue.jsonl ./data/catalogue.jsonl
COPY data/index ./data/index
COPY data/index-e5-small ./data/index-e5-small

ARG VANGRAIL_REV=e9aa7a1e9942dc089a5c469e54017251b05b105a
RUN git clone --quiet https://github.com/HaoZeke/vangrail vendor/vangrail \
    && git -C vendor/vangrail checkout --quiet "$VANGRAIL_REV" \
    && test "$(git -C vendor/vangrail rev-parse HEAD)" = "$VANGRAIL_REV" \
    && ruby -Ivendor/vangrail/lib -e 'require "vangrail"; require "./rails/ruby/grund_cell_claim_rail"; raise Vangrail::VERSION unless Vangrail::VERSION == "0.3.0"' \
    && rm -rf vendor/vangrail/.git

ARG E5_REV=761b726dd34fb83930e26aab4e9ac3899aa1fa78
RUN mkdir -p data/models/small/onnx \
    && curl -fsSL -o data/models/small/tokenizer_config.json \
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/${E5_REV}/tokenizer_config.json" \
    && curl -fsSL -o data/models/small/tokenizer.json \
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/${E5_REV}/tokenizer.json" \
    && curl -fsSL -o data/models/small/onnx/model_int8.onnx \
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/${E5_REV}/onnx/model_int8.onnx" \
    && echo "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b  data/models/small/tokenizer_config.json" | sha256sum -c - \
    && echo "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39  data/models/small/tokenizer.json" | sha256sum -c - \
    && echo "4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c  data/models/small/onnx/model_int8.onnx" | sha256sum -c -

ENV PYTHONPATH=/app/lang:/app/indexer:/app/evalset:/app/rails:/app/app
RUN python3 -m grund_lang build \
        --catalogue data/catalogue.jsonl \
        --source data/index \
        --out data/index-lang \
        --embeddings chargram

COPY --from=ui /src/dist ./app/web/dist

RUN useradd --create-home --uid 10001 grund \
    && chown -R grund:grund /app
USER grund

EXPOSE 8741
CMD ["sh", "script/freeze_run.sh"]
