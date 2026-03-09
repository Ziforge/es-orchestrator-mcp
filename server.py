"""Expert Sleepers Orchestrator MCP Server — unified control of FH-2, ES-9, and Disting NT."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import Context, FastMCP

from config import OrchestratorConfig
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

    yield {"orchestrator": orch, "config": config}

    # Cleanup
    orch.disconnect_all()


mcp = FastMCP(
    "es-orchestrator",
    instructions=(
        "Orchestrate Expert Sleepers Eurorack modules: FH-2 (MIDI-to-CV), "
        "ES-9 (USB audio interface), and Disting NT (multi-algorithm DSP). "
        "Provides cross-module MIDI CC mapping, proxied single-module operations, "
        "and system-wide control. When the orchestrator is running, individual "
        "per-module MCP servers should be stopped (macOS can't share MIDI output "
        "ports between processes)."
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
# Entry point
# ===================================================================


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
