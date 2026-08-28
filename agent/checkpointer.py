# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langgraph.checkpoint.sqlite import SqliteSaver
from shared.config import get_config


_checkpointer = None
_saver_context = None


def get_sqlite_checkpointer():
    global _checkpointer, _saver_context
    if _checkpointer is None:
        config = get_config()
        base_dir = config.output_base_dir
        db_path = base_dir / "checkpoints.db"
        _saver_context = SqliteSaver.from_conn_string(str(db_path))
        _checkpointer = _saver_context.__enter__()
    return _checkpointer
