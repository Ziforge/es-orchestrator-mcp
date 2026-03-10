"""Expert Sleepers Orchestrator MCP Server — unified control of FH-2, ES-9, and Disting NT."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import Context, FastMCP

from config import OrchestratorConfig
from nt_metadata import NTMetadataStore
from nt_helper_proxy import NTHelperProxy
from orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Lifespan: initialize orchestrator + optional auto-connect
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    config = OrchestratorConfig.from_env()
    orch = Orchestrator(config)

    if config.auto_connect:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, orch.connect_all)
        for module, result in results.items():
            print(f"[es-orchestrator] {module}: {result}")

    # Load bundled algorithm metadata
    metadata = NTMetadataStore()
    try:
        metadata.load()
        print(f"[es-orchestrator] Algorithm metadata: {metadata.count} algorithms loaded")
    except Exception as e:
        print(f"[es-orchestrator] Algorithm metadata failed to load: {e}")

    # Optional nt_helper proxy
    nt_proxy: NTHelperProxy | None = None
    if config.nt_helper_url:
        nt_proxy = NTHelperProxy(config.nt_helper_url)
        available = await nt_proxy.check_available()
        if available:
            print(f"[es-orchestrator] nt_helper proxy: connected ({config.nt_helper_url})")
        else:
            print(f"[es-orchestrator] nt_helper proxy: configured but not reachable ({config.nt_helper_url})")

    yield {
        "orchestrator": orch,
        "config": config,
        "metadata": metadata,
        "nt_proxy": nt_proxy,
    }

    # Cleanup
    if nt_proxy:
        await nt_proxy.close()
    orch.disconnect_all()


mcp = FastMCP(
    "es-orchestrator",
    instructions=(
        "Orchestrate Expert Sleepers Eurorack modules: FH-2 (MIDI-to-CV), "
        "ES-9 (USB audio interface), and Disting NT (multi-algorithm DSP). "
        "Provides cross-module MIDI CC mapping, proxied single-module operations, "
        "and system-wide control. Includes a bundled library of ~114 Disting NT "
        "algorithm metadata (searchable offline — no device needed) and an optional "
        "proxy to thorinside/nt_helper for live routing visualization and editing. "
        "When the orchestrator is running, individual per-module MCP servers should "
        "be stopped (macOS can't share MIDI output ports between processes)."
    ),
    lifespan=lifespan,
)


def _orch(ctx: Context) -> Orchestrator:
    return ctx.request_context.lifespan_context["orchestrator"]


def _config(ctx: Context) -> OrchestratorConfig:
    return ctx.request_context.lifespan_context["config"]


def _require_fh2(ctx: Context) -> Orchestrator:
    orch = _orch(ctx)
    if not orch.fh2.connected:
        raise ValueError("FH-2 not connected. Use connect_module('fh2') first.")
    return orch


def _require_es9(ctx: Context) -> Orchestrator:
    orch = _orch(ctx)
    if not orch.es9.midi_connected:
        raise ValueError("ES-9 not connected. Use connect_module('es9') first.")
    return orch


def _require_nt(ctx: Context) -> Orchestrator:
    orch = _orch(ctx)
    if not orch.nt.connected:
        raise ValueError("Disting NT not connected. Use connect_module('nt') first.")
    return orch


def _metadata(ctx: Context) -> NTMetadataStore:
    return ctx.request_context.lifespan_context["metadata"]


def _nt_proxy(ctx: Context) -> NTHelperProxy | None:
    return ctx.request_context.lifespan_context.get("nt_proxy")


def _require_nt_proxy(ctx: Context) -> NTHelperProxy:
    proxy = _nt_proxy(ctx)
    if proxy is None:
        raise ValueError(
            "nt_helper proxy not configured. Set NT_HELPER_URL in .env "
            "(e.g. http://localhost:3847/mcp) and restart."
        )
    if proxy.available is False:
        raise ValueError(
            "nt_helper proxy is configured but not reachable. "
            "Ensure the nt_helper Flutter app is running."
        )
    return proxy


async def _ensure_es9_audio(ctx: Context) -> Orchestrator:
    """Require ES-9 MIDI and auto-start audio stream if not running."""
    orch = _require_es9(ctx)
    if not orch.es9.audio_running:
        config = _config(ctx)
        device = config.es9_audio_device
        if not device:
            raise ValueError(
                "ES9_AUDIO_DEVICE not configured. Set it in .env for CV generation."
            )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: orch.es9.connect_audio(
                device=device, sample_rate=config.es9_sample_rate
            ),
        )
    return orch


# ===================================================================
# 1. SYSTEM TOOLS (4)
# ===================================================================


@mcp.tool()
async def system_status(ctx: Context) -> str:
    """Show connection and state info for all three Expert Sleepers modules."""
    orch = _orch(ctx)
    loop = asyncio.get_event_loop()
    status = await loop.run_in_executor(None, orch.get_status)

    lines = ["=== Expert Sleepers Orchestrator ==="]
    for module, info in status.items():
        label = {"fh2": "FH-2", "es9": "ES-9", "nt": "Disting NT"}[module]
        connected = info.get("connected", False)
        lines.append(f"\n  [{label}] {'CONNECTED' if connected else 'disconnected'}")
        if connected:
            lines.append(f"    Ports: {info.get('ports', '?')}")
            if "firmware" in info:
                lines.append(f"    Firmware: {info['firmware']}")
            if "preset" in info:
                lines.append(f"    Preset: {info['preset']}")
        if module == "es9":
            audio = info.get("audio_running", False)
            lines.append(f"    Audio: {'RUNNING' if audio else 'stopped'}")
            cv_sources = info.get("cv_sources", {})
            if cv_sources:
                for ch, desc in cv_sources.items():
                    lines.append(f"    CV ch{ch}: {desc}")

    # Algorithm metadata status
    meta = _metadata(ctx)
    lines.append(f"\n  [Algorithm Library] loaded ({meta.count} algorithms)" if meta.count > 0
                 else "\n  [Algorithm Library] not loaded")

    # nt_helper proxy status
    proxy = _nt_proxy(ctx)
    if proxy is None:
        lines.append("  [nt_helper Proxy] not configured")
    elif proxy.available:
        lines.append("  [nt_helper Proxy] connected")
    else:
        lines.append("  [nt_helper Proxy] configured but not reachable")

    return "\n".join(lines)


@mcp.tool()
async def connect_module(ctx: Context, module: str) -> str:
    """Connect to a specific module.

    Args:
        module: Module name: "fh2", "es9", or "nt" (also accepts "disting", "disting_nt").
            Use "all" to connect to all modules.
    """
    orch = _orch(ctx)
    loop = asyncio.get_event_loop()

    if module.lower().strip() == "all":
        results = await loop.run_in_executor(None, orch.connect_all)
        lines = ["Connect all:"]
        for m, r in results.items():
            label = {"fh2": "FH-2", "es9": "ES-9", "nt": "Disting NT"}[m]
            lines.append(f"  {label}: {r}")
        return "\n".join(lines)

    result = await loop.run_in_executor(
        None, lambda: orch.connect_module(module)
    )
    return f"Connected {module}: {result}"


@mcp.tool()
async def disconnect_module(ctx: Context, module: str) -> str:
    """Disconnect a specific module.

    Args:
        module: Module name: "fh2", "es9", or "nt".
            Use "all" to disconnect all modules.
    """
    orch = _orch(ctx)
    loop = asyncio.get_event_loop()

    if module.lower().strip() == "all":
        results = await loop.run_in_executor(None, orch.disconnect_all)
        lines = ["Disconnect all:"]
        for m, r in results.items():
            label = {"fh2": "FH-2", "es9": "ES-9", "nt": "Disting NT"}[m]
            lines.append(f"  {label}: {r}")
        return "\n".join(lines)

    result = await loop.run_in_executor(
        None, lambda: orch.disconnect_module(module)
    )
    return f"Disconnected {module}: {result}"


@mcp.tool()
async def list_midi_ports(ctx: Context) -> str:
    """List all available MIDI input and output ports on the system."""
    orch = _orch(ctx)
    loop = asyncio.get_event_loop()

    # Use FH2Engine's static methods (they're all the same rtmidi call)
    out_ports = await loop.run_in_executor(None, orch.fh2.list_output_ports)
    in_ports = await loop.run_in_executor(None, orch.fh2.list_input_ports)

    lines = ["=== Output Ports ==="]
    for i, p in enumerate(out_ports):
        lines.append(f"  [{i}] {p}")
    if not out_ports:
        lines.append("  (none)")

    lines.append("\n=== Input Ports ===")
    for i, p in enumerate(in_ports):
        lines.append(f"  [{i}] {p}")
    if not in_ports:
        lines.append("  (none)")

    return "\n".join(lines)


# ===================================================================
# 2. CROSS-MODULE MAPPING TOOLS (3)
# ===================================================================


@mcp.tool()
async def map_fh2_to_nt_param(
    ctx: Context,
    nt_algo: int,
    nt_param: int,
    midi_cc: int,
    fh2_cv: int,
    midi_channel: int = 0,
) -> str:
    """Map an FH-2 CV output to a Disting NT parameter via MIDI CC.

    Sets up the MIDI CC mapping on the Disting NT side. The FH-2 CV output
    should be configured to send the specified MIDI CC (via FH-2 config).

    Args:
        nt_algo: Disting NT algorithm slot index (0-based).
        nt_param: Parameter number within the algorithm (0-based).
        midi_cc: MIDI CC number to use for the bridge (0-127).
        fh2_cv: FH-2 CV output number (1-8) that will send this CC.
        midi_channel: MIDI channel (0=omni, 1-15 for specific).
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None,
        lambda: orch.map_fh2_cv_to_nt_param(
            nt_algo, nt_param, midi_cc, fh2_cv, midi_channel
        ),
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return (
        f"Mapped: FH-2 CV{result['fh2_cv']} → CC{result['midi_cc']} → "
        f"NT slot {result['nt_algo']} '{result['param_name']}' "
        f"(param {result['nt_param']})\n"
        f"  Parameter range: {result['param_range']}\n"
        f"  MIDI channel: {'omni' if result['midi_channel'] == 0 else result['midi_channel']}"
    )


@mcp.tool()
async def fh2_control_nt_param(
    ctx: Context,
    midi_cc: int,
    value: int,
    channel: int = 1,
) -> str:
    """Send a MIDI CC from FH-2 to control a mapped Disting NT parameter.

    Requires an active MIDI CC mapping on the Disting NT (use map_fh2_to_nt_param first).
    The CC is sent from the FH-2's MIDI output to the NT's MIDI input via USB.

    Args:
        midi_cc: MIDI CC number (must match the mapping set on the NT).
        value: CC value 0-127.
        channel: MIDI channel 1-16.
    """
    orch = _require_fh2(ctx)
    loop = asyncio.get_event_loop()

    await loop.run_in_executor(
        None, lambda: orch.fh2.send_cc(channel, midi_cc, value)
    )
    return f"Sent CC{midi_cc}={value} on ch{channel} (FH-2 → NT)"


@mcp.tool()
async def setup_fh2_nt_bridge(
    ctx: Context,
    mappings: list[dict],
) -> str:
    """Batch-configure multiple FH-2 CV → Disting NT parameter mappings.

    Each mapping specifies which FH-2 CV output controls which NT parameter
    via which MIDI CC number.

    Args:
        mappings: List of mapping dicts, each with keys:
            - nt_algo: NT algorithm slot index (0-based)
            - nt_param: Parameter number (0-based)
            - midi_cc: MIDI CC number (0-127)
            - fh2_cv: FH-2 CV output (1-8)
            - midi_channel: (optional) MIDI channel, default 0=omni
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()

    results = await loop.run_in_executor(
        None, lambda: orch.setup_fh2_nt_bridge(mappings)
    )

    lines = [f"=== FH-2 → NT Bridge ({len(results)} mappings) ==="]
    for r in results:
        if "error" in r:
            lines.append(f"  ERROR: {r['error']}")
        else:
            lines.append(
                f"  CV{r['fh2_cv']} → CC{r['midi_cc']} → "
                f"slot {r['nt_algo']} '{r['param_name']}' "
                f"(range {r['param_range']})"
            )
    return "\n".join(lines)


# ===================================================================
# 3. PRESET MANAGEMENT TOOLS (2)
# ===================================================================


@mcp.tool()
async def recall_system_preset(ctx: Context, preset_name: str) -> str:
    """Load a preset on the Disting NT and report system state.

    Args:
        preset_name: Name of the Disting NT preset to load.
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()

    await loop.run_in_executor(
        None, lambda: orch.nt.load_preset(preset_name)
    )

    # Give the NT a moment to load
    await asyncio.sleep(0.5)

    # Query status
    status = await loop.run_in_executor(None, orch.get_status)
    nt = status.get("nt", {})

    name = await loop.run_in_executor(None, orch.nt.get_preset_name)
    count = await loop.run_in_executor(None, orch.nt.get_loaded_algorithm_count)

    lines = [f"Loaded preset: {name}"]
    lines.append(f"  Algorithm slots: {count}")
    lines.append(f"  FH-2: {'connected' if status.get('fh2', {}).get('connected') else 'disconnected'}")
    lines.append(f"  ES-9: {'connected' if status.get('es9', {}).get('connected') else 'disconnected'}")
    return "\n".join(lines)


@mcp.tool()
async def save_system_state(ctx: Context) -> str:
    """Save the current Disting NT preset and report system state."""
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()

    await loop.run_in_executor(None, lambda: orch.nt.save_preset(0))

    name = await loop.run_in_executor(None, orch.nt.get_preset_name)
    return f"Saved preset: {name}"


# ===================================================================
# 4. PROXIED MODULE TOOLS (8)
# ===================================================================


@mcp.tool()
async def fh2_set_cv(
    ctx: Context, output: int, value: int, channel: int = 1
) -> str:
    """Set an FH-2 CV output value directly via CC.

    Args:
        output: CV output number (1-8).
        value: CC value 0-127 (maps to voltage based on FH-2 config).
        channel: MIDI channel (default 1).
    """
    orch = _require_fh2(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.fh2.set_cv_output(output, value, channel)
    )
    return f"FH-2 CV{output} = {value}"


@mcp.tool()
async def fh2_send_cc(
    ctx: Context, channel: int, cc: int, value: int
) -> str:
    """Send a MIDI CC message from the FH-2.

    Args:
        channel: MIDI channel 1-16.
        cc: CC number 0-127.
        value: CC value 0-127.
    """
    orch = _require_fh2(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.fh2.send_cc(channel, cc, value)
    )
    return f"FH-2: CC{cc}={value} on ch{channel}"


@mcp.tool()
async def fh2_read_display(ctx: Context) -> str:
    """Read the FH-2 4-line OLED display text."""
    orch = _require_fh2(ctx)
    loop = asyncio.get_event_loop()
    display = await loop.run_in_executor(None, orch.fh2.get_display)
    if isinstance(display, dict):
        return display.get("text", str(display))
    return str(display)


@mcp.tool()
async def nt_get_loaded_algorithms(ctx: Context) -> str:
    """List all algorithms loaded in the Disting NT preset."""
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()

    count = await loop.run_in_executor(None, orch.nt.get_loaded_algorithm_count)
    if count <= 0:
        return "No algorithms loaded (or no response)"

    lines = [f"=== Disting NT: {count} Algorithms Loaded ==="]
    for i in range(count):
        info = await loop.run_in_executor(
            None, lambda idx=i: orch.nt.get_loaded_algorithm(idx)
        )
        if "error" in info:
            lines.append(f"  [{i}] (error: {info['error']})")
        else:
            lines.append(f"  [{i}] {info.get('name', '?')} (GUID={info.get('guid', '?')})")

    return "\n".join(lines)


@mcp.tool()
async def nt_set_parameter(
    ctx: Context, algo_index: int, param_num: int, value: int
) -> str:
    """Set a Disting NT parameter value directly.

    Args:
        algo_index: Algorithm slot index (0-based).
        param_num: Parameter number (0-based).
        value: Parameter value (signed 16-bit).
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.nt.set_parameter_value(algo_index, param_num, value)
    )
    return f"NT: slot {algo_index} param {param_num} = {value}"


@mcp.tool()
async def nt_get_preset_name(ctx: Context) -> str:
    """Get the current Disting NT preset name."""
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    name = await loop.run_in_executor(None, orch.nt.get_preset_name)
    return f"NT preset: {name}"


@mcp.tool()
async def nt_take_screenshot(ctx: Context) -> str:
    """Capture the Disting NT 256x64 display as ASCII art."""
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, orch.nt.take_screenshot)


@mcp.tool()
async def es9_get_cpu_usage(ctx: Context) -> str:
    """Get ES-9 CPU usage."""
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, orch.es9.get_cpu_usage)
    if isinstance(result, dict) and "error" in result:
        return f"Error: {result['error']}"
    return f"ES-9 CPU: {result}"


# ===================================================================
# 5. SAFETY TOOLS (1)
# ===================================================================


@mcp.tool()
async def system_panic(ctx: Context) -> str:
    """Emergency silence — panic all connected modules.

    Sends All Notes Off + Reset Controllers on all channels to FH-2 and NT,
    zeros all FH-2 CV outputs, and silences ES-9.
    """
    orch = _orch(ctx)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, orch.panic)

    lines = ["=== SYSTEM PANIC ==="]
    for module, result in results.items():
        label = {"fh2": "FH-2", "es9": "ES-9", "nt": "Disting NT"}[module]
        lines.append(f"  {label}: {result}")
    return "\n".join(lines)


# ===================================================================
# 6. ES-9 MIXER & ROUTING TOOLS (6)
# ===================================================================


@mcp.tool()
async def es9_set_mix_level(
    ctx: Context, mix_bus: int, channel: int, db: float
) -> str:
    """Set a channel's level on an ES-9 virtual mix bus.

    Args:
        mix_bus: Mix bus number (1 or 2).
        channel: Channel number within the mix bus (0-based).
        db: Level in dB (e.g. 0.0 = unity, -inf = off).
    """
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.set_virtual_mix(mix_bus, channel, db)
    )
    return f"ES-9 mix{mix_bus} ch{channel} = {db} dB"


@mcp.tool()
async def es9_set_mix_pan(
    ctx: Context, mix_bus: int, channel: int, pan: int
) -> str:
    """Set a channel's pan position on an ES-9 virtual mix bus.

    Args:
        mix_bus: Mix bus number (1 or 2).
        channel: Channel number within the mix bus (0-based).
        pan: Pan position (0=hard left, 64=centre, 127=hard right).
    """
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.set_virtual_pan(mix_bus, channel, pan)
    )
    return f"ES-9 mix{mix_bus} ch{channel} pan = {pan}"


@mcp.tool()
async def es9_set_input_routing(
    ctx: Context, dsp: int, channels: list[int]
) -> str:
    """Set ES-9 capture (input) routing for a DSP block.

    Args:
        dsp: DSP block index (0-based).
        channels: List of raw integer channel codes for the routing.
    """
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.set_capture_routing(dsp, channels)
    )
    return f"ES-9 DSP{dsp} input routing = {channels}"


@mcp.tool()
async def es9_set_output_routing(
    ctx: Context, dsp: int, channels: list[int]
) -> str:
    """Set ES-9 output routing for a DSP block.

    Args:
        dsp: DSP block index (0-based).
        channels: List of raw integer channel codes for the routing.
    """
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.set_output_routing(dsp, channels)
    )
    return f"ES-9 DSP{dsp} output routing = {channels}"


@mcp.tool()
async def es9_reset_mixer(ctx: Context) -> str:
    """Reset the ES-9 mixer to default state (all levels unity, pans centre)."""
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, orch.es9.reset_mixer)
    return "ES-9 mixer reset to defaults"


@mcp.tool()
async def es9_set_options(
    ctx: Context, mixer2_spdif: bool = False, midi_thru: bool = False
) -> str:
    """Set ES-9 global options.

    Args:
        mixer2_spdif: Route mixer 2 output to S/PDIF.
        midi_thru: Enable MIDI thru.
    """
    orch = _require_es9(ctx)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.set_options(mixer2_spdif, midi_thru)
    )
    opts = []
    if mixer2_spdif:
        opts.append("mixer2→S/PDIF")
    if midi_thru:
        opts.append("MIDI thru")
    return f"ES-9 options: {', '.join(opts) if opts else 'all off'}"


# ===================================================================
# 7. FH-2 LFO CONTROL TOOLS (3)
# ===================================================================


@mcp.tool()
async def fh2_configure_lfo(
    ctx: Context, lfo: int, params: dict, channel: int = 0
) -> str:
    """Configure multiple FH-2 LFO parameters at once.

    Args:
        lfo: LFO number (1-8).
        params: Dict of param_name → value. Valid keys include:
            "speed", "depth", "offset", "waveform", "oneshot", etc.
        channel: MIDI channel (0 = use config default, 1-16 for specific).
    """
    orch = _require_fh2(ctx)
    config = _config(ctx)
    ch = channel if channel > 0 else config.fh2_midi_channel
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.fh2.configure_lfo(lfo, params, ch)
    )
    return f"FH-2 LFO{lfo}: configured {list(params.keys())} on ch{ch}"


@mcp.tool()
async def fh2_set_lfo_param(
    ctx: Context, lfo: int, param: str, value: int, channel: int = 0
) -> str:
    """Set a single FH-2 LFO parameter.

    Args:
        lfo: LFO number (1-8).
        param: Parameter name (e.g. "speed", "depth", "offset", "waveform").
        value: Parameter value (0-127).
        channel: MIDI channel (0 = use config default, 1-16 for specific).
    """
    orch = _require_fh2(ctx)
    config = _config(ctx)
    ch = channel if channel > 0 else config.fh2_midi_channel
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.fh2.set_lfo_param(lfo, param, value, ch)
    )
    return f"FH-2 LFO{lfo} {param} = {value} on ch{ch}"


@mcp.tool()
async def fh2_reset_lfo(ctx: Context, lfo: int, channel: int = 0) -> str:
    """Reset an FH-2 LFO to its default state.

    Args:
        lfo: LFO number (1-8).
        channel: MIDI channel (0 = use config default, 1-16 for specific).
    """
    orch = _require_fh2(ctx)
    config = _config(ctx)
    ch = channel if channel > 0 else config.fh2_midi_channel
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.fh2.reset_lfo(lfo, ch)
    )
    return f"FH-2 LFO{lfo} reset on ch{ch}"


# ===================================================================
# 8. ES-9 CV GENERATION TOOLS (4)
# ===================================================================


@mcp.tool()
async def es9_set_cv_voltage(
    ctx: Context, channel: int, voltage: float
) -> str:
    """Set a static CV voltage on an ES-9 audio output channel.

    Auto-starts the ES-9 audio stream if not already running.

    Args:
        channel: Audio output channel (0-based).
        voltage: Target voltage (e.g. -5.0 to +5.0).
    """
    from orchestrator import StaticCV

    orch = await _ensure_es9_audio(ctx)
    source = StaticCV(voltage)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.cv_engine.set_source(channel, source)
    )
    return f"ES-9 CV ch{channel} = {voltage}V (static)"


@mcp.tool()
async def es9_set_cv_gate(
    ctx: Context, channel: int, high: bool = False, voltage: float = 5.0
) -> str:
    """Set a gate CV on an ES-9 audio output channel.

    Auto-starts the ES-9 audio stream if not already running.

    Args:
        channel: Audio output channel (0-based).
        high: Gate state (True = high/on, False = low/off).
        voltage: Gate high voltage (default 5V).
    """
    from orchestrator import GateCV

    orch = await _ensure_es9_audio(ctx)
    source = GateCV(high=high, voltage=voltage)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.cv_engine.set_source(channel, source)
    )
    state = "HIGH" if high else "LOW"
    return f"ES-9 CV ch{channel} = gate {state} ({voltage}V)"


@mcp.tool()
async def es9_generate_lfo(
    ctx: Context,
    channel: int,
    shape: str = "sine",
    rate_hz: float = 1.0,
    depth_v: float = 5.0,
    offset_v: float = 0.0,
) -> str:
    """Generate an LFO CV waveform on an ES-9 audio output channel.

    Auto-starts the ES-9 audio stream if not already running.

    Args:
        channel: Audio output channel (0-based).
        shape: Waveform shape: "sine", "triangle", "saw", "square", "random".
        rate_hz: Frequency in Hz.
        depth_v: Peak-to-peak amplitude in volts.
        offset_v: DC offset in volts.
    """
    from orchestrator import LfoCv

    orch = await _ensure_es9_audio(ctx)
    source = LfoCv(shape=shape, rate_hz=rate_hz, depth_v=depth_v, offset_v=offset_v)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.cv_engine.set_source(channel, source)
    )
    return f"ES-9 CV ch{channel} = LFO {shape} {rate_hz}Hz ±{depth_v/2}V offset {offset_v}V"


@mcp.tool()
async def es9_trigger_envelope(
    ctx: Context,
    channel: int,
    attack_ms: float = 10.0,
    release_ms: float = 100.0,
    peak_v: float = 5.0,
) -> str:
    """Trigger an attack-release envelope on an ES-9 audio output channel.

    Auto-starts the ES-9 audio stream if not already running.

    Args:
        channel: Audio output channel (0-based).
        attack_ms: Attack time in milliseconds.
        release_ms: Release time in milliseconds.
        peak_v: Peak voltage.
    """
    from orchestrator import EnvelopeCV

    orch = await _ensure_es9_audio(ctx)
    source = EnvelopeCV(attack_ms=attack_ms, release_ms=release_ms, peak_v=peak_v)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: orch.es9.cv_engine.set_source(channel, source)
    )
    return f"ES-9 CV ch{channel} = envelope A={attack_ms}ms R={release_ms}ms peak={peak_v}V"


# ===================================================================
# 9. MULTI-PARAM MACRO TOOLS (3)
# ===================================================================


@mcp.tool()
async def map_macro_to_nt_params(
    ctx: Context,
    midi_cc: int,
    targets: list[dict],
    midi_channel: int = 0,
) -> str:
    """Map a single MIDI CC to multiple Disting NT parameters (macro control).

    Each target can have independent min/max scaling so one CC controls
    several parameters simultaneously with different ranges.

    Args:
        midi_cc: MIDI CC number (0-127) to use as the macro source.
        targets: List of target dicts, each with keys:
            - algo: NT algorithm slot index (0-based)
            - param: Parameter number (0-based)
            - min: (optional) Minimum mapped value (default 0)
            - max: (optional) Maximum mapped value (default 127)
        midi_channel: MIDI channel (0=omni, 1-15 for specific).
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: orch.map_macro_to_nt_params(midi_cc, targets, midi_channel)
    )
    lines = [f"Macro CC{midi_cc} → {len(result['targets'])} targets:"]
    for t in result["targets"]:
        lines.append(f"  slot {t['algo']} param {t['param']} (range {t['min']}–{t['max']})")
    return "\n".join(lines)


@mcp.tool()
async def nt_batch_set_parameters(
    ctx: Context, params: list[dict]
) -> str:
    """Set multiple Disting NT parameters in a single call.

    Args:
        params: List of parameter dicts, each with keys:
            - algo: NT algorithm slot index (0-based)
            - param: Parameter number (0-based)
            - value: Parameter value (signed 16-bit)
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: orch.batch_set_nt_parameters(params)
    )
    ok = sum(1 for r in results if "status" in r and r["status"] == "ok")
    err = len(results) - ok
    lines = [f"Batch set: {ok} ok, {err} errors"]
    for r in results:
        if "error" in r:
            lines.append(f"  ERROR slot {r['algo']} param {r['param']}: {r['error']}")
    return "\n".join(lines)


@mcp.tool()
async def sweep_nt_param(
    ctx: Context,
    algo: int,
    param: int,
    start: int,
    end: int,
    steps: int = 64,
    delay_ms: float = 20.0,
) -> str:
    """Sweep a Disting NT parameter from start to end over time.

    Runs a blocking ramp in the executor thread. Total duration ≈ steps × delay_ms.

    Args:
        algo: NT algorithm slot index (0-based).
        param: Parameter number (0-based).
        start: Starting parameter value.
        end: Ending parameter value.
        steps: Number of intermediate steps (default 64).
        delay_ms: Delay between steps in milliseconds (default 20).
    """
    orch = _require_nt(ctx)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: orch.sweep_nt_param(algo, param, start, end, steps, delay_ms)
    )
    total_ms = steps * delay_ms
    return (
        f"Swept NT slot {algo} param {param}: {start} → {end} "
        f"({steps} steps, {total_ms:.0f}ms)"
    )


# ===================================================================
# 10. NT ALGORITHM METADATA TOOLS (2) — always available, no device needed
# ===================================================================


@mcp.tool()
async def nt_search_algorithms(
    ctx: Context, query: str, max_results: int = 10
) -> str:
    """Fuzzy search over the bundled Disting NT algorithm library.

    Works offline — no device connection needed. Returns ranked results
    with GUID, name, categories, and specs.

    Args:
        query: Search term (algorithm name, category, feature, etc.).
        max_results: Maximum number of results to return (default 10).
    """
    meta = _metadata(ctx)
    results = meta.search(query, max_results=max_results)

    if not results:
        return f"No algorithms found matching '{query}'."

    lines = [f"=== Algorithm Search: '{query}' ({len(results)} results) ==="]
    for r in results:
        cats = ", ".join(r["categories"][:3]) if r["categories"] else "—"
        lines.append(
            f"\n  [{r['guid']}] {r['name']} (score: {r['score']})"
            f"\n    Categories: {cats}"
            f"\n    {r['short_description']}"
            f"\n    Params: {r['num_parameters']}  In: {r['num_inputs']}  Out: {r['num_outputs']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def nt_algorithm_info(ctx: Context, identifier: str) -> str:
    """Get full details for a Disting NT algorithm by GUID or exact name.

    Works offline — no device connection needed. Shows description,
    all parameters with types/ranges, and input/output ports.
    Falls back to fuzzy suggestions if the identifier is not an exact match.

    Args:
        identifier: Algorithm GUID (e.g. "clck") or exact name (e.g. "Clock").
    """
    meta = _metadata(ctx)
    algo = meta.get(identifier)

    if algo is None:
        # Offer fuzzy suggestions
        suggestions = meta.search(identifier, max_results=5)
        if suggestions:
            names = ", ".join(f"{s['name']} ({s['guid']})" for s in suggestions)
            return f"Algorithm '{identifier}' not found. Did you mean: {names}?"
        return f"Algorithm '{identifier}' not found."

    lines = [f"=== {algo['name']} [{algo['guid']}] ==="]
    lines.append(f"  {algo.get('description', 'No description.')}")

    cats = algo.get("categories", [])
    if cats:
        lines.append(f"\n  Categories: {', '.join(cats)}")

    use_cases = algo.get("use_cases", [])
    if use_cases:
        lines.append(f"  Use cases: {', '.join(use_cases)}")

    # Parameters
    params = algo.get("parameters", [])
    if params:
        lines.append(f"\n  === Parameters ({len(params)}) ===")
        for i, p in enumerate(params):
            ptype = p.get("type", "")
            pmin = p.get("min", "")
            pmax = p.get("max", "")
            pdefault = p.get("default", "")
            desc = p.get("description", "")
            line = f"    [{i}] {p['name']}"
            if ptype:
                line += f" ({ptype})"
            if pmin != "" or pmax != "":
                line += f" [{pmin}..{pmax}]"
            if pdefault != "":
                line += f" default={pdefault}"
            lines.append(line)
            if desc:
                lines.append(f"        {desc}")

    # Input ports
    inputs = algo.get("input_ports", [])
    if inputs:
        lines.append(f"\n  === Inputs ({len(inputs)}) ===")
        for port in inputs:
            desc = f" — {port['description']}" if port.get("description") else ""
            lines.append(f"    {port['name']}{desc}")

    # Output ports
    outputs = algo.get("output_ports", [])
    if outputs:
        lines.append(f"\n  === Outputs ({len(outputs)}) ===")
        for port in outputs:
            desc = f" — {port['description']}" if port.get("description") else ""
            lines.append(f"    {port['name']}{desc}")

    return "\n".join(lines)


# ===================================================================
# 11. NT_HELPER PROXY TOOLS (5) — optional, requires nt_helper app
# ===================================================================


@mcp.tool()
async def nt_helper_show_routing(ctx: Context) -> str:
    """Show the current Disting NT routing as a visual diagram.

    Requires the nt_helper Flutter app running with its MCP server enabled.
    """
    proxy = _require_nt_proxy(ctx)
    result = await proxy.show_routing()
    if result is None:
        return "Error: nt_helper did not return routing data."
    return result if isinstance(result, str) else json.dumps(result, indent=2)


@mcp.tool()
async def nt_helper_show_screen(ctx: Context, display_mode: str = "") -> str:
    """Show the current Disting NT screen content via nt_helper.

    Requires the nt_helper Flutter app running with its MCP server enabled.

    Args:
        display_mode: Optional display mode hint (empty for default).
    """
    proxy = _require_nt_proxy(ctx)
    result = await proxy.show_screen(display_mode)
    if result is None:
        return "Error: nt_helper did not return screen data."
    return result if isinstance(result, str) else json.dumps(result, indent=2)


@mcp.tool()
async def nt_helper_edit_slot(ctx: Context, slot_index: int, data: dict) -> str:
    """Edit parameters on a specific Disting NT algorithm slot via nt_helper.

    Requires the nt_helper Flutter app running with its MCP server enabled.

    Args:
        slot_index: Algorithm slot index (0-based).
        data: Dict of parameter edits to apply (key-value pairs).
    """
    proxy = _require_nt_proxy(ctx)
    result = await proxy.edit_slot(slot_index, data)
    if result is None:
        return "Error: nt_helper did not return edit result."
    return result if isinstance(result, str) else json.dumps(result, indent=2)


@mcp.tool()
async def nt_helper_add_algorithm(
    ctx: Context,
    name: str = "",
    guid: str = "",
    slot_index: int = -1,
) -> str:
    """Add an algorithm to the Disting NT preset by name or GUID via nt_helper.

    At least one of name or guid must be provided. Provide slot_index to insert
    at a specific position (default: append).

    Requires the nt_helper Flutter app running with its MCP server enabled.

    Args:
        name: Algorithm name (fuzzy matched by nt_helper).
        guid: Algorithm GUID (exact match, e.g. "clck").
        slot_index: Target slot index (-1 = append).
    """
    if not name and not guid:
        return "Error: provide at least one of 'name' or 'guid'."
    proxy = _require_nt_proxy(ctx)
    result = await proxy.add_algorithm(name=name, guid=guid, slot_index=slot_index)
    if result is None:
        return "Error: nt_helper did not return add result."
    return result if isinstance(result, str) else json.dumps(result, indent=2)


@mcp.tool()
async def nt_helper_search_parameters(
    ctx: Context,
    query: str,
    scope: str = "preset",
    slot_index: int = -1,
    partial_match: bool = False,
) -> str:
    """Search parameters across the current Disting NT preset via nt_helper.

    Requires the nt_helper Flutter app running with its MCP server enabled.

    Args:
        query: Parameter name or value to search for.
        scope: Search scope: "preset" (all slots) or "slot" (single slot).
        slot_index: Slot index when scope="slot" (-1 = ignored).
        partial_match: Allow partial name matches.
    """
    proxy = _require_nt_proxy(ctx)
    result = await proxy.search_parameters(
        query=query, scope=scope, slot_index=slot_index, partial_match=partial_match
    )
    if result is None:
        return "Error: nt_helper did not return search results."
    return result if isinstance(result, str) else json.dumps(result, indent=2)


# ===================================================================
# Entry point
# ===================================================================


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
