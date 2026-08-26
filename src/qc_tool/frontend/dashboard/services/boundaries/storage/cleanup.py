"""Best-effort cleanup limited to service-owned staging trees."""

import logging
from pathlib import Path
import shutil


logger = logging.getLogger(__name__)


def remove_tree(path: Path) -> None:
    """Best-effort cleanup for a service-created, explicitly scoped path."""

    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError:
        logger.exception("Could not remove private boundary-package staging data")
