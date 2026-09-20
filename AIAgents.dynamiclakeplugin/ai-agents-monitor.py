#!/usr/bin/env python3
"""
DynamicLake AI Agents JSON plugin for Codex, Claude, and OpenCode.

The plugin reads local agent sessions and sends predefined JSON components
to DynamicLake.
"""

from __future__ import annotations

import base64
import json
import os
import selectors
import socket
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    return min(max(number, minimum), maximum)


SCHEMA_VERSION = 1
PLUGIN_NAME = "AI Agents"
STALE_SECONDS = env_float("AI_AGENTS_STALE_SECONDS", 90, 15, 600)
COMPLETED_VISIBLE_SECONDS = env_float("AI_AGENTS_COMPLETED_VISIBLE_SECONDS", 20, 0, 120)
POLL_SECONDS = 1.0
MAX_HEAD_BYTES = 96_000
MAX_TAIL_BYTES = 512_000
MAX_LINE_CHARS = 220_000


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    activity_id: str
    system_image: str
    logo: str


CODEX = Source("codex", "Codex", "ai-agents.codex", "terminal.fill", "codex.png")
CLAUDE = Source("claude", "Claude", "ai-agents.claude", "sparkles", "claude.png")
OPENCODE = Source("opencode", "OpenCode", "ai-agents.opencode", "chevron.left.forwardslash.chevron.right", "opencode.png")
SOURCES = (CODEX, CLAUDE, OPENCODE)


def plugin_settings() -> dict[str, Any]:
    settings_path = os.environ.get("DYNAMICLAKE_PLUGIN_SETTINGS_PATH")
    if settings_path:
        try:
            values = json.loads(Path(settings_path).read_text(encoding="utf-8")).get("values", {})
            if isinstance(values, dict):
                return values
        except (OSError, ValueError, TypeError):
            pass
    return {}


def setting_bool(key: str, default: bool, values: dict[str, Any] | None = None) -> bool:
    values = plugin_settings() if values is None else values
    if isinstance(values.get(key), bool):
        return values[key]
    env_key = "DYNAMICLAKE_SETTING_" + "".join(
        f"_{char}" if char.isupper() else char for char in key
    ).upper()
    setting = os.environ.get(env_key)
    if setting is not None:
        return setting.strip().lower() in {"1", "true", "yes", "on"}
    return default


def show_agent_logos() -> bool:
    return setting_bool("showAgentLogos", False)


def enabled_sources(values: dict[str, Any] | None = None) -> tuple[Source, ...]:
    values = plugin_settings() if values is None else values
    enabled: list[Source] = []
    for source in SOURCES:
        if source == OPENCODE:
            is_enabled = setting_bool("enableOpenCode", env_bool("AI_AGENTS_ENABLE_OPENCODE", True), values)
        else:
            # DynamicLake provides native Codex/Claude controls outside the
            # plugin manifest. Ignore obsolete saved plugin-setting values.
            is_enabled = env_bool(f"AI_AGENTS_ENABLE_{source.key.upper()}", True)
        if is_enabled:
            enabled.append(source)
    return tuple(enabled)


def source_logo(source: Source) -> dict[str, str] | None:
    path = Path(__file__).resolve().parent / "logos" / source.logo
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 48_000:
        return None
    return {
        "type": "image",
        "source": "inlineData",
        "mimeType": "image/png",
        "base64Data": base64.b64encode(data).decode("ascii"),
    }


@dataclass
class AgentState:
    session_id: str
    title: str
    project_name: str
    project_path: str | None
    phase: str
    detail: str
    last_tool_name: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    updated_at: datetime

    @property
    def title_text(self) -> str:
        return self.title.strip() or self.project_text

    @property
    def project_text(self) -> str:
        return self.project_name.strip() or "Project"

    @property
    def detail_text(self) -> str:
        return self.detail.strip() or phase_title(self.phase)

    @property
    def is_active(self) -> bool:
        age = age_seconds(self.updated_at)
        if self.phase == "paused":
            return False
        if self.phase == "completed":
            return age <= COMPLETED_VISIBLE_SECONDS
        return age <= STALE_SECONDS

    @property
    def publish_signature(self) -> str:
        return "|".join(
            [
                self.session_id,
                self.title_text,
                self.project_text,
                self.phase,
                self.detail_text,
                self.last_tool_name or "",
                str(self.total_tokens),
                str(int(self.updated_at.timestamp() / 5)),
            ]
        )


class DynamicLakeJSONClient:
    def __init__(self, socket_path: str | None = None) -> None:
        self.socket_path = socket_path or f"/tmp/dynamiclake-json-{os.getuid()}.sock"
        self.socket: socket.socket | None = None
        self.selector = selectors.DefaultSelector()
        self.buffer = bytearray()
        self.expected_length: int | None = None

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)
        sock.setblocking(False)
        self.socket = sock
        self.selector.register(sock, selectors.EVENT_READ)

    def close(self) -> None:
        if self.socket is None:
            return
        self.selector.unregister(self.socket)
        self.socket.close()
        self.socket = None

    def send(self, message: dict[str, Any]) -> None:
        if self.socket is None:
            raise RuntimeError("DynamicLake client is not connected.")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        frame = struct.pack(">I", len(payload)) + payload
        # Inline logos make frames larger; sendall on a nonblocking socket can
        # raise EAGAIN after a partial write and corrupt the next frame.
        self.socket.settimeout(1.0)
        try:
            self.socket.sendall(frame)
        finally:
            self.socket.setblocking(False)

    def read_available(self, timeout: float = 0.0) -> list[dict[str, Any]]:
        if self.socket is None:
            return []

        messages: list[dict[str, Any]] = []
        for key, _ in self.selector.select(timeout):
            chunk = key.fileobj.recv(4096)
            if not chunk:
                raise ConnectionError("DynamicLake closed the connection.")
            self.buffer.extend(chunk)

        while True:
            if self.expected_length is None:
                if len(self.buffer) < 4:
                    break
                self.expected_length = struct.unpack(">I", self.buffer[:4])[0]
                del self.buffer[:4]

            if len(self.buffer) < self.expected_length:
                break

            payload = bytes(self.buffer[: self.expected_length])
            del self.buffer[: self.expected_length]
            self.expected_length = None
            messages.append(json.loads(payload.decode("utf-8")))

        return messages


class AgentsJSONPlugin:
    def __init__(self) -> None:
        self.client = DynamicLakeJSONClient(os.environ.get("DYNAMICLAKE_JSON_SOCKET"))
        self.published_signatures: dict[str, str] = {}
        self.dismissed_session_ids: dict[str, str] = {}
        self.reconciled_activity_ids: set[str] = set()

    def run(self) -> int:
        try:
            self.client.connect()
        except OSError as error:
            print(f"Unable to connect to DynamicLake socket {self.client.socket_path}: {error}", file=sys.stderr)
            print("Start DynamicLakePro before running this plugin.", file=sys.stderr)
            return 1

        print(f"{PLUGIN_NAME} connected to {self.client.socket_path}")
        print("Monitoring Codex, Claude, and OpenCode sessions. Press Ctrl-C to stop.")

        try:
            while True:
                self.handle_callbacks()
                self.refresh_sources()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopping.")
            self.dismiss_all()
            return 0
        finally:
            self.client.close()

    def handle_callbacks(self) -> None:
        for message in self.client.read_available(timeout=0):
            print("Received:", json.dumps(message, indent=2))
            if message.get("type") != "action":
                continue

            action_id = message.get("actionID")
            activity_id = message.get("activityID")
            if action_id in {"dismiss", "dismiss-codex", "dismiss-claude", "dismiss-opencode"} and isinstance(activity_id, str):
                source = source_for_activity_id(activity_id)
                current_state = load_latest_state(source) if source else None
                if current_state is not None:
                    self.dismissed_session_ids[activity_id] = current_state.session_id
                self.client.send(dismiss_message(activity_id))
                self.published_signatures.pop(activity_id, None)

    def refresh_sources(self) -> None:
        active_sources = enabled_sources()
        for source in SOURCES:
            first_refresh = source.activity_id not in self.reconciled_activity_ids
            self.reconciled_activity_ids.add(source.activity_id)
            if source not in active_sources:
                was_published = self.published_signatures.pop(source.activity_id, None) is not None
                if first_refresh or was_published:
                    self.client.send(dismiss_message(source.activity_id))
                self.dismissed_session_ids.pop(source.activity_id, None)
                continue
            result = load_latest_state(source)
            if result is not None and self.dismissed_session_ids.get(source.activity_id) != result.session_id:
                self.dismissed_session_ids.pop(source.activity_id, None)

            is_dismissed = (
                result is not None
                and self.dismissed_session_ids.get(source.activity_id) == result.session_id
            )
            if result is None or not result.is_active or is_dismissed:
                was_published = self.published_signatures.pop(source.activity_id, None) is not None
                if first_refresh or was_published:
                    self.client.send(dismiss_message(source.activity_id))
                continue

            signature = result.publish_signature + f"|logos={show_agent_logos()}"
            command_type = "create" if source.activity_id not in self.published_signatures else "update"
            if self.published_signatures.get(source.activity_id) == signature:
                continue

            self.client.send(activity_message(source, result, command_type))
            self.published_signatures[source.activity_id] = signature

    def dismiss_all(self) -> None:
        for source in SOURCES:
            self.client.send(dismiss_message(source.activity_id))


def activity_message(source: Source, state: AgentState, command_type: str) -> dict[str, Any]:
    status = json_status_for_phase(state.phase)
    tint = tint_for_phase(state.phase)
    center_text = f"{source.title} - {state.project_text} - {state.detail_text}"
    logo = source_logo(source)
    show_logos = show_agent_logos()
    completed_with_logo = show_logos and logo is not None and state.phase == "completed"
    check_slot: dict[str, Any] = {
        "type": "image",
        "source": "sfSymbol",
        "systemImage": "checkmark.circle.fill",
        "tint": "green",
    }
    compact_surface: dict[str, Any] = {
        "leftSlot": {
            "type": "image",
            "source": "sfSymbol",
            "systemImage": compact_symbol_for_phase(state.phase),
            "tint": tint,
        }
    }
    if show_logos and logo is not None:
        compact_surface["leftSlot"] = logo

    compact_surface["rightSlot"] = {
        "type": "progress",
        "status": status,
        "tint": tint,
    }
    progress_value = progress_value_for_phase(state.phase)
    if progress_value is not None:
        compact_surface["rightSlot"]["value"] = progress_value
    if completed_with_logo:
        compact_surface["rightSlot"] = check_slot.copy()

    extra_left_slot = logo or {
        "type": "image",
        "source": "sfSymbol",
        "systemImage": source.system_image,
        "tint": tint,
    }
    extra_surface = {"leftSlot": extra_left_slot}

    sneak_peek_left: dict[str, Any] = {
        "type": "status",
        "status": status,
        "systemImage": symbol_for_phase(state.phase),
        "tint": tint,
    }
    if show_logos and logo is not None:
        sneak_peek_left = logo

    sneak_peek: dict[str, Any] = {
        "leftSlot": sneak_peek_left,
        "center": {
            "type": "text",
            "text": center_text,
            "style": "marquee",
            "tint": "white",
        },
    }
    if completed_with_logo:
        sneak_peek["rightSlot"] = check_slot.copy()

    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestID": f"{source.key}-{int(time.time())}",
        "type": command_type,
        "activityID": source.activity_id,
        "title": PLUGIN_NAME,
        "priority": "normal",
        "size": "small",
        "surfaces": {
            "compactLiveActivity": compact_surface,
            "extraLiveActivity": extra_surface,
            "sneakPeek": sneak_peek,
        },
    }


def dismiss_message(activity_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestID": f"dismiss-{activity_id}",
        "type": "dismiss",
        "activityID": activity_id,
    }


def source_for_activity_id(activity_id: str) -> Source | None:
    return next((source for source in SOURCES if source.activity_id == activity_id), None)


def load_latest_state(source: Source) -> AgentState | None:
    try:
        if source == CODEX:
            return load_codex_state()
        if source == CLAUDE:
            return load_claude_state()
        if source == OPENCODE:
            return load_opencode_state()
        return None
    except FileNotFoundError:
        return None
    except Exception as error:
        print(f"{source.title}: {error}")
        return None


def load_codex_state() -> AgentState:
    sessions_dir = codex_home() / "sessions"
    if not sessions_dir.exists():
        raise FileNotFoundError(f"Missing Codex path: {sessions_dir}")

    session_file = newest_jsonl(sessions_dir)
    parser = CodexSessionParser()
    for line in head_lines(session_file):
        obj = json_object(line)
        if obj and obj.get("type") in {"session_meta", "turn_context"}:
            parser.consume(line)
    parser.may_infer_turn = True
    for line in tail_lines(session_file):
        parser.consume(line)
    parsed = parser.snapshot()
    session_id = parsed["session_id"] or codex_session_id_from_path(session_file)
    updated_at = parsed["updated_at"] or mtime(session_file)

    return AgentState(
        session_id=session_id,
        title=display_title(parsed["title"], parsed["project_name"], "Codex CLI"),
        project_name=parsed["project_name"],
        project_path=parsed["cwd"],
        phase=parsed["phase"],
        detail=parsed["detail"],
        last_tool_name=parsed["last_tool_name"],
        input_tokens=parsed["input_tokens"],
        output_tokens=parsed["output_tokens"],
        total_tokens=parsed["total_tokens"],
        updated_at=updated_at,
    )


def load_claude_state() -> AgentState:
    projects_dir = claude_home() / "projects"
    if not projects_dir.exists():
        raise FileNotFoundError(f"Missing Claude Code path: {projects_dir}")

    session_file = newest_jsonl(projects_dir)
    parser = ClaudeSessionParser(session_file)
    for line in session_lines(session_file):
        parser.consume(line)
    parsed = parser.snapshot()
    session_id = parsed["session_id"] or session_file.stem
    updated_at = max(parsed["updated_at"] or datetime.min.replace(tzinfo=timezone.utc), mtime(session_file))

    return AgentState(
        session_id=session_id,
        title=display_title(parsed["title"], parsed["project_name"], "Claude Code"),
        project_name=parsed["project_name"],
        project_path=parsed["cwd"],
        phase=parsed["phase"],
        detail=parsed["detail"],
        last_tool_name=parsed["last_tool_name"],
        input_tokens=parsed["input_tokens"],
        output_tokens=parsed["output_tokens"],
        total_tokens=parsed["total_tokens"],
        updated_at=updated_at,
    )


def opencode_database() -> Path:
    override = os.environ.get("OPENCODE_DB")
    data_dir = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "opencode"
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else data_dir / path
    candidates = [data_dir / "opencode-prod.db", data_dir / "opencode.db"]
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise FileNotFoundError("No OpenCode database found")
    return max(existing, key=lambda path: path.stat().st_mtime)


def load_opencode_state() -> AgentState:
    database = opencode_database()
    # mode=ro prevents this monitor from creating or changing OpenCode data.
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=0.2) as connection:
        connection.row_factory = sqlite3.Row
        session = connection.execute(
            "SELECT id, directory, title, time_updated FROM session "
            "WHERE time_archived IS NULL ORDER BY time_updated DESC LIMIT 1"
        ).fetchone()
        if session is None:
            raise FileNotFoundError("No OpenCode sessions found")
        message = connection.execute(
            "SELECT id, data, time_updated FROM message WHERE session_id = ? "
            "ORDER BY time_created DESC, id DESC LIMIT 1", (session["id"],)
        ).fetchone()
        part = None
        if message is not None:
            part = connection.execute(
                "SELECT data, time_updated FROM part WHERE message_id = ? "
                "AND json_extract(data, '$.type') IN ('reasoning', 'text', 'tool') "
                "ORDER BY time_created DESC, id DESC LIMIT 1", (message["id"],)
            ).fetchone()
        usage_message = connection.execute(
            "SELECT data FROM message WHERE session_id = ? AND json_extract(data, '$.role') = 'assistant' "
            "AND COALESCE(json_extract(data, '$.tokens.total'), 0) > 0 "
            "ORDER BY time_created DESC, id DESC LIMIT 1", (session["id"],)
        ).fetchone()

    message_data = json_object(message["data"]) if message is not None else None
    part_data = json_object(part["data"]) if part is not None else None
    phase, detail, tool_name = opencode_phase(message_data, part_data)
    usage_data = json_object(usage_message["data"]) if usage_message is not None else message_data
    tokens = usage_data.get("tokens") if isinstance(usage_data, dict) else None
    tokens = tokens if isinstance(tokens, dict) else {}
    input_tokens = int_value(tokens.get("input")) or 0
    output_tokens = int_value(tokens.get("output")) or 0
    total_tokens = int_value(tokens.get("total")) or input_tokens + output_tokens
    updated_ms = max(
        session["time_updated"] or 0,
        message["time_updated"] if message is not None else 0,
        part["time_updated"] if part is not None else 0,
    )
    directory = string_value(session["directory"])
    project_name = project_name_from_path(directory)
    return AgentState(
        session_id=session["id"],
        title=display_title(session["title"], project_name, "OpenCode"),
        project_name=project_name,
        project_path=directory,
        phase=phase,
        detail=detail,
        last_tool_name=tool_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        updated_at=datetime.fromtimestamp(updated_ms / 1000, timezone.utc),
    )


def opencode_phase(message: dict[str, Any] | None, part: dict[str, Any] | None) -> tuple[str, str, str | None]:
    if not message:
        return "paused", "Idle", None
    if message.get("role") == "user":
        return "running", "Working", None
    if message.get("role") != "assistant":
        return "paused", "Idle", None
    if isinstance(message.get("error"), dict):
        return "failed", "Failed", None
    timing = message.get("time")
    if isinstance(timing, dict) and timing.get("completed"):
        if message.get("finish") != "tool-calls":
            return "completed", "Complete", None
    if part and part.get("type") == "tool":
        tool_name = string_value(part.get("tool"))
        return "tool", codex_tool_detail(tool_name), tool_name
    if part and part.get("type") == "text":
        return "responding", "Writing response", None
    return "thinking", "Thinking", None


class CodexSessionParser:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.cwd: str | None = None
        self.title: str | None = None
        self.updated_at: datetime | None = None
        self.phase = "paused"
        self.detail = "Idle"
        self.active_turn_id: str | None = None
        self.has_open_turn = False
        self.may_infer_turn = False
        self.last_tool_name: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def consume(self, line: str) -> None:
        if len(line) > MAX_LINE_CHARS:
            return
        obj = json_object(line)
        if not obj:
            return

        payload = obj.get("payload")
        if not isinstance(payload, dict):
            return

        event_type = obj.get("type")
        payload_type = payload.get("type")
        activity_event = (
            event_type == "event_msg"
            and (
                payload_type == "task_started"
                or ((self.has_open_turn or self.may_infer_turn) and payload_type in {
                    "task_complete", "turn_aborted", "user_message", "agent_message", "token_count"
                })
            )
        ) or (event_type == "response_item" and (self.has_open_turn or self.may_infer_turn))
        timestamp = parse_date(obj.get("timestamp"))
        if timestamp and activity_event:
            self.updated_at = max_date(self.updated_at, timestamp)
        if event_type == "session_meta":
            self.session_id = string_value(payload.get("session_id")) or string_value(payload.get("id")) or self.session_id
            self.cwd = string_value(payload.get("cwd")) or self.cwd
            self.title = string_value(payload.get("thread_name")) or self.title
        elif event_type == "turn_context":
            self.cwd = string_value(payload.get("cwd")) or self.cwd
        elif event_type == "event_msg":
            self.consume_event(payload)
        elif event_type == "response_item":
            self.consume_response_item(payload)

    def consume_event(self, payload: dict[str, Any]) -> None:
        payload_type = payload.get("type")
        if payload_type == "task_started":
            self.open_turn(string_value(payload.get("turn_id")), "running", "Working")
        elif payload_type == "user_message" and self.has_open_turn:
            self.set_active_phase("running", "Working")
        elif payload_type == "agent_message" and (self.has_open_turn or self.may_infer_turn):
            self.set_active_phase("responding", assistant_message_detail(string_value(payload.get("phase"))))
        elif payload_type == "token_count":
            info = payload.get("info")
            usage = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(usage, dict):
                self.input_tokens = int_value(usage.get("input_tokens")) or self.input_tokens
                self.output_tokens = int_value(usage.get("output_tokens")) or self.output_tokens
                self.total_tokens = int_value(usage.get("total_tokens")) or self.total_tokens
        elif payload_type == "turn_aborted":
            self.close_turn(string_value(payload.get("turn_id")), "Interrupted")
        elif payload_type == "task_complete":
            self.close_turn(string_value(payload.get("turn_id")), "Complete")

    def consume_response_item(self, payload: dict[str, Any]) -> None:
        if not self.has_open_turn and not self.may_infer_turn:
            return
        payload_type = payload.get("type")
        if payload_type == "reasoning":
            self.set_active_phase("thinking", "Thinking")
        elif payload_type in {"function_call", "custom_tool_call"}:
            self.last_tool_name = string_value(payload.get("name"))
            self.set_active_phase("tool", codex_tool_detail(self.last_tool_name))
        elif payload_type in {"function_call_output", "custom_tool_call_output"}:
            self.set_active_phase("thinking", "Thinking")
        elif payload_type == "message":
            if payload.get("role") == "user":
                if self.has_open_turn:
                    self.set_active_phase("running", "Working")
                return
            self.set_active_phase("responding", assistant_message_detail(string_value(payload.get("phase"))))

    def open_turn(self, turn_id: str | None, phase: str, detail: str) -> None:
        self.has_open_turn = True
        if turn_id:
            self.active_turn_id = turn_id
        self.set_active_phase(phase, detail)

    def set_active_phase(self, phase: str, detail: str) -> None:
        self.has_open_turn = True
        self.phase = phase
        self.detail = detail

    def close_turn(self, turn_id: str | None, detail: str) -> None:
        if turn_id and self.active_turn_id and turn_id != self.active_turn_id:
            return
        self.has_open_turn = False
        self.may_infer_turn = False
        self.active_turn_id = None
        self.phase = "paused" if detail == "Interrupted" else "completed"
        self.detail = detail

    def snapshot(self) -> dict[str, Any]:
        clean_cwd = self.cwd.strip() if self.cwd else None
        visible_phase = self.phase
        visible_detail = self.detail if self.has_open_turn else ("Complete" if self.detail == "Idle" else self.detail)
        return {
            "session_id": self.session_id,
            "title": self.title,
            "cwd": clean_cwd,
            "project_name": project_name_from_path(clean_cwd),
            "phase": visible_phase,
            "detail": visible_detail,
            "last_tool_name": self.last_tool_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "updated_at": self.updated_at,
        }


class ClaudeSessionParser:
    def __init__(self, session_file: Path) -> None:
        self.session_file = session_file
        self.session_id: str | None = None
        self.cwd: str | None = None
        self.title: str | None = None
        self.updated_at: datetime | None = None
        self.phase = "paused"
        self.detail = "Complete"
        self.has_open_turn = False
        self.last_tool_name: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def consume(self, line: str) -> None:
        if len(line) > MAX_LINE_CHARS:
            return
        obj = json_object(line)
        if not obj:
            return

        self.session_id = string_value(obj.get("sessionId")) or string_value(obj.get("session_id")) or self.session_id
        self.cwd = string_value(obj.get("cwd")) or self.cwd

        timestamp = parse_date(obj.get("timestamp"))
        if timestamp:
            self.updated_at = max_date(self.updated_at, timestamp)

        event_type = obj.get("type")
        if event_type == "ai-title":
            self.title = string_value(obj.get("aiTitle")) or self.title
        elif event_type == "user":
            self.consume_user_message(obj)
        elif event_type == "assistant":
            self.consume_assistant_message(obj)
        elif event_type == "system" and obj.get("subtype") == "error":
            self.set_active_phase("failed", "Failed")

    def consume_user_message(self, obj: dict[str, Any]) -> None:
        if obj.get("isSidechain") is True:
            return
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if contains_content_type("tool_result", content) or obj.get("toolUseResult") is not None:
            self.set_active_phase("thinking", "Thinking")
        else:
            self.set_active_phase("running", "Working")

    def consume_assistant_message(self, obj: dict[str, Any]) -> None:
        if obj.get("isSidechain") is True:
            return
        message = obj.get("message")
        if not isinstance(message, dict):
            return

        self.consume_usage(message.get("usage"))
        content = message.get("content")
        stop_reason = message.get("stop_reason")
        tool_name = first_tool_name(content)

        if tool_name:
            self.last_tool_name = tool_name
            self.set_active_phase("tool", claude_tool_detail(tool_name))
        elif contains_content_type("thinking", content):
            self.set_active_phase("thinking", "Thinking")
        elif contains_text(content):
            self.set_active_phase("responding", "Writing response")

        if stop_reason == "end_turn" and not tool_name and contains_text(content):
            self.close_turn("Complete")

    def consume_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        input_tokens = int_value(usage.get("input_tokens")) or 0
        output_tokens = int_value(usage.get("output_tokens")) or 0
        if input_tokens > 0:
            self.input_tokens = input_tokens
        if output_tokens > 0:
            self.output_tokens = output_tokens
        if self.input_tokens + self.output_tokens > 0:
            self.total_tokens = self.input_tokens + self.output_tokens

    def set_active_phase(self, phase: str, detail: str) -> None:
        self.has_open_turn = True
        self.phase = phase
        self.detail = detail

    def close_turn(self, detail: str) -> None:
        self.has_open_turn = False
        self.phase = "completed"
        self.detail = detail

    def snapshot(self) -> dict[str, Any]:
        clean_cwd = self.cwd.strip() if self.cwd else None
        visible_phase = self.phase
        visible_detail = self.detail if self.has_open_turn else (self.detail or "Complete")
        return {
            "session_id": self.session_id,
            "title": self.title,
            "cwd": clean_cwd,
            "project_name": project_name_from_path(clean_cwd) or project_name_from_claude_path(self.session_file),
            "phase": visible_phase,
            "detail": visible_detail,
            "last_tool_name": self.last_tool_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "updated_at": self.updated_at,
        }


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME", "~/.claude")).expanduser()


def newest_jsonl(root: Path) -> Path:
    newest_path: Path | None = None
    newest_mtime = -1.0
    for path in root.rglob("*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime > newest_mtime:
            newest_mtime = stat.st_mtime
            newest_path = path
    if newest_path is None:
        raise FileNotFoundError(f"No session files found in {root}")
    return newest_path


def session_lines(path: Path) -> list[str]:
    head = head_lines(path)
    tail = tail_lines(path)
    if not head:
        return tail
    if not tail:
        return head
    return head + tail


def head_lines(path: Path, max_bytes: int = MAX_HEAD_BYTES) -> list[str]:
    with path.open("rb") as handle:
        data = handle.read(max_bytes)
    text = data.decode("utf-8", errors="ignore")
    return [line for line in text.splitlines() if line.strip()]


def tail_lines(path: Path, max_bytes: int = MAX_TAIL_BYTES) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        offset = max(0, size - max_bytes)
        handle.seek(offset)
        data = handle.read()
    text = data.decode("utf-8", errors="ignore")
    if offset > 0 and "\n" in text:
        text = text.split("\n", 1)[1]
    return [line for line in text.splitlines() if line.strip()]


def json_object(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def max_date(lhs: datetime | None, rhs: datetime) -> datetime:
    return rhs if lhs is None or rhs > lhs else lhs


def age_seconds(date: datetime) -> float:
    return max(0.0, (datetime.now(timezone.utc) - date.astimezone(timezone.utc)).total_seconds())


def string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def project_name_from_path(path: str | None) -> str:
    if not path:
        return "Project"
    return Path(path).expanduser().name or "Project"


def project_name_from_claude_path(path: Path) -> str:
    project_dir = path.parent.name.strip("-")
    parts = [part for part in project_dir.split("-") if part]
    return parts[-1] if parts else "Project"


def codex_session_id_from_path(path: Path) -> str:
    stem = path.stem
    prefix = "rollout-"
    timestamp_length = 20
    if not stem.startswith(prefix):
        return stem
    remainder = stem[len(prefix) :]
    if len(remainder) <= timestamp_length:
        return stem
    return remainder[timestamp_length:] or stem


def display_title(title: str | None, project_name: str, default_title: str) -> str:
    clean = (title or "").strip()
    if not clean or clean == default_title:
        return project_name
    return clean


def assistant_message_detail(phase: str | None) -> str:
    if phase == "final_answer":
        return "Writing final answer"
    if phase == "commentary":
        return "Writing update"
    return "Writing response"


def codex_tool_detail(tool_name: str | None) -> str:
    mapping = {
        "exec_command": "Running command",
        "apply_patch": "Editing files",
        "view_image": "Inspecting image",
        "imagegen": "Generating image",
        "update_plan": "Updating plan",
    }
    if not tool_name:
        return "Running tool"
    return mapping.get(tool_name, f"Running {tool_name}")


def claude_tool_detail(tool_name: str) -> str:
    mapping = {
        "Bash": "Running command",
        "Edit": "Editing files",
        "MultiEdit": "Editing files",
        "Write": "Editing files",
        "Read": "Reading files",
        "Glob": "Reading files",
        "Grep": "Reading files",
        "LS": "Reading files",
        "WebFetch": "Searching",
        "WebSearch": "Searching",
        "TodoWrite": "Updating plan",
    }
    return mapping.get(tool_name, f"Using {tool_name}")


def first_tool_name(content: Any) -> str | None:
    for item in content_items(content):
        if item.get("type") == "tool_use":
            return string_value(item.get("name"))
    return None


def contains_content_type(content_type: str, content: Any) -> bool:
    return any(item.get("type") == content_type for item in content_items(content))


def contains_text(content: Any) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    for item in content_items(content):
        if item.get("type") == "text" and string_value(item.get("text")):
            return True
    return False


def content_items(content: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict)]


def phase_title(phase: str) -> str:
    return {
        "running": "Working",
        "thinking": "Thinking",
        "tool": "Tool",
        "responding": "Responding",
        "completed": "Complete",
        "paused": "Paused",
        "failed": "Failed",
    }.get(phase, "Working")


def symbol_for_phase(phase: str) -> str:
    return {
        "running": "sparkles",
        "thinking": "lightbulb.fill",
        "tool": "wrench.and.screwdriver.fill",
        "responding": "text.bubble.fill",
        "completed": "checkmark",
        "paused": "pause.fill",
        "failed": "exclamationmark.triangle.fill",
    }.get(phase, "sparkles")


def compact_symbol_for_phase(phase: str) -> str:
    return {
        "running": "terminal.fill",
        "thinking": "lightbulb.fill",
        "tool": "hammer.fill",
        "responding": "text.bubble.fill",
        "completed": "checkmark.circle.fill",
        "paused": "pause.circle.fill",
        "failed": "exclamationmark.triangle.fill",
    }.get(phase, "terminal.fill")


def json_status_for_phase(phase: str) -> str:
    return {
        "running": "inProgress",
        "thinking": "inProgress",
        "tool": "inProgress",
        "responding": "inProgress",
        "completed": "success",
        "paused": "paused",
        "failed": "failed",
    }.get(phase, "inProgress")


def tint_for_phase(phase: str) -> str:
    return {
        "running": "teal",
        "thinking": "indigo",
        "tool": "orange",
        "responding": "green",
        "completed": "green",
        "paused": "gray",
        "failed": "red",
    }.get(phase, "teal")


def progress_value_for_phase(phase: str) -> float | None:
    if phase in {"completed", "failed"}:
        return 1.0
    return None


def format_count(value: int) -> str:
    return f"{value:,}"


def current_states() -> list[tuple[Source, AgentState]]:
    states: list[tuple[Source, AgentState]] = []
    for source in enabled_sources():
        state = load_latest_state(source)
        if state is not None:
            states.append((source, state))
    return states


def run_check() -> int:
    if not enabled_sources():
        print("No agent sources are enabled.")
        return 0

    for source, state in current_states():
        print(f"{source.title}: {state.phase} - {state.detail_text} - {state.project_text} active={state.is_active}")
    return 0


def run_demo_json() -> int:
    messages = [
        activity_message(source, state, "create")
        for source, state in current_states()
        if state.is_active
    ]
    payload: Any = messages[0] if len(messages) == 1 else messages
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return run_check()
    if "--demo-json" in sys.argv[1:]:
        return run_demo_json()
    return AgentsJSONPlugin().run()


if __name__ == "__main__":
    raise SystemExit(main())
