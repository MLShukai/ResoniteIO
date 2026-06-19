# syntax=docker/dockerfile:1.7
#
# resonite-io 開発環境イメージ。
#   - debian:13-slim ベース。
#   - .NET 10 SDK / uv / just / protoc を /usr/local 配下に root で固定インストール。
#   - host UID/GID 一致の `dev` ユーザーで実行 (bind 経由の成果物が host 所有になる)。
#   - ソースコードは image に焼かない。host repo を `/workspace` に bind mount し、
#     dotnet tool restore / uv sync / pre-commit install は scripts/container-init.sh が
#     冪等に行う。
#   - Resonite 起動用に X11 / GPU / audio / umu-launcher / Proton 関連を追加。

FROM debian:13-slim

ARG USER_UID=1000
ARG USER_GID=1000
ARG DOTNET_CHANNEL=10.0
ARG PROTOC_VERSION=29.3
# GPU vendor: nvidia | amd | intel。
# nvidia: Mesa 不要 (nvidia-container-toolkit が host ドライバを inject)。
# amd / intel: Mesa を image に焼き込む。
ARG GPU=nvidia

ENV DOTNET_ROOT=/usr/local/dotnet
ENV HOME=/home/dev
# $HOME/.local/bin は `uv tool install` の既定インストール先。
ENV PATH=/usr/local/dotnet:/usr/local/bin:/home/dev/.local/bin:$PATH
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
ENV DOTNET_NOLOGO=1

# Proton/Wine は 32bit コードを含むため i386 アーキテクチャを有効化する。
# apt-get update より先に dpkg --add-architecture を実行する必要がある。
RUN dpkg --add-architecture i386

# uv が独自 Python を引くため build-essential は不要。
# python3 は debug bridge client (scripts/resonite_cli.py) 専用で、uv 管理の
# Python 環境とは分離した stdlib 実行用 (PYTHONPATH も share しない)。
# libicu76 は .NET SDK の globalization 初期化に必要 (debian 13 trixie の ICU)。
# dbus-x11 は dbus-launch を提供する (Steam Linux Runtime の launcher-service が必要)。
# rsync は entrypoint.sh が Resonite インストールを named volume にコピーするために使う。
# x11-apps は X11 接続の smoke test 用 (xeyes 等)。
# locales + locale-gen は VS Code 等が転送する en_US.UTF-8 ロケールを生成し、
# bash 起動時の "cannot change locale" 警告を抑止する (slim は C.utf8 のみ同梱)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        unzip \
        tar \
        tmux \
        procps \
        ca-certificates \
        xz-utils \
        bash-completion \
        libatomic1 \
        libicu76 \
        netcat-openbsd \
        openssh-client \
        ffmpeg \
        python3 \
        shellcheck \
        shfmt \
        sudo \
        dbus-x11 \
        rsync \
        x11-apps \
        libpulse0 \
        locales \
 && sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
 && locale-gen \
 && rm -rf /var/lib/apt/lists/*

# GPU ユーザースペース (GL/Vulkan ローダ 32/64bit + 条件付き Mesa)。
# NVIDIA: GLVND/Vulkan ローダのみ (ドライバは nvidia-container-toolkit が inject)。
# AMD/Intel: Mesa を同梱 (ドライバが host から inject されないため)。
#   mesa-vulkan-drivers は RADV (AMD) と ANV (Intel) の両 Vulkan ICD を含む。
#   対応 PCI ID を持つ GPU のみが実デバイスとして列挙されるため、
#   Intel 環境では ANV、AMD 環境では RADV が自動選択される。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgl1 libgl1:i386 \
      libvulkan1 libvulkan1:i386 \
      vulkan-tools \
 && if [ "$GPU" = "amd" ] || [ "$GPU" = "intel" ]; then \
      apt-get install -y --no-install-recommends \
        libglx-mesa0 libglx-mesa0:i386 \
        libgl1-mesa-dri libgl1-mesa-dri:i386 \
        mesa-vulkan-drivers mesa-vulkan-drivers:i386; \
    fi \
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

# umu-launcher を GitHub Releases の debian-13 向け .deb から導入。
# umu-run は Proton/SteamRT を自動取得して Wine アプリを起動する。
# Resonite の起動は scripts/resonite-run.sh が umu-run 経由で行う。
RUN set -eux; \
    apt-get update; \
    cd /tmp; \
    curl -fsSL https://api.github.com/repos/Open-Wine-Components/umu-launcher/releases/latest \
      | grep -oE 'https://[^"]+(amd64|all)_debian-13[^"]*\.deb' \
      | xargs -n1 curl -fsSL -O; \
    apt-get install -y --no-install-recommends ./*.deb; \
    rm -rf /var/lib/apt/lists/* /tmp/*.deb

# debian 13 の /etc/bash.bashrc は bash-completion ローダ部がコメントアウトされて
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
# Resonite 用 named volume のマウント先も dev 所有で先行作成:
#   /opt/resonite     : Resonite インストールコピー (HOME 外に置く理由は entrypoint 参照)
#   /home/dev/.local/share : SteamRT / Proton + Resonite ユーザーデータ
#   /home/dev/prefix  : Wine prefix (WINEPREFIX)
# /home/dev/.cache は resonite-cache volume のマウント先 (cache-uv とネスト)。
RUN groupadd -g ${USER_GID} dev \
 && useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/bash dev \
 && mkdir -p \
      /home/dev/.nuget/packages \
      /home/dev/.cache/uv \
      /home/dev/.claude \
      /home/dev/.codex \
 && install -d -o dev -g dev \
      /opt/resonite \
      /home/dev/.local \
      /home/dev/.local/share \
      /home/dev/prefix \
 && chown -R dev:dev /home/dev \
 && echo 'dev ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/dev \
 && chmod 0440 /etc/sudoers.d/dev

# machine-id はコンテナ毎に entrypoint.sh が /proc/sys/kernel/random/uuid から生成する。
# dev 所有の空ファイルを先に作り、非 root ユーザーが書き込めるようにする。
# /var/lib/dbus/machine-id は /etc/machine-id へのシンボリックリンクとする。
RUN install -o dev -g dev -m 0644 /dev/null /etc/machine-id \
 && mkdir -p /var/lib/dbus \
 && ln -sf /etc/machine-id /var/lib/dbus/machine-id

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER dev
WORKDIR /workspace

# umu 用 ENV。WINEPREFIX / Proton / アセットキャッシュはすべて named volume で永続化。
# GAMEID=umu-default: umu DB 未登録ゲーム向けの汎用 ID。
# PROTONPATH=GE-Proton: GE-Proton を使うことで起動時スプラッシュロゴの描画崩れを回避
#   (Valve Proton では Unity テクスチャがカラーバー表示になる問題がある)。
#   umu が GitHub Releases から最新版を自動取得し ~/.local/share/Steam/compatibilitytools.d に展開する。
ENV GAMEID=umu-default \
    WINEPREFIX=/home/dev/prefix \
    PROTONPATH=GE-Proton

# Claude Code / Codex CLI は公式 install.sh (native installer) で最新版を入れる。
# apt / npm 版ではなく standalone installer に揃える。どちらも $HOME/.local/bin に
# 落とすので dev user 切替後に実行する ($HOME/.local は volume マウント対象外なので
# image に焼き込んだバイナリがそのまま残る)。
RUN curl -fsSL https://claude.ai/install.sh | bash

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]
