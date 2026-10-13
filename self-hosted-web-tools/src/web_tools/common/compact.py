import json

from web_tools.common.errors import ToolError


def compact_data(data: dict, budget: int, arguments: dict) -> dict:
    """Bound aggregate output without corrupting identifiers or citation URLs."""
    truncated = data.get("_truncated", False)
    data.setdefault("_truncated", truncated)

    def size():
        return len(json.dumps(data, separators=(",", ":")))

    # PDF page text needs its own continuation cursor when the aggregate budget
    # (including JSON escaping) is tighter than the extraction character limit.
    if "total_pages" in data and "pages" in data:
        while size() > budget:
            pages = data["pages"]
            if not pages:
                raise ToolError("response_too_large", "PDF metadata exceeds the response budget")
            last = pages[-1]
            text = last["text"]
            data["_truncated"] = True
            data["next_page"] = last["page_number"]
            data["next_text_offset"] = last["text_offset"]
            last["truncated"] = True
            # Binary search the prefix that fits; never cut a citation URL or ID.
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                last["text"] = text[:middle]
                data["next_text_offset"] = last["text_offset"] + middle
                if size() <= budget:
                    low = middle
                else:
                    high = middle - 1
            last["text"] = text[:low]
            data["next_text_offset"] = last["text_offset"] + low
            if low == 0:
                if len(pages) == 1:
                    raise ToolError(
                        "response_too_large", "PDF metadata exceeds the response budget"
                    )
                pages.pop()
            if size() <= budget:
                break
        return data

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
