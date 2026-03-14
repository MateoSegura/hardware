FROM ubuntu:24.04

# ── Environment ───────────────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    IS_SANDBOX=1 \
    PATH="/root/.local/bin:$PATH"

# ── Version pins ──────────────────────────────────────────────────────────────
ARG KICAD_PPA_VERSION=9
ARG NODE_MAJOR=24

# ── Base system packages ─────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    less \
    lsb-release \
    make \
    nano \
    openssh-client \
    procps \
    software-properties-common \
    sudo \
    tree \
    unzip \
    vim \
    wget \
    zip \
    zsh \
    && rm -rf /var/lib/apt/lists/*

# ── Python 3 (full stack) ────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-dev \
    python3-full \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ── KiCad 9 (CLI + libraries) ───────────────────────────────────────────────
# We need kicad-cli for headless ERC, DRC, netlist export, Gerber generation.
# The full KiCad GUI is not needed — CLI is sufficient for our pipeline.
RUN add-apt-repository -y ppa:kicad/kicad-${KICAD_PPA_VERSION}.0-releases \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        kicad \
        kicad-libraries \
    && rm -rf /var/lib/apt/lists/*

# ── GitHub CLI ───────────────────────────────────────────────────────────────
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# ── Docker CLI (uses host Docker socket) ─────────────────────────────────────
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js (for devcontainer CLI) ───────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code ──────────────────────────────────────────────────────────────
RUN curl -fsSL https://claude.ai/install.sh | bash

# ── ripgrep + fd (used by Claude Code internals) ─────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    fd-find \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# ── Python packages for hardware pipeline ────────────────────────────────────
RUN pip3 install --break-system-packages \
    kiutils \
    sexpdata \
    httpx \
    pandas \
    pytest \
    pytest-asyncio \
    pyyaml \
    rich \
    ruff \
    typer \
    claude-code-sdk

# ── Oh My Zsh ────────────────────────────────────────────────────────────────
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended \
    && git clone https://github.com/zsh-users/zsh-autosuggestions /root/.oh-my-zsh/custom/plugins/zsh-autosuggestions \
    && git clone https://github.com/zsh-users/zsh-syntax-highlighting /root/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting \
    && sed -i 's/plugins=(git)/plugins=(git docker python pip npm zsh-autosuggestions zsh-syntax-highlighting)/' /root/.zshrc \
    && echo 'export PATH="/root/.local/bin:$PATH"' >> /root/.zshrc \
    && echo 'export IS_SANDBOX=1' >> /root/.zshrc \
    && chsh -s /usr/bin/zsh root

WORKDIR /workspace
CMD ["sleep", "infinity"]
