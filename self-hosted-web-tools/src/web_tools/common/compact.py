import json

from web_tools.common.errors import ToolError


def compact_data(data: dict, budget: int, arguments: dict) -> dict:
    """Bound aggregate output without corrupting identifiers or citation URLs."""
    truncated = data.get("_truncated", False)
    data.setdefault("_truncated", truncated)

    def size():
        return len(json.dumps(data, separators=(",", ":")))

    while size() > budget:
        text = data.get("text")
        if isinstance(text, str) and len(text) > 512:
            data["text"] = text[: max(512, len(text) - (size() - budget))]
            truncated = True
            continue
        lists = [(key, value) for key, value in data.items() if isinstance(value, list) and value]
        if not lists:
            raise ToolError("response_too_large", "Result metadata exceeds the response budget")
        key, items = max(lists, key=lambda item: len(json.dumps(item[1])))
        if key == "files" and len(items) == 1:
            raise ToolError("response_too_large", "A file record exceeds the response budget")
        items.pop()
        if key == "files":
            data["next_offset"] = arguments.get("offset", 0) + len(items)
        truncated = True
    data["_truncated"] = truncated
    return data
