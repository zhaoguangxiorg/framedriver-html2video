# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import json
from pathlib import Path
from typing import Dict, Any, Optional


_project_root: Optional[Path] = None


def _get_project_root() -> Path:
    global _project_root
    if _project_root is None:
        _project_root = Path(__file__).parent.parent
    return _project_root


def _get_personas_path() -> Path:
    return _get_project_root() / "config" / "voice_personas.json"


def load_voice_personas() -> Dict[str, Dict[str, Any]]:
    personas_path = _get_personas_path()
    with open(personas_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_voice_settings(persona_id: str) -> Optional[Dict[str, str]]:
    if not persona_id:
        return None
    personas = load_voice_personas()
    persona = personas.get(persona_id)
    if persona is None:
        persona = personas.get("default")
    return {
        "voice": persona["voice"],
        "voice_rate": persona["voice_rate"],
        "voice_volume": persona["voice_volume"],
        "voice_pitch": persona["voice_pitch"],
    }


def list_voice_personas() -> Dict[str, Dict[str, Any]]:
    return load_voice_personas()
