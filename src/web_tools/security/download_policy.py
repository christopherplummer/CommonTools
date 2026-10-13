import re
from pathlib import PureWindowsPath

from web_tools.common.errors import ToolError


def safe_filename(filename: str) -> str:
    if not filename or filename in {".", ".."} or any(c in filename for c in "/\\\0"):
        raise ToolError("invalid_filename", "Supply a filename without directories")
    if len(filename) > 180 or re.search(r'[<>:"|?*\x00-\x1f]', filename):
        raise ToolError("invalid_filename", "Filename contains unsupported characters")
    if filename.startswith(".") or filename.endswith((".", " ")):
        raise ToolError(
            "invalid_filename", "Hidden filenames or trailing dots/spaces are not allowed"
        )
    if PureWindowsPath(filename).is_reserved():
        raise ToolError("invalid_filename", "Reserved filename")
    return filename
