"""Stable facade for durable boundary generation storage.

``os`` remains available here because existing failure-injection tests patch
``boundaries.storage.os.replace``. All child modules share that same stdlib
module object, so the seam continues to exercise publication atomics.
"""

import os as os

from .activation import activate_generation
from .cleanup import remove_tree
from .compatibility import ensure_fresh_compatibility_links, is_compatibility_link
from .durability import fsync_directory as _fsync_directory
from .locking import boundary_package_lock
from .publication import publish_generation
from .root import prepare_boundary_root
from .trees import prepare_managed_directory as _prepare_managed_directory


__all__ = (
    "activate_generation",
    "boundary_package_lock",
    "ensure_fresh_compatibility_links",
    "is_compatibility_link",
    "prepare_boundary_root",
    "publish_generation",
    "remove_tree",
)
