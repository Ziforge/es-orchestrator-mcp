"""Expert Sleepers Orchestrator: cross-module control of FH-2, ES-9, and Disting NT."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

from config import OrchestratorConfig

# ---------------------------------------------------------------------------
# Import engines from sibling MCP server projects.
#
# Each project has its own protocol.py, config.py, etc. We must isolate
# imports so each engine loads its own modules, not a sibling's.
# ---------------------------------------------------------------------------

_BASE = Path(__file__).resolve().parent.parent

# Module names that collide across projects
_SHARED_NAMES = ("protocol", "config", "cv_engine")


def _import_engine(project_dir: str, engine_module: str, engine_class: str):
    """Import an engine class from a sibling MCP project, isolating shared module names."""
    project_path = str(_BASE / project_dir)

    # Save and temporarily remove any cached colliding modules
    saved: dict[str, object] = {}
    for name in _SHARED_NAMES:
        if name in sys.modules:
            saved[name] = sys.modules.pop(name)

    # Add project to front of path
    sys.path.insert(0, project_path)

    try:
        mod = importlib.import_module(engine_module)
        cls = getattr(mod, engine_class)
    finally:
        # Remove from path
        if project_path in sys.path:
            sys.path.remove(project_path)
        # Remove the project's cached modules that would collide
        for name in _SHARED_NAMES:
            sys.modules.pop(name, None)
        # Restore previously saved modules
        for name, mod_obj in saved.items():
            sys.modules[name] = mod_obj

    return cls


FH2Engine = _import_engine("fh2-mcp", "fh2_engine", "FH2Engine")
ES9Engine = _import_engine("es9-mcp", "es9_engine", "ES9Engine")
DistingNTEngine = _import_engine("disting-nt-mcp", "disting_nt_engine", "DistingNTEngine")


def _import_cv_sources() -> dict[str, type]:
    """Import CV source classes from es9-mcp/cv_engine.py using the same isolation pattern."""
    project_path = str(_BASE / "es9-mcp")
    saved: dict[str, object] = {}
    for name in _SHARED_NAMES:
        if name in sys.modules:
            saved[name] = sys.modules.pop(name)
    sys.path.insert(0, project_path)
    try:
        mod = importlib.import_module("cv_engine")
        classes = {
            n: getattr(mod, n)
            for n in ("StaticCV", "GateCV", "LfoCv", "EnvelopeCV")
        }
    finally:
        if project_path in sys.path:
            sys.path.remove(project_path)
        for name in _SHARED_NAMES:
            sys.modules.pop(name, None)
        for name, mod_obj in saved.items():
            sys.modules[name] = mod_obj
    return classes


_CV_SOURCES = _import_cv_sources()
StaticCV = _CV_SOURCES["StaticCV"]
GateCV = _CV_SOURCES["GateCV"]
LfoCv = _CV_SOURCES["LfoCv"]
EnvelopeCV = _CV_SOURCES["EnvelopeCV"]


class Orchestrator:
    """Cross-module orchestrator for Expert Sleepers Eurorack system."""

    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self.fh2 = FH2Engine()
        self.es9 = ES9Engine()
        self.nt = DistingNTEngine(sysex_id=config.nt_sysex_id)
        self._macro_mappings: dict[int, list[dict]] = {}

    # -- Connection Management --

    def connect_fh2(self) -> str:
        """Connect to FH-2."""
        return self.fh2.connect(
            output_port=self.config.fh2_output_port or "FH-2",
            input_port=self.config.fh2_input_port or self.config.fh2_output_port or "FH-2",
        )

    def connect_es9(self) -> str:
        """Connect to ES-9 (MIDI + optional audio for CV generation)."""
        result = self.es9.connect_midi(
            output_port=self.config.es9_output_port or "ES-9",
            input_port=self.config.es9_input_port or self.config.es9_output_port or "ES-9",
        )
        if self.config.es9_audio_device:
            audio_result = self.es9.connect_audio(
                device=self.config.es9_audio_device,
                sample_rate=self.config.es9_sample_rate,
            )
            result += f" | audio: {audio_result}"
        return result

    def connect_nt(self) -> str:
        """Connect to Disting NT."""
        return self.nt.connect(
            output_port=self.config.nt_output_port or "Disting NT",
            input_port=self.config.nt_input_port or self.config.nt_output_port or "Disting NT",
        )

    def connect_all(self) -> dict[str, str]:
        """Connect to all modules, reporting per-module results."""
        results: dict[str, str] = {}
        for name, connect_fn in [
            ("fh2", self.connect_fh2),
            ("es9", self.connect_es9),
            ("nt", self.connect_nt),
        ]:
            try:
                results[name] = connect_fn()
            except Exception as e:
                results[name] = f"FAILED: {e}"
        return results

    def disconnect_all(self) -> dict[str, str]:
        """Disconnect all modules gracefully."""
        results: dict[str, str] = {}
        for name, engine in [("fh2", self.fh2), ("es9", self.es9), ("nt", self.nt)]:
            try:
                engine.disconnect()
                results[name] = "disconnected"
            except Exception as e:
                results[name] = f"FAILED: {e}"
        return results

    def connect_module(self, module: str) -> str:
        """Connect a single module by name."""
        module = module.lower().strip()
        if module == "fh2":
            return self.connect_fh2()
        elif module == "es9":
            return self.connect_es9()
        elif module in ("nt", "disting", "disting_nt"):
            return self.connect_nt()
        else:
            raise ValueError(f"Unknown module '{module}'. Use: fh2, es9, nt")

    def disconnect_module(self, module: str) -> str:
        """Disconnect a single module by name."""
        module = module.lower().strip()
        if module == "fh2":
            return self.fh2.disconnect()
        elif module == "es9":
            return self.es9.disconnect()
        elif module in ("nt", "disting", "disting_nt"):
            return self.nt.disconnect()
        else:
            raise ValueError(f"Unknown module '{module}'. Use: fh2, es9, nt")

    # -- Status --

    def get_status(self) -> dict[str, Any]:
        """Get connection and state info for all modules."""
        status: dict[str, Any] = {}

        # FH-2
        fh2_info: dict[str, Any] = {"connected": self.fh2.connected}
        if self.fh2.connected:
            fh2_info["ports"] = self.fh2.port_info
            fh2_info["firmware"] = self.fh2._firmware_version or "(not queried)"
        status["fh2"] = fh2_info

        # ES-9
        es9_info: dict[str, Any] = {"connected": self.es9.midi_connected}
        if self.es9.midi_connected:
            es9_info["ports"] = self.es9.port_info
        es9_info["audio_running"] = self.es9.audio_running
        if self.es9.audio_running and self.es9.cv_engine is not None:
            es9_info["cv_sources"] = self.es9.cv_engine.get_source_info()
        status["es9"] = es9_info

        # Disting NT
        nt_info: dict[str, Any] = {"connected": self.nt.connected}
        if self.nt.connected:
            nt_info["ports"] = self.nt.port_info
            nt_info["firmware"] = self.nt._firmware_version or "(not queried)"
            nt_info["preset"] = self.nt._preset_name or "(not queried)"
        status["nt"] = nt_info

        return status

    # -- Cross-Module Mapping --

    def map_fh2_cv_to_nt_param(
        self,
        nt_algo: int,
        nt_param: int,
        midi_cc: int,
        fh2_cv: int,
        midi_channel: int = 0,
    ) -> dict[str, Any]:
        """Set up FH-2 CV → MIDI CC → Disting NT parameter mapping.

        1. Queries NT parameter info for name and range
        2. Sets MIDI CC mapping on the NT side
        3. Returns info needed to control from FH-2 side

        The FH-2 CV output should be configured to send the specified MIDI CC.
        """
        param_info = self.nt.get_parameter_info(nt_algo, nt_param)
        if "error" in param_info:
            return {"error": f"Could not get NT param info: {param_info['error']}"}

        param_name = param_info.get("name", "?")
        param_min = param_info.get("min", 0)
        param_max = param_info.get("max", 127)

        self.nt.set_midi_mapping(
            nt_algo, nt_param, 5, midi_cc, midi_channel,
            enabled=True, midi_min=param_min, midi_max=param_max,
        )

        return {
            "nt_algo": nt_algo,
            "nt_param": nt_param,
            "param_name": param_name,
            "param_range": [param_min, param_max],
            "midi_cc": midi_cc,
            "midi_channel": midi_channel,
            "fh2_cv": fh2_cv,
            "status": "mapped",
        }

    def setup_fh2_nt_bridge(
        self, mappings: list[dict[str, int]]
    ) -> list[dict[str, Any]]:
        """Batch-configure FH-2 → Disting NT mappings.

        Each mapping dict: {"nt_algo": int, "nt_param": int, "midi_cc": int, "fh2_cv": int}
        Optional keys: "midi_channel" (default 0=omni)
        """
        results = []
        for m in mappings:
            result = self.map_fh2_cv_to_nt_param(
                nt_algo=m["nt_algo"],
                nt_param=m["nt_param"],
                midi_cc=m["midi_cc"],
                fh2_cv=m["fh2_cv"],
                midi_channel=m.get("midi_channel", 0),
            )
            results.append(result)
        return results

    # -- Multi-param Macros --

    def map_macro_to_nt_params(
        self,
        midi_cc: int,
        targets: list[dict],
        midi_channel: int = 0,
    ) -> dict[str, Any]:
        """Map a single MIDI CC to multiple Disting NT parameters with per-target scaling.

        Each target dict: {"algo": int, "param": int, "min": int, "max": int}
        """
        mapped = []
        for t in targets:
            self.nt.set_midi_mapping(
                t["algo"], t["param"], 5, midi_cc, midi_channel,
                enabled=True, midi_min=t.get("min", 0), midi_max=t.get("max", 127),
            )
            mapped.append({"algo": t["algo"], "param": t["param"],
                           "min": t.get("min", 0), "max": t.get("max", 127)})
        self._macro_mappings[midi_cc] = mapped
        return {"midi_cc": midi_cc, "targets": mapped, "midi_channel": midi_channel}

    def batch_set_nt_parameters(self, params: list[dict]) -> list[dict[str, Any]]:
        """Set multiple Disting NT parameters in one call.

        Each dict: {"algo": int, "param": int, "value": int}
        """
        results = []
        for p in params:
            try:
                self.nt.set_parameter_value(p["algo"], p["param"], p["value"])
                results.append({"algo": p["algo"], "param": p["param"],
                                "value": p["value"], "status": "ok"})
            except Exception as e:
                results.append({"algo": p["algo"], "param": p["param"],
                                "error": str(e)})
        return results

    def sweep_nt_param(
        self,
        algo: int,
        param: int,
        start: int,
        end: int,
        steps: int = 64,
        delay_ms: float = 20.0,
    ) -> dict[str, Any]:
        """Ramp a Disting NT parameter from start to end over time (blocking)."""
        step_size = (end - start) / max(steps, 1)
        delay_s = delay_ms / 1000.0
        for i in range(steps + 1):
            value = int(start + step_size * i)
            self.nt.set_parameter_value(algo, param, value)
            if i < steps:
                time.sleep(delay_s)
        return {"algo": algo, "param": param, "start": start, "end": end,
                "steps": steps, "delay_ms": delay_ms}

    # -- Safety --

    def panic(self) -> dict[str, str]:
        """Emergency silence on all modules."""
        results: dict[str, str] = {}

        if self.fh2.connected:
            try:
                self.fh2.panic()
                self.fh2.zero_all_cv()
                results["fh2"] = "panic + CV zeroed"
            except Exception as e:
                results["fh2"] = f"FAILED: {e}"
        else:
            results["fh2"] = "not connected"

        if self.es9.midi_connected:
            try:
                for ch in range(16):
                    self.es9._send([0xB0 | ch, 123, 0])
                    self.es9._send([0xB0 | ch, 121, 0])
                msg = "all notes off + reset controllers"
                if self.es9.audio_running and self.es9.cv_engine is not None:
                    for ch_num in list(self.es9.cv_engine._sources):
                        self.es9.cv_engine.clear_source(ch_num)
                    msg += " + CV sources cleared"
                results["es9"] = msg
            except Exception as e:
                results["es9"] = f"FAILED: {e}"
        else:
            results["es9"] = "not connected"

        if self.nt.connected:
            try:
                self.nt.panic()
                results["nt"] = "panic sent"
            except Exception as e:
                results["nt"] = f"FAILED: {e}"
        else:
            results["nt"] = "not connected"

        return results
