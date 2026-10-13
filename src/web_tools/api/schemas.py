from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(Input):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(5, ge=1, le=20)
    language: str = Field("en", min_length=2, max_length=20, pattern=r"^[a-zA-Z-]+$")


class FetchInput(Input):
    url: str = Field(min_length=1, max_length=4096)
    max_chars: int = Field(12000, ge=100, le=100000)


class DownloadInput(Input):
    url: str = Field(min_length=1, max_length=4096)
    filename: str | None = Field(None, min_length=1, max_length=180)


class InspectInput(Input):
    file_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ListInput(Input):
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class OpenInput(Input):
    url: str = Field(min_length=1, max_length=4096)
    session_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")


class SessionInput(Input):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class SnapshotInput(SessionInput):
    max_chars: int = Field(8000, ge=100, le=100000)


class RefInput(SessionInput):
    ref: str = Field(pattern=r"^[a-f0-9]{12}:\d{1,3}$")


class ClickInput(RefInput):
    approval_token: str | None = Field(None, max_length=100)


class TypeInput(ClickInput):
    text: str = Field(max_length=4000)


class ScrollInput(SessionInput):
    pixels: int = Field(700, ge=-5000, le=5000)


class BrowserDownloadInput(RefInput):
    filename: str | None = Field(None, min_length=1, max_length=180)


class ApprovalInput(RefInput):
    action: Literal["browser_click", "browser_type"]
    text: str | None = Field(None, max_length=4000)
