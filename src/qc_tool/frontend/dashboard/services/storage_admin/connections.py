"""Read-only, operator-configured desktop connection information."""

import re
import ipaddress
import shlex
from urllib.parse import quote

from django.conf import settings


def connection_info():
    host = getattr(settings, "QC_TOOL_STORAGE_SFTP_HOST", "")
    username = getattr(settings, "QC_TOOL_STORAGE_SFTP_USERNAME", "qcstorage")
    port = getattr(settings, "QC_TOOL_STORAGE_SFTP_PORT", 2222)
    root = getattr(settings, "QC_TOOL_STORAGE_SFTP_ROOT", "/files")
    if not host:
        return {"configured": False}
    try:
        if ":" in host:
            if ipaddress.ip_address(host).version != 6:
                raise ValueError
        elif all(c.isdigit() or c == "." for c in host):
            ipaddress.IPv4Address(host)
        elif not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                     for label in host.rstrip(".").split(".")):
            raise ValueError
    except (ValueError, TypeError):
        return {"configured": False, "configuration_error": True}
    if (not isinstance(host, str) or len(host) > 253 or not re.fullmatch(r"[a-zA-Z0-9.:-]+", host)
            or not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}", username)
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(root, str) or not root.startswith("/") or root.startswith("//")
            or len(root) > 1024 or "\\" in root or ".." in root.split("/")
            or any(ord(c) < 32 or ord(c) == 127 for c in root)):
        return {"configured": False, "configuration_error": True}
    hostname = "[" + host + "]" if ":" in host else host
    address = f"sftp://{quote(username, safe='')}@{hostname}:{port}{quote(root, safe='/')}"
    return {"configured": True, "host": host, "port": port, "username": username, "root": root,
            "address": address, "command": "sftp -P " + str(port) + " " + shlex.quote(username + "@" + hostname)}
