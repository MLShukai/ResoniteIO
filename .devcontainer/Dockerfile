# syntax=docker/dockerfile:1.7
#
# resonite-io 開発環境イメージ。
#   - debian:bookworm-slim ベース。
#   - .NET 10 SDK / uv / just / protoc を /usr/local 配下に root で固定インストール。
#   - host UID/GID 一致の `dev` ユーザーで実行 (bind 経由の成果物が host 所有になる)。
#   - ソースコードは image に焼かない。host repo を `/workspace` に bind mount し、
#     dotnet tool restore / uv sync / pre-commit install は scripts/container-init.sh が
#     冪等に行う。

FROM debian:bookworm-slim

ARG USER_UID=1000
ARG USER_GID=1000
ARG DOTNET_CHANNEL=10.0
ARG PROTOC_VERSION=29.3

ENV DOTNET_ROOT=/usr/local/dotnet
ENV HOME=/home/dev
# $HOME/.local/bin は `uv tool install` の既定インストール先。
ENV PATH=/usr/local/dotnet:/usr/local/bin:/home/dev/.local/bin:$PATH
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
ENV DOTNET_NOLOGO=1

# uv が独自 Python を引くため build-essential は不要。
# python3 は debug bridge client (scripts/resonite_cli.py) 専用で、uv 管理の
# Python 環境とは分離した stdlib 実行用 (PYTHONPATH も share しない)。
# libicu72 は .NET SDK の globalization 初期化に必要 (bookworm-slim には含まれない)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        unzip \
        tar \
        tmux \
        ca-certificates \
        xz-utils \
        bash-completion \
        libatomic1 \
        libicu72 \
        netcat-openbsd \
        openssh-client \
        ffmpeg \
        python3 \
        shellcheck \
        shfmt \
        sudo \
 && rm -rf /var/lib/apt/lists/*

# ツール一式を /usr/local 配下に 1 RUN でインストール (レイヤ削減)。
RUN set -eux; \
    curl -LsSf https://astral.sh/uv/install.sh \
      | UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh; \
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
      | bash -s -- --to /usr/local/bin; \
    arch="$(uname -m | sed 's/aarch64/aarch_64/;s/arm64/aarch_64/')"; \
    curl -fsSL \
      "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-linux-${arch}.zip" \
      -o /tmp/protoc.zip; \
    unzip -oq /tmp/protoc.zip -d /usr/local; \
    rm -f /tmp/protoc.zip; \
    curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh; \
    chmod +x /tmp/dotnet-install.sh; \
    /tmp/dotnet-install.sh --channel "${DOTNET_CHANNEL}" --install-dir /usr/local/dotnet; \
    rm -f /tmp/dotnet-install.sh

# GitHub CLI (gh) は公式 apt リポジトリから入れる。Claude から `git push` や
# `gh pr create` を行うため。
RUN set -eux; \
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends gh; \
    rm -rf /var/lib/apt/lists/*

# bookworm-slim の /etc/bash.bashrc は bash-completion ローダ部がコメントアウトされて
# おり、`docker exec dev bash` は非 login 対話 shell で /etc/profile.d/bash_completion.sh
# も読まれないため、明示的にローダ呼び出しを追記する。
RUN set -eux; \
    uv generate-shell-completion bash > /etc/bash_completion.d/uv; \
    uvx --generate-shell-completion bash > /etc/bash_completion.d/uvx; \
    just --completions bash > /etc/bash_completion.d/just; \
    echo '[ -f /usr/share/bash-completion/bash_completion ] && . /usr/share/bash-completion/bash_completion' \
      >> /etc/bash.bashrc; \
    echo '[ -f /workspace/clicomp.sh ] && . /workspace/clicomp.sh' >> /etc/bash.bashrc

# キャッシュ系 (.nuget / .cache/uv) は named volume のマウント先で、Docker が初回
# マウント時に target dir の所有権/モードを継承するため dev 所有で先行作成しておく。
# /home/dev/.claude は container-init.sh が settings.container.json への symlink を
# 張る前提でディレクトリだけ用意する。/home/dev/.codex は Codex CLI の
# 認証・設定 state を compose volume に載せるため先行作成する。
RUN groupadd -g ${USER_GID} dev \
 && useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/bash dev \
 && mkdir -p /home/dev/.nuget/packages /home/dev/.cache/uv /home/dev/.claude /home/dev/.codex \
 && chown -R dev:dev /home/dev \
 && echo 'dev ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/dev \
 && chmod 0440 /etc/sudoers.d/dev

USER dev
WORKDIR /workspace

# Claude Code / Codex CLI は公式 install.sh (native installer) で最新版を入れる。
# apt / npm 版ではなく standalone installer に揃える。どちらも $HOME/.local/bin に
# 落とすので dev user 切替後に実行する ($HOME/.local は volume マウント対象外なので
# image に焼き込んだバイナリがそのまま残る)。
RUN curl -fsSL https://claude.ai/install.sh | bash \
 && curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh

CMD ["sleep", "infinity"]
