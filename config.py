"""Configuration for Expert Sleepers Orchestrator MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class OrchestratorConfig:
    """Configuration for all three Expert Sleepers modules."""

    # FH-2
    fh2_output_port: str = ""
    fh2_input_port: str = ""
    fh2_midi_channel: int = 1

    # ES-9
    es9_output_port: str = ""
    es9_input_port: str = ""
    es9_audio_device: str = ""
    es9_sample_rate: int = 48000

    # Disting NT
    nt_output_port: str = ""
    nt_input_port: str = ""
    nt_sysex_id: int = 0
    nt_midi_channel: int = 1

    # nt_helper proxy (optional — thorinside/nt_helper Flutter app)
    nt_helper_url: str = ""

    # Global
    auto_connect: bool = False

    @classmethod
    def from_env(cls, env_path: str | None = None) -> OrchestratorConfig:
        load_dotenv(env_path)
        return cls(
            fh2_output_port=os.getenv("FH2_OUTPUT_PORT", ""),
            fh2_input_port=os.getenv("FH2_INPUT_PORT", ""),
            fh2_midi_channel=int(os.getenv("FH2_MIDI_CHANNEL", "1")),
            es9_output_port=os.getenv("ES9_OUTPUT_PORT", ""),
            es9_input_port=os.getenv("ES9_INPUT_PORT", ""),
            es9_audio_device=os.getenv("ES9_AUDIO_DEVICE", ""),
            es9_sample_rate=int(os.getenv("ES9_SAMPLE_RATE", "48000")),
            nt_output_port=os.getenv("DISTING_NT_OUTPUT_PORT", ""),
            nt_input_port=os.getenv("DISTING_NT_INPUT_PORT", ""),
            nt_sysex_id=int(os.getenv("DISTING_NT_SYSEX_ID", "0")),
            nt_midi_channel=int(os.getenv("DISTING_NT_MIDI_CHANNEL", "1")),
            nt_helper_url=os.getenv("NT_HELPER_URL", ""),
            auto_connect=os.getenv("AUTO_CONNECT", "false").lower()
            in ("true", "1", "yes"),
        )
