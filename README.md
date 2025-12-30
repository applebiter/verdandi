# Verdandi

A local-first, peer-to-peer platform for building always-on, multi-node AI systems on a LAN with integrated real-time audio and MIDI fabric.

## Components

- **Verdandi Engine** - Always-on headless node daemon (systemd-managed)
- **Verdandi Hall** - PySide6 GUI application for configuration and monitoring
- **Verdandi Rune** - CLI for operations, debugging, and scripting
- **Verdandi Codex** - Shared SDK/library used by all components

## Requirements

- Linux (Ubuntu/Debian or Arch-based distributions)
- Python 3.10+
- JACK Audio Connection Kit
- JackTrip
- PostgreSQL 14+ with pgvector extension

## Installation

```bash
# Clone the repository
git clone https://github.com/applebiter/verdandi.git
cd verdandi

# Install dependencies
pip install -e .

# For GUI support
pip install -e ".[gui]"

# For voice features
pip install -e ".[voice]"

# For development
pip install -e ".[dev]"
```

## Quick Start

Documentation is under development alongside the implementation.

## License

MIT
