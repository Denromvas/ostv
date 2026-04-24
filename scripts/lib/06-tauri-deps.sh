#!/bin/bash
# 06-tauri-deps.sh
# Встановлює Rust toolchain та системні deps для побудови Tauri 2 app.
# Ідемпотентний.
#
# Usage:
#   sudo bash 06-tauri-deps.sh        # system deps (apt, потрібен root)
#   bash 06-tauri-deps.sh --user-rust # rustup під поточного юзера (dromanyuk)

set +e

if [ "$1" == "--user-rust" ]; then
    echo "=== Installing Rust via rustup (as $USER) ==="
    if command -v rustc >/dev/null 2>&1; then
        echo "Rust already installed: $(rustc --version)"
    else
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
        export PATH="$HOME/.cargo/bin:$PATH"
        echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> "$HOME/.bashrc"
    fi
    rustc --version
    cargo --version
    exit 0
fi

# System deps (root)
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: запускати як root через sudo (або з флагом --user-rust для Rust)"
    exit 1
fi

echo "=== apt install Tauri 2 system deps ==="
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    libwebkit2gtk-4.1-dev \
    libayatana-appindicator3-dev \
    librsvg2-dev \
    libxdo-dev \
    libssl-dev \
    build-essential \
    file \
    patchelf \
    pkg-config \
    2>&1 | tail -5

echo
echo "=== Versions ==="
dpkg -s libwebkit2gtk-4.1-dev 2>/dev/null | grep Version
dpkg -s libayatana-appindicator3-dev 2>/dev/null | grep Version
node --version
npm --version
echo "Rust — install окремо під user: bash 06-tauri-deps.sh --user-rust"

echo "=== Done (system deps). ==="
