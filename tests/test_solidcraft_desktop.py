from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/makers-supply-cad/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "solidcraft_desktop_adapter", SCRIPTS / "solidcraft_desktop_housing.py"
)
assert SPEC is not None and SPEC.loader is not None
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1kAAAAASUVORK5CYII="
)


def result(value: Any, **extra: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value)}], **extra}


def empty_design() -> dict[str, Any]:
    return {
        "dirty": False,
        "timeline": [],
        "bodies": [],
        "sketches": [],
        "params": [],
        "path": None,
        "undo": 0,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("dirty", True),
        ("timeline", [{"name": "User feature"}]),
        ("bodies", ["User part"]),
        ("sketches", ["User sketch"]),
        ("params", [{"name": "width"}]),
        ("path", "/saved/blank.sc"),
        ("undo", 2),
    ],
)
def test_existing_work_is_refused(field: str, value: Any) -> None:
    baseline = empty_design()
    desktop.require_empty(baseline)
    baseline[field] = value
    with pytest.raises(desktop.IntegrationError, match="not empty and clean"):
        desktop.require_empty(baseline)


def test_missing_state_is_not_proof_of_empty_desktop() -> None:
    with pytest.raises(desktop.IntegrationError):
        desktop.require_empty({})


def test_desktop_file_commands_use_absolute_granted_project_paths(tmp_path: Path) -> None:
    source = desktop.build_commands(["Reference A", "Reference B"])
    before = copy.deepcopy(source)
    rewritten = desktop.absolute_commands(source, tmp_path)
    assert source == before
    paths = [Path(s["params"]["path"]) for s in rewritten if "path" in s["params"]]
    assert len(paths) == 4
    assert all(p.is_absolute() and p.is_relative_to(tmp_path) for p in paths)
    assert paths[0] == tmp_path / "reference/ea028.stp"
    for s in rewritten:
        if s["command"] == "file.export":
            assert s["params"]["bodies"] == ["Housing"]
    with pytest.raises(desktop.IntegrationError, match="escapes"):
        desktop.absolute_commands(
            [{"command": "file.export", "params": {"path": "../outside.step"}}], tmp_path
        )


@pytest.mark.parametrize(
    "value,error",
    [
        ({"ok": False, "completed": 1, "results": [{}], "applied": [0]}, False),
        ({"ok": True, "completed": 1, "results": [{}]}, False),
        ({"ok": True, "completed": 2, "results": [{}]}, False),
        ({"ok": True, "completed": 2, "results": [{}, {}]}, True),
    ],
)
def test_partial_or_errored_batch_never_counts_as_completed(
    value: dict[str, Any], error: bool
) -> None:
    with pytest.raises(desktop.MCPError, match="did not complete"):
        desktop.unwrap_batch(result(value, isError=error), 2)


def test_batch_unwraps_raw_command_results_and_checks_warnings() -> None:
    values = [{"created_bodies": ["Housing"]}, {"timeline": [{"name": "Seat"}]}]
    assert (
        desktop.unwrap_batch(result({"ok": True, "completed": 2, "results": values}), 2) == values
    )
    values[1]["timeline"][0]["warning"] = "Boolean retry"
    with pytest.raises(desktop.IntegrationError, match="Unhealthy"):
        desktop.unwrap_batch(result({"ok": True, "completed": 2, "results": values}), 2)


@pytest.mark.parametrize(
    "metadata",
    [
        {"source": "model"},
        {"source": "window", "fallback": "model render"},
        {},
    ],
)
def test_model_render_cannot_prove_desktop_window(metadata: dict[str, Any], tmp_path: Path) -> None:
    raw = result(metadata)
    raw["content"].append(
        {"type": "image", "mimeType": "image/png", "data": base64.b64encode(PNG).decode()}
    )
    with pytest.raises(desktop.MCPError, match="actual presented"):
        desktop.window_image(raw, tmp_path / "shot.png")
    assert not (tmp_path / "shot.png").exists()


def test_explicit_window_png_is_saved_without_base64_logging(tmp_path: Path) -> None:
    raw = result({"source": "window", "width": 1, "height": 1})
    raw["content"].append(
        {"type": "image", "mimeType": "image/png", "data": base64.b64encode(PNG).decode()}
    )
    metadata = desktop.window_image(raw, tmp_path / "shot.png")
    assert metadata["source"] == "window"
    assert (tmp_path / "shot.png").read_bytes() == PNG


def test_stdio_client_reads_large_chunked_reply_after_notification(tmp_path: Path) -> None:
    server = tmp_path / "server.py"
    server.write_text(
        "import json,sys\n"
        "for line in sys.stdin.buffer:\n"
        " p=json.loads(line)\n"
        " if 'id' not in p: continue\n"
        " sys.stdout.write(json.dumps({'jsonrpc':'2.0','method':'notifications/progress'})+'\\n')\n"
        " b=(json.dumps({'id':p['id'],'result':{'large':'x'*1500000}})+'\\n').encode()\n"
        " for i in range(0,len(b),4093):\n"
        "  sys.stdout.buffer.write(b[i:i+4093]); sys.stdout.buffer.flush()\n"
    )
    with (tmp_path / "stderr").open("wb") as stderr:
        client = desktop.MCPClient([sys.executable, str(server)], stderr, timeout=5)
        try:
            client.notify("notifications/initialized")
            value = client.request("tools/list", {})
            assert len(value["large"]) == 1500000
        finally:
            client.close()


def test_timeout_does_not_resend_mutation(tmp_path: Path) -> None:
    server = tmp_path / "slow.py"
    received = tmp_path / "received.jsonl"
    server.write_text(
        "import sys,time\n"
        f"with open({str(received)!r},'wb') as f:\n"
        " f.write(sys.stdin.buffer.readline()); f.flush()\n"
        " time.sleep(0.25)\n"
    )
    with (tmp_path / "stderr").open("wb") as stderr:
        client = desktop.MCPClient([sys.executable, str(server)], stderr, timeout=0.05)
        try:
            with pytest.raises(desktop.MCPError, match="do not retry"):
                client.request("tools/call", {"name": "batch", "arguments": {}})
        finally:
            client.close()
    lines = received.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["params"]["name"] == "batch"


@pytest.mark.parametrize("message", ["still running: request 17", "no SolidCraft app is listening"])
def test_plain_text_tool_error_preserves_actionable_reason(
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object.__new__(desktop.MCPClient)
    monkeypatch.setattr(
        client,
        "tool",
        lambda *_: {
            "isError": True,
            "content": [{"type": "text", "text": message}],
        },
    )
    with pytest.raises(desktop.MCPError, match=message):
        client.call("execute", {"command": "solid.box", "params": {}})


def test_nonempty_app_is_not_mutated_and_failure_files_stay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "reference.stp"
    source.write_bytes(b"STEP")
    monkeypatch.setattr(desktop, "load_reference", lambda _: ({}, {}, source))
    calls = []

    class Client:
        def __init__(self, argv: list[str], stderr: Any) -> None:
            assert "--headless" not in argv
            assert argv[argv.index("--connect") + 1] == "127.0.0.1:28789"

        def request(self, method: str, params: Any) -> dict[str, Any]:
            if method == "tools/list":
                return {
                    "tools": [
                        {"name": n}
                        for n in [
                            "batch",
                            "execute",
                            "measure",
                            "inspect_design",
                            "screenshot",
                            "set_parameter",
                            "save",
                            "skill_reference",
                        ]
                    ]
                }
            return {"serverInfo": {"name": "solidcraft"}}

        def notify(self, *args: Any) -> None:
            pass

        def tool(self, name: str, arguments: Any) -> dict[str, Any]:
            calls.append(name)
            assert name == "skill_reference"
            return {"content": [{"type": "text", "text": "Modeling reference"}]}

        def call(self, name: str, arguments: Any) -> dict[str, Any]:
            calls.append(name)
            assert name == "inspect_design"
            return {**empty_design(), "timeline": [{"name": "User work"}]}

        def close(self) -> None:
            pass

    monkeypatch.setattr(desktop, "MCPClient", Client)
    output = tmp_path / "project"
    with pytest.raises(desktop.IntegrationError, match="not empty and clean"):
        desktop.build(sys.executable, "127.0.0.1:28789", tmp_path, output)
    assert calls == ["skill_reference", "inspect_design"]
    assert not (output / "bearing-housing.sc").exists()
    assert json.loads((output / "validation-failure.json").read_text())["passed"] is False


@pytest.mark.parametrize("connect", ["", "localhost:28789", "example.com:1234", "127.0.0.1:0"])
def test_explicit_local_desktop_is_required(connect: str, tmp_path: Path) -> None:
    with pytest.raises(desktop.IntegrationError):
        desktop.build(sys.executable, connect, tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()
