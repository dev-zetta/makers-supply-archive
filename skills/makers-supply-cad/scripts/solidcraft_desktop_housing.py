#!/usr/bin/env python3
"""Build the EA028 example through an explicit SolidCraft desktop MCP bridge."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from solidcraft_bearing_housing import (
    IntegrationError,
    build_commands,
    digest,
    load_reference,
    read_json,
    run_cli,
    validate_health,
    validate_interference,
    validate_measure,
    write_json,
)


class MCPError(IntegrationError):
    """A desktop call failed; a timed-out mutation must not be resent."""


class MCPClient:
    """One JSON-lines stdio session; a reader thread also works with Windows pipes."""

    def __init__(self, argv: list[str], stderr: BinaryIO, timeout: float = 330) -> None:
        self.process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr
        )
        self.timeout = timeout
        self.next_id = 0
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        identifier = self.next_id
        payload = {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as error:
                raise MCPError(
                    "MCP timed out; the desktop may still be applying the request. "
                    "Inspect running/pending and the design before another mutation; do not retry."
                ) from error
            if line is None:
                raise MCPError("MCP closed before replying; inspect the desktop before retrying")
            message = json.loads(line)
            if message.get("id") != identifier:
                continue
            if "error" in message:
                raise MCPError(f"MCP protocol error: {message['error']}")
            result: dict[str, Any] = message["result"]
            return result

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = self.tool(name, arguments)
        if raw.get("isError"):
            message = " ".join(b.get("text", "") for b in raw.get("content", []))
            raise MCPError(f"{name} failed: {message[:1800]}. Inspect state before retrying.")
        data = content_json(raw)
        if data.get("errors") or data.get("parameter_errors"):
            raise MCPError(f"{name} reported errors: {data}")
        return data

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        if self.process.stdout:
            self.process.stdout.close()


def content_json(result: dict[str, Any]) -> dict[str, Any]:
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                value = json.loads(block["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise MCPError("MCP did not return the expected JSON object")


def require_empty(design: dict[str, Any]) -> None:
    if (
        design.get("dirty") is not False
        or design.get("timeline") != []
        or design.get("bodies") != []
        or design.get("sketches") != []
        or design.get("params")
        or design.get("path")
        or design.get("undo")
    ):
        raise IntegrationError(
            "Desktop design is not empty and clean; use a separate blank test window. "
            "The runner never opens or replaces an existing design."
        )


def absolute_commands(steps: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    """Desktop file paths resolve in the app, not in the MCP process's cwd."""
    rewritten = copy.deepcopy(steps)
    output = output.resolve()
    for step in rewritten:
        if step["command"] in {"file.insert_step", "file.export", "file.save", "file.save_as"}:
            path = (output / step["params"]["path"]).resolve()
            if not path.is_relative_to(output):
                raise IntegrationError("A generated desktop command escapes the project directory")
            step["params"]["path"] = str(path)
    return rewritten


def unwrap_batch(raw: dict[str, Any], expected: int) -> list[dict[str, Any]]:
    value = content_json(raw)
    results = value.get("results")
    if (
        raw.get("isError")
        or value.get("ok") is not True
        or value.get("completed") != expected
        or not isinstance(results, list)
        or len(results) != expected
    ):
        raise MCPError(
            f"Desktop batch did not complete: {value}. "
            "Preserve the desktop and inspect applied/rolled_back state before retrying."
        )
    validate_health(results)
    return results


def batch(client: MCPClient, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = client.tool("batch", {"commands": steps, "verbose": False})
    return unwrap_batch(raw, len(steps))


def window_image(result: dict[str, Any], destination: Path) -> dict[str, Any]:
    if result.get("isError"):
        raise MCPError("Explicit desktop window screenshot failed; a model render is not proof")
    metadata = content_json(result)
    if metadata.get("source") != "window" or metadata.get("fallback"):
        raise MCPError("Screenshot is not an actual presented desktop window")
    image = next((b for b in result.get("content", []) if b.get("type") == "image"), None)
    if image is None or image.get("mimeType") != "image/png":
        raise MCPError("Desktop screenshot did not contain PNG image data")
    raw = base64.b64decode(image["data"], validate=True)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MCPError("Desktop screenshot is not a PNG")
    destination.write_bytes(raw)
    return metadata


def checked_design(client: MCPClient) -> dict[str, Any]:
    design = client.call("inspect_design", {"measure": False, "sketches": False})
    validate_health([design])
    return design


def measure(client: MCPClient, clearance: float = 0.2) -> dict[str, Any]:
    value = client.call("measure", {"summary": True})
    validate_measure(value, clearance=clearance)
    checked_design(client)
    return value


def build(cli: str, connect: str, reference: Path, output: Path) -> dict[str, Any]:
    if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", connect):
        raise IntegrationError("--connect must explicitly name 127.0.0.1:PORT")
    if not 1 <= int(connect.rsplit(":", 1)[1]) <= 65535:
        raise IntegrationError("Invalid desktop port")
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise IntegrationError("Output must be a new directory")
    if not output.parent.is_dir():
        raise IntegrationError("Output parent must already exist")
    product, asset, source = load_reference(reference)
    executable = shutil.which(cli)
    if executable is None:
        raise IntegrationError("SolidCraft CLI was not found")
    executable = str(Path(executable).resolve())
    # This final path stays stable while the desktop has the native design open.
    output.mkdir()
    (output / "reference").mkdir()
    shutil.copyfile(source, output / "reference/ea028.stp")
    write_json(output / "reference/source-asset.json", asset)
    client: MCPClient | None = None
    try:
        with (output / "mcp-stderr.log").open("wb") as stderr:
            client = MCPClient(
                [
                    executable,
                    "mcp",
                    "--connect",
                    connect,
                    "--allow-path",
                    str(output),
                    "--param-check",
                    "strict",
                ],
                stderr,
            )
            initialized = client.request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "makers-supply-desktop-housing", "version": "1"},
                },
            )
            client.notify("notifications/initialized")
            tools = client.request("tools/list", {})
            required = {
                "batch",
                "execute",
                "measure",
                "inspect_design",
                "screenshot",
                "set_parameter",
                "save",
                "skill_reference",
            }
            if not required.issubset({t["name"] for t in tools["tools"]}):
                raise MCPError("Desktop server lacks required modeling tools")
            skill = client.tool("skill_reference", {"skill": "solidcraft-modeling"})
            if skill.get("isError"):
                raise MCPError("The server's modeling reference could not be loaded")
            initial = checked_design(client)
            require_empty(initial)
            write_json(output / "initial-desktop.json", initial)
            all_steps = absolute_commands(build_commands([]), output)
            index = next(i for i, s in enumerate(all_steps) if s["command"] == "file.insert_step")
            print("Building the desktop housing features…", file=sys.stderr, flush=True)
            stage = batch(client, all_steps[:index])
            imported = client.call(
                "execute",
                {
                    "command": "file.insert_step",
                    "params": all_steps[index]["params"],
                },
            )
            validate_health([imported])
            names = imported.get("created_bodies", [])
            if len(names) != 2:
                raise IntegrationError("The EA028 source must import as two desktop solids")
            steps = absolute_commands(build_commands(names), output)
            # Place both imported solids, then read health/measure/interference; exports wait.
            rest = [s for s in steps[index + 1 :] if s["command"] != "file.export"]
            placed = batch(client, rest)
            baseline = measure(client)
            overlap = client.call("execute", {"command": "inspect.interference", "params": {}})
            validate_interference(overlap)
            client.call("set_parameter", {"name": "diametral_clearance", "value": "0.4 mm"})
            changed = measure(client, clearance=0.4)
            client.call("save", {"path": str(output / "clearance-0.4.sc")})
            client.call("set_parameter", {"name": "diametral_clearance", "value": "-0.2 mm"})
            negative = client.call("execute", {"command": "inspect.interference", "params": {}})
            # Restore before validating the control, leaving baseline even if that check fails.
            client.call("set_parameter", {"name": "diametral_clearance", "value": "0.2 mm"})
            restored = measure(client)
            validate_interference(negative, negative=True)
            final_overlap = client.call(
                "execute",
                {
                    "command": "inspect.interference",
                    "params": {},
                },
            )
            validate_interference(final_overlap)
            print("Saving and exporting the restored desktop model…", file=sys.stderr, flush=True)
            client.call("save", {"path": str(output / "bearing-housing.sc")})
            export_steps = [s for s in steps if s["command"] == "file.export"]
            exports = batch(client, export_steps)
            screenshot = window_image(
                client.tool(
                    "screenshot",
                    {
                        "source": "window",
                        "view": "iso",
                        "path": str(output / "desktop-window.png"),
                    },
                ),
                output / "desktop-window.png",
            )
            client.call("save", {"path": str(output / "bearing-housing.sc")})
            final = checked_design(client)
            if final.get("dirty"):
                raise IntegrationError("Desktop baseline was not saved cleanly")
            run_cli(
                executable,
                output,
                "eval",
                str(output / "bearing-housing.sc"),
                "--json-out",
                str(output / "native-reopen.json"),
            )
            reopened = read_json(output / "native-reopen.json")
            validate_health([reopened])
            validate_measure(reopened)
            run_cli(
                executable,
                output,
                "eval",
                str(output / "housing.step"),
                "--json-out",
                str(output / "step-reimport.json"),
            )
            back = read_json(output / "step-reimport.json")
            validate_health([back])
            validate_measure(back, references=False)
            variant = next(
                v
                for v in product["variants"]
                if v["region"] == "eu" and v.get("part_number") == "EA028"
            )
            write_json(
                output / "hardware-bom.json",
                {
                    "items": [
                        {
                            "product_id": product["id"],
                            "region": "eu",
                            "variant_id": variant["variant_id"],
                            "part_number": "EA028",
                            "quantity": 1,
                            "quantity_unit": "pack",
                            "pack_size": 2,
                            "physical_part_quantity": 1,
                            "spare_part_quantity": 1,
                            "source_asset": asset,
                            "reference_file": "reference/ea028.stp",
                            "dimension_source": next(
                                t
                                for t in product["source_tables"]
                                if any(row[0] == "EA028" for row in t["rows"])
                            ),
                        }
                    ]
                },
            )
            evidence = {
                "passed": True,
                "mode": "explicit desktop MCP bridge",
                "connect": connect,
                "serverInfo": initialized.get("serverInfo"),
                "initial": initial,
                "reference_sha256": asset["sha256"],
                "import": imported,
                "build_results": stage + [imported] + placed,
                "measure": baseline,
                "interference": overlap,
                "parameter_variant": changed,
                "negative_control": negative,
                "restored_measure": restored,
                "restored_interference": final_overlap,
                "final_desktop": final,
                "window_screenshot": screenshot,
                "native_reopen": reopened,
                "step_reimport": back,
                "export_results": exports,
                "exports": [
                    {
                        "name": f"housing.{ext}",
                        "sha256": digest(output / f"housing.{ext}"),
                        "bytes": (output / f"housing.{ext}").stat().st_size,
                    }
                    for ext in ["step", "stl", "3mf"]
                ],
                "limitations": [
                    "Prototype clearances; physical fit is untested.",
                    "This open-top housing has no axial retainer.",
                ],
            }
            write_json(output / "validation.json", evidence)
            housing = next(b for b in restored["bodies"] if b["name"] == "Housing")
            return {
                "passed": True,
                "output": str(output),
                "mode": evidence["mode"],
                "housing_volume_mm3": housing["volume_mm3"],
                "bodies": 3,
            }
    except Exception as error:
        write_json(
            output / "validation-failure.json",
            {
                "passed": False,
                "error": str(error),
                "desktop_may_have_changes": True,
                "note": "Files were preserved. Inspect the desktop before retrying any mutation.",
            },
        )
        raise
    finally:
        if client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solidcraft-cli", default="solidcraft-cli")
    parser.add_argument("--connect", required=True, help="Explicit desktop at 127.0.0.1:PORT")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New, stable project directory")
    args = parser.parse_args(argv)
    try:
        result = build(args.solidcraft_cli, args.connect, args.reference, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except (
        IntegrationError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"solidcraft desktop: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
