"""Render a new standalone Telegram DM config, without credentials or deployment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .file_io import write_exclusive_bytes
except ImportError:
    from file_io import write_exclusive_bytes

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates/telegram-dm-standalone.config.yaml"
)


def render_dm_config(user_id: str, chat_id: str) -> str:
    if (
        not isinstance(user_id, str)
        or not user_id.isascii()
        or not user_id.isdecimal()
        or not 0 < int(user_id) <= 2**63 - 1
        or str(int(user_id)) != user_id
        or chat_id != user_id
    ):
        raise ValueError("dm_identity_invalid")
    return (
        TEMPLATE.read_text()
        .replace("__PERMITTED_DM_USER_ID__", user_id)
        .replace("__PERMITTED_DM_CHAT_ID__", chat_id)
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rendered = render_dm_config(args.user_id, args.chat_id)
        write_exclusive_bytes(args.output.resolve(), rendered.encode())
    except (ValueError, OSError):
        print(json.dumps({"status": "render_failed", "applied": False}))
        return 2
    print(
        json.dumps(
            {
                "status": "rendered",
                "token_written": False,
                "applied": False,
                "messages_sent": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
