import time

import pytest

from web_tools.common.errors import ToolError
from web_tools.main import create_app


@pytest.mark.browser
@pytest.mark.integration
async def test_complete_workflow(settings, fixture_site):
    settings.browser_enabled = True
    settings.searxng_base_url = fixture_site
    settings.test_allowed_origins = [fixture_site]
    app = create_app(settings)
    async with app.router.lifespan_context(app):

        async def call(name, **arguments):
            result = await app.state.registry.call(name, arguments)
            assert result["success"], result
            return result["data"]

        search = await call("web_search", query="fixture documentation")
        assert search["results"][0]["engine"] == "fixture"
        url = search["results"][0]["url"]
        fetched = await call("web_fetch", url=url)
        assert fetched["title"] == "Fixture Docs"
        opened = await call("browser_open", url=url)
        session_id = opened["session_id"]
        snapshot = await call("browser_snapshot", session_id=session_id)
        input_ref = next(e["ref"] for e in snapshot["elements"] if e["tag"] == "input")
        blocked = await app.state.registry.call(
            "browser_type", {"session_id": session_id, "ref": input_ref, "text": "hello"}
        )
        assert blocked["error"]["code"] == "approval_required"
        grant = app.state.browser.interactions.approve(
            settings.human_approval_key.get_secret_value(),
            "browser_type",
            session_id,
            input_ref,
            "hello",
        )
        await call(
            "browser_type",
            session_id=session_id,
            ref=input_ref,
            text="hello",
            approval_token=grant["approval_token"],
        )
        async with app.state.browser.sessions.use(session_id) as session:
            assert await session.page.locator("input").input_value() == "hello"
        stale = await app.state.registry.call(
            "browser_click", {"session_id": session_id, "ref": input_ref}
        )
        assert stale["error"]["code"] == "stale_reference"
        snapshot = await call("browser_snapshot", session_id=session_id)
        button = next(e["ref"] for e in snapshot["elements"] if e["tag"] == "button")
        grant = app.state.browser.interactions.approve(
            settings.human_approval_key.get_secret_value(),
            "browser_click",
            session_id,
            button,
            None,
        )
        await call(
            "browser_click",
            session_id=session_id,
            ref=button,
            approval_token=grant["approval_token"],
        )
        async with app.state.browser.sessions.use(session_id) as session:
            assert await session.page.locator("#result").text_content() == "clicked"
        snapshot = await call("browser_snapshot", session_id=session_id)
        guide = next(e["ref"] for e in snapshot["elements"] if e["name"] == "Read guide")
        await call("browser_click", session_id=session_id, ref=guide)
        snapshot = await call("browser_snapshot", session_id=session_id)
        assert snapshot["title"] == "Guide"
        download_ref = next(
            e["ref"] for e in snapshot["elements"] if e["name"] == "Download manual"
        )
        artifact = await call("browser_download", session_id=session_id, ref=download_ref)
        assert artifact["size"] > 0 and artifact["status"] == "complete"
        assert (await call("file_inspect", file_id=artifact["file_id"]))["sha256"] == artifact[
            "sha256"
        ]
        assert len((await call("file_list"))["files"]) == 1
        direct = await call("file_download", url=f"{fixture_site}/manual.txt")
        assert direct["sha256"] == artifact["sha256"]
        screenshot = await call("browser_screenshot", session_id=session_id)
        assert screenshot["kind"] == "screenshot" and screenshot["content_type"] == "image/png"
        assert len((await call("browser_tabs", session_id=session_id))["tabs"]) == 1
        await call("browser_scroll", session_id=session_id, pixels=300)
        await call("browser_close", session_id=session_id)
        assert not app.state.browser.sessions.sessions


@pytest.mark.browser
async def test_session_limits_expiry_and_private_subresources(settings, fixture_site):
    settings.browser_enabled = True
    settings.browser_max_sessions = 1
    settings.test_allowed_origins = [fixture_site]
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        browser = app.state.browser
        opened = await browser.open(f"{fixture_site}/docs")
        with pytest.raises(ToolError, match="existing browser"):
            await browser.open(f"{fixture_site}/docs")
        session_id = opened["session_id"]
        async with browser.sessions.use(session_id) as session:
            # This internal fetch is test-only; there is no JS-execution tool for clients.
            response = await session.page.evaluate("""async () => {
                try { await fetch('http://169.254.169.254/latest/meta-data'); return 'bad'; }
                catch { return 'blocked'; }
            }""")
            assert response == "blocked"
        browser.sessions.sessions[session_id].touched = time.monotonic() - 1000
        await browser.sessions.reap()
        assert not browser.sessions.sessions
        result = await app.state.registry.call("browser_snapshot", {"session_id": session_id})
        assert result["error"]["code"] == "session_not_found"
