# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Config:
    def __init__(self):
        load_dotenv()
        output_dir = os.getenv("OUTPUT_BASE_DIR", "./output")
        output_path = Path(output_dir)
        if output_path.is_absolute():
            self.output_base_dir: Path = output_path.resolve()
        else:
            self.output_base_dir: Path = (_PROJECT_ROOT / output_dir).resolve()

_config_instance: Optional[Config] = None


def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
