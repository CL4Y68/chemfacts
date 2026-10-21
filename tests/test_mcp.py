"""MCP server tests.

Offline: call the registered tool functions directly with an injected
ChemFacts (FakePubChem + real SQLite + tmp alias registry).
Live: spawn the actual stdio server and drive it with the MCP client.
"""

from __future__ import annotations

import pytest

from chemfacts import mcp_server
from chemfacts.cache import FactCache
from chemfacts.core import ChemFacts
from tests.test_core import FakePubChem


@pytest.fixture()
def facts(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    fake = FakePubChem()
    f = ChemFacts(client=fake, cache=FactCache(str(tmp_path / "facts.db")))
    monkeypatch.setattr(mcp_server, "_FACTS", f)
    return f


def test_tool_resolve(facts):
    out = mcp_server.chemfacts_resolve("NMP")
    assert out["ok"]
    assert out["cid"] == 13387
    assert out["formula"] == "C5H9NO"
    assert out["molecular_weight"] == 99.13
    assert out["cas"] == "872-50-4"


def test_tool_resolve_unresolved(facts):
    out = mcp_server.chemfacts_resolve("definitely-not-a-compound-xyz")
    assert out["ok"] is False
    assert "unresolved" in out["error"]


def test_tool_resolve_alias_pin(facts):
    facts.aliases.add("XNMP", "13387", "test pin")
    out = mcp_server.chemfacts_resolve("XNMP")
    assert out["ok"]
    assert out["cid"] == 13387
    assert out["pinned_via_alias"] == "13387"


def test_tool_lookup_with_provenance(facts):
    out = mcp_server.chemfacts_lookup("IPDI", "flash-point")
    assert out["ok"]
    assert len(out["values"]) == 2
    assert all(v["source"] for v in out["values"])
    assert all("accessed_at" in v for v in out["values"])


def test_tool_lookup_missing_is_honest(facts):
    out = mcp_server.chemfacts_lookup("NMP", "density")
    assert out["ok"] and out["values"] == []
    assert "no sourced value" in out["note"]


def test_tool_crosscheck_status(facts):
    out = mcp_server.chemfacts_crosscheck("IPDI", "flash-point")
    assert out["ok"] and out["status"] == "verified"
    out2 = mcp_server.chemfacts_crosscheck("NMP", "density")
    assert out2["status"] == "unverified"


def test_tool_verify(facts):
    good = mcp_server.chemfacts_verify("NMP", "mw", "99.13")
    assert good["verdict"] == "confirmed"
    bad = mcp_server.chemfacts_verify("NMP", "mw", "110.0")
    assert bad["verdict"] == "mismatch"
    assert "99.13" in bad["closest"]["value"]
    assert "HSDB" in bad["detail"] or "PubChem" in bad["detail"]


def test_tool_card_formats(facts):
    obs = mcp_server.chemfacts_card("IPDI", fmt="obsidian")
    assert obs["ok"] and obs["card_markdown"].startswith("---")
    plain = mcp_server.chemfacts_card("IPDI", fmt="md")
    assert plain["card_markdown"].startswith("# ")
    j = mcp_server.chemfacts_card("IPDI", fmt="json")
    assert '"identity"' in j["card_json"]


def test_tool_alias_roundtrip(facts):
    added = mcp_server.chemfacts_alias(
        "add", alias="DMPA", identifier="4767-03-7", note="not TMEDA"
    )
    assert added["ok"] and added["entry"]["alias"] == "DMPA"
    lst = mcp_server.chemfacts_alias("list")
    assert any(e["alias"] == "DMPA" for e in lst["entries"])
    shown = mcp_server.chemfacts_alias("show", alias="dmpa")
    assert shown["ok"] and shown["entry"]["identifier"] == "4767-03-7"
    rm = mcp_server.chemfacts_alias("remove", alias="DMPA")
    assert rm["ok"]
    assert mcp_server.chemfacts_alias("show", alias="DMPA")["ok"] is False
    assert mcp_server.chemfacts_alias("add")["ok"] is False  # missing args


def test_tools_registered():
    import anyio

    tools = anyio.run(mcp_server.server.list_tools)
    names = {t.name for t in tools}
    assert {"chemfacts_resolve", "chemfacts_lookup", "chemfacts_verify",
            "chemfacts_crosscheck", "chemfacts_card", "chemfacts_alias"} <= names


# -- streamable-http transport (offline: in-process uvicorn, no PubChem needed) --


def test_http_transport_offline(tmp_path, monkeypatch):
    """Serve the streamable-http ASGI app in-process (uvicorn on a thread)
    and drive it with the real MCP client. Offline: _FACTS is monkeypatched
    to a fake-backed ChemFacts, so tool calls touch only local tmp files."""
    import json
    import socket
    import threading
    import time

    import anyio
    import httpx2
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    fake = FakePubChem()
    f = ChemFacts(client=fake, cache=FactCache(str(tmp_path / "facts.db")))
    monkeypatch.setattr(mcp_server, "_FACTS", f)

    app = mcp_server.server.streamable_http_app(streamable_http_path="/mcp")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    usrv = uvicorn.Server(config)
    thread = threading.Thread(target=usrv.run, daemon=True)
    thread.start()
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            break
        except OSError:
            time.sleep(0.3)
    else:
        pytest.fail("http server did not come up")

    try:
        # trust_env=False: never route loopback test traffic through a
        # system/OS-level proxy (e.g. Clash in system-proxy mode).
        http = httpx2.AsyncClient(trust_env=False)

        async def drive():
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=http
            ) as (read, write), ClientSession(read, write) as s:
                await s.initialize()
                tools = await s.list_tools()
                assert len(tools.tools) == 6
                r = await s.call_tool("chemfacts_alias", {"action": "list"})
                assert json.loads(r.content[0].text)["ok"] is True

        anyio.run(drive)
    finally:
        usrv.should_exit = True
        thread.join(timeout=10)


def test_http_subprocess_smoke(tmp_path):
    """The `python -m chemfacts.mcp_server` console entry starts the
    streamable-http service and answers a raw initialize handshake (SSE)."""
    import json
    import os
    import socket
    import subprocess
    import sys
    import time

    import httpx2

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    env = dict(os.environ)
    env["CHEMFACTS_ALIASES"] = str(tmp_path / "aliases.json")
    env["CHEMFACTS_CACHE_DIR"] = str(tmp_path / "cache")
    env["NO_PROXY"] = "127.0.0.1,localhost"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "chemfacts.mcp_server",
            "--transport", "streamable-http", "--host", "127.0.0.1",
            "--port", str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("http server did not come up")

        # trust_env=False: keep the handshake off any system proxy.
        resp = httpx2.Client(trust_env=False).post(
            f"http://127.0.0.1:{port}/mcp",
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
            timeout=15,
        )
        assert resp.status_code == 200
        # SSE response: "event: message\ndata: {json}\n\n"
        data_line = next(
            line for line in resp.text.splitlines() if line.startswith("data:")
        )
        payload = json.loads(data_line[len("data:"):].strip())
        assert payload["result"]["serverInfo"]["name"] == "chemfacts"
    finally:
        proc.terminate()
        proc.wait(timeout=15)


# -- live (real stdio server + MCP client, real PubChem) ----------------------


@pytest.mark.live
def test_stdio_handshake_end_to_end(tmp_path, monkeypatch):
    import sys

    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))

    async def drive():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "chemfacts.mcp_server", "--transport", "stdio"],
            env=None,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "chemfacts_resolve" in names
            result = await session.call_tool("chemfacts_resolve", {"identifier": "NMP"})
            import json

            payload = json.loads(result.content[0].text)
            assert payload["ok"]
            assert payload["cid"] == 13387

    anyio.run(drive)
