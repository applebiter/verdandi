# Verdandi

A local-first, peer-to-peer platform for building always-on, multi-node AI systems on a LAN with integrated real-time audio and MIDI.

## Overview

Verdandi enables distributed AI workflows across multiple machines on your local network, with built-in support for:

- **Real-time Audio/MIDI Routing** - JACK integration with JackTrip for low-latency networked audio
- **Remote Control** - Manage JACK graphs and audio connections on any node from the GUI
- **Automatic Discovery** - mDNS-based node discovery with certificate-based security
- **Persistent Topology** - Save and auto-restore audio routing configurations per node
- **Privacy-First** - All data stays local; no cloud dependencies

## Components

- **Verdandi Engine** (`verdandi-engine`) - Always-on headless node daemon with gRPC services
- **Verdandi Hall** (`verdandi-hall`) - PySide6 GUI for visualization and control
- **Verdandi Rune** (`verdandi-rune`) - CLI for operations and scripting
- **Verdandi Codex** (`verdandi-codex`) - Shared SDK/library used by all components

## Features

### Current (December 2025)
- ✅ Local and remote JACK graph visualization
- ✅ Drag-and-drop audio/MIDI connection management
- ✅ JackTrip hub/client controls with automatic node naming
- ✅ Per-node preset system with auto-restore
- ✅ Automatic state detection and UI synchronization
- ✅ mDNS-based node discovery and registration
- ✅ gRPC-based remote control with mTLS security

### In Development
- 🚧 Task orchestration system
- 🚧 Voice integration and session management

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
