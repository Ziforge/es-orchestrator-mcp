# es-orchestrator-mcp

MCP server that orchestrates all three [Expert Sleepers](https://expert-sleepers.co.uk/) Eurorack modules — FH-2, ES-9, and Disting NT — through a single unified interface.

Provides 41 tools for cross-module MIDI CC mapping, proxied per-module operations, system-wide control, a bundled library of ~114 Disting NT algorithm metadata (searchable offline), and an optional HTTP proxy to [thorinside/nt_helper](https://github.com/thorinside/nt_helper) for live routing visualization and editing.

Part of the [Expert Sleepers MCP suite](https://github.com/Ziforge):
[fh2-mcp](https://github.com/Ziforge/fh2-mcp) |
[es9-mcp](https://github.com/Ziforge/es9-mcp) |
[disting-nt-mcp](https://github.com/Ziforge/disting-nt-mcp) |
[es-orchestrator-mcp](https://github.com/Ziforge/es-orchestrator-mcp)

## Why an Orchestrator?

macOS cannot share MIDI output ports between processes. When you need to control multiple Expert Sleepers modules simultaneously, the orchestrator replaces the individual per-module MCP servers with a single process that holds all MIDI connections.

It also provides features that span modules:
- **FH-2 CV to Disting NT parameter mapping** via MIDI CC bridges
- **Multi-parameter macros** — one CC controlling several NT parameters with independent scaling
- **Parameter sweeps** — automated ramps across NT parameter values
- **ES-9 CV generation** — LFOs, gates, envelopes, and static voltages via audio output
- **Algorithm metadata search** — fuzzy offline search across all ~114 Disting NT algorithms
- **nt_helper integration** — optional proxy to the Flutter companion app

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- One or more Expert Sleepers modules connected via USB
- Sibling MCP projects cloned alongside: `fh2-mcp/`, `es9-mcp/`, `disting-nt-mcp/`

## Setup

```bash
git clone https://github.com/Ziforge/es-orchestrator-mcp.git
cd es-orchestrator-mcp
uv sync
cp .env.example .env  # edit with your port names
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FH2_OUTPUT_PORT` | *(empty)* | FH-2 MIDI output (substring match, auto-detects) |
| `FH2_INPUT_PORT` | *(empty)* | FH-2 MIDI input |
| `FH2_MIDI_CHANNEL` | `1` | FH-2 MIDI channel (1-16) |
| `ES9_OUTPUT_PORT` | *(empty)* | ES-9 MIDI output |
| `ES9_INPUT_PORT` | *(empty)* | ES-9 MIDI input |
| `ES9_AUDIO_DEVICE` | *(empty)* | ES-9 audio device (for CV generation) |
| `ES9_SAMPLE_RATE` | `48000` | Audio sample rate |
| `DISTING_NT_OUTPUT_PORT` | *(empty)* | Disting NT MIDI output |
| `DISTING_NT_INPUT_PORT` | *(empty)* | Disting NT MIDI input |
| `DISTING_NT_SYSEX_ID` | `0` | Disting NT SysEx device ID |
| `DISTING_NT_MIDI_CHANNEL` | `1` | Disting NT MIDI channel |
| `NT_HELPER_URL` | *(empty)* | nt_helper MCP endpoint (e.g. `http://localhost:3847/mcp`) |
| `AUTO_CONNECT` | `false` | Connect all modules on server start |

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "es-orchestrator": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/es-orchestrator-mcp", "python", "server.py"]
    }
  }
}
```

## Tools (41)

### 1. System (4)
| Tool | Description |
|------|-------------|
| `system_status` | Connection/state info for all modules + metadata + proxy status |
| `connect_module` | Connect a module (`fh2`, `es9`, `nt`, or `all`) |
| `disconnect_module` | Disconnect a module |
| `list_midi_ports` | List all available MIDI I/O ports |

### 2. Cross-Module Mapping (3)
| Tool | Description |
|------|-------------|
| `map_fh2_to_nt_param` | Map an FH-2 CV output to a Disting NT parameter via MIDI CC |
| `fh2_control_nt_param` | Send a CC from FH-2 to a mapped NT parameter |
| `setup_fh2_nt_bridge` | Batch-configure multiple FH-2 CV to NT mappings |

### 3. Presets (2)
| Tool | Description |
|------|-------------|
| `recall_system_preset` | Load a Disting NT preset and report system state |
| `save_system_state` | Save the current NT preset |

### 4. Proxied Module Operations (8)
| Tool | Description |
|------|-------------|
| `fh2_set_cv` | Set an FH-2 CV output via CC |
| `fh2_send_cc` | Send a MIDI CC from the FH-2 |
| `fh2_read_display` | Read the FH-2 OLED display text |
| `nt_get_loaded_algorithms` | List all algorithms in the NT preset |
| `nt_set_parameter` | Set a Disting NT parameter value |
| `nt_get_preset_name` | Get the current NT preset name |
| `nt_take_screenshot` | Capture the NT display as ASCII art |
| `es9_get_cpu_usage` | Get ES-9 CPU usage |

### 5. Safety (1)
| Tool | Description |
|------|-------------|
| `system_panic` | Emergency silence — panic all connected modules |

### 6. ES-9 Mixer & Routing (6)
| Tool | Description |
|------|-------------|
| `es9_set_mix_level` | Set a channel's level on an ES-9 mix bus |
| `es9_set_mix_pan` | Set a channel's pan position |
| `es9_set_input_routing` | Set ES-9 capture routing for a DSP block |
| `es9_set_output_routing` | Set ES-9 output routing |
| `es9_reset_mixer` | Reset mixer to defaults |
| `es9_set_options` | Set ES-9 global options |

### 7. FH-2 LFO Control (3)
| Tool | Description |
|------|-------------|
| `fh2_configure_lfo` | Configure multiple FH-2 LFO parameters at once |
| `fh2_set_lfo_param` | Set a single FH-2 LFO parameter |
| `fh2_reset_lfo` | Reset an FH-2 LFO to defaults |

### 8. ES-9 CV Generation (4)
| Tool | Description |
|------|-------------|
| `es9_set_cv_voltage` | Set a static CV voltage on an ES-9 audio output |
| `es9_set_cv_gate` | Set a gate CV on an ES-9 audio output |
| `es9_generate_lfo` | Generate an LFO waveform on an ES-9 output |
| `es9_trigger_envelope` | Trigger an attack-release envelope |

### 9. Multi-Param Macros (3)
| Tool | Description |
|------|-------------|
| `map_macro_to_nt_params` | Map one MIDI CC to multiple NT parameters |
| `nt_batch_set_parameters` | Set multiple NT parameters in one call |
| `sweep_nt_param` | Sweep a parameter from start to end over time |

### 10. NT Algorithm Metadata (2) — offline, no device needed
| Tool | Description |
|------|-------------|
| `nt_search_algorithms` | Fuzzy search over ~114 bundled algorithm descriptions |
| `nt_algorithm_info` | Full detail by GUID or name: params, I/O ports, categories |

### 11. nt_helper Proxy (5) — optional, requires Flutter app
| Tool | Description |
|------|-------------|
| `nt_helper_show_routing` | Show current NT routing as a visual diagram |
| `nt_helper_show_screen` | Show current NT screen content |
| `nt_helper_edit_slot` | Edit parameters on a specific algorithm slot |
| `nt_helper_add_algorithm` | Add an algorithm by name or GUID |
| `nt_helper_search_parameters` | Search parameters across the current preset |

## Algorithm Metadata

The `data/nt_algorithms.json` file bundles metadata for all ~114 Disting NT algorithms sourced from [thorinside/nt_helper](https://github.com/thorinside/nt_helper). This enables offline fuzzy search by name, category, description, or parameter name — no device connection required.

To update the bundled metadata after nt_helper publishes new algorithms:

```bash
python scripts/update_algorithms.py
```

Requires the `gh` CLI authenticated with GitHub.

## nt_helper Proxy

When `NT_HELPER_URL` is set (e.g. `http://localhost:3847/mcp`), the orchestrator can proxy requests to the [nt_helper](https://github.com/thorinside/nt_helper) Flutter companion app. This provides:

- **Routing visualization** — see how algorithms are connected
- **Screen capture** — view the NT display remotely
- **Live editing** — add algorithms and edit parameters by name
- **Parameter search** — find parameters across the current preset

The proxy is optional and degrades gracefully — if the app is not running, proxy tools return clear error messages and all other tools continue to work normally.

## Architecture

```
server.py             — FastMCP tool definitions (41 tools)
orchestrator.py       — Core orchestration: cross-module mapping, macros, sweeps
nt_metadata.py        — NTMetadataStore: offline algorithm search (stdlib only)
nt_helper_proxy.py    — NTHelperProxy: async httpx JSON-RPC 2.0 client
config.py             — Configuration from environment
data/                 — Bundled algorithm metadata
scripts/              — Maintenance scripts (update_algorithms.py)
```

The orchestrator imports engine classes from sibling MCP projects (`fh2-mcp/`, `es9-mcp/`, `disting-nt-mcp/`) at runtime, isolating module imports to prevent name collisions.
