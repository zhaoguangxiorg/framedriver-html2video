# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from pathlib import Path
from typing import Union


def ensure_dir(dir_path: Union[str, Path]) -> Path:
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path
