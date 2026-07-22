"""Use case: a research assistant that remembers across conversations.

Each invocation of this script is a FRESH operating-system process. It connects
to the real mcpstate flagship MCP server (in-memory, so no banner noise) and
calls the actual tools an agent would call. Because nothing is held in memory
between runs, the fact that state survives from one command to the next is a
genuine proof of durability — the whole point of mcpstate.

Run it as a story:

    python3 examples/research_assistant.py start
    python3 examples/research_assistant.py source "https://developer.arm.com/..."
    python3 examples/research_assistant.py source "https://aws.amazon.com/ec2/graviton/"
    python3 examples/research_assistant.py resume     # a NEW conversation
    python3 examples/research_assistant.py conflict    # two devices at once
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# A shared on-disk backend + a file that stands in for the model "remembering"
# the handle it was given. Both are configurable via env for the capture run.
DEMO_DIR = Path(os.environ.get("MCPSTATE_DEMO_DIR", ".demo"))
DEMO_DIR.mkdir(exist_ok=True)
HANDLE_FILE = DEMO_DIR / "handle.txt"
os.environ.setdefault("MCPSTATE_BACKEND", f"sqlite:///{DEMO_DIR / 'assistant.db'}")
os.environ.setdefault("MCPSTATE_USER", "varma")

TOPIC = "Migrating our payments API from x86 to ARM64"

from fastmcp import Client  # noqa: E402  (import after env is set)

import mcpstate.server as server  # noqa: E402


def rule(label: str) -> None:
    print(f"\n\033[2m── {label} " + "─" * max(0, 62 - len(label)) + "\033[0m")


def you(text: str) -> None:
    print(f"  \033[1myou\033[0m   {text}")


def agent(text: str) -> None:
    print(f"  agent {text}")


def tool(name: str, ok: bool = True) -> None:
    mark = "\033[32mok\033[0m" if ok else "\033[31m!!\033[0m"
    print(f"        {mark} {name}")


async def call(name: str, **args):
    async with Client(server.mcp) as client:
        return (await client.call_tool(name, args)).data


def save_handle(h: str) -> None:
    HANDLE_FILE.write_text(h)


def load_handle() -> str:
    return HANDLE_FILE.read_text().strip()


def as_device(label: str) -> None:
    # The flagship tools resolve the writer per call from MCPSTATE_WRITER, so
    # setting it here labels who is writing in the freshness metadata.
    os.environ["MCPSTATE_WRITER"] = label


async def start() -> None:
    as_device("laptop")
    rule("Conversation 1  ·  laptop, Monday morning")
    you(f'"Help me research: {TOPIC}."')
    agent("I'll keep this research in durable state so we can pick it up later.")
    res = await call("state_save", kind="research",
                     state={"topic": TOPIC, "sources": [], "notes": "just started"})
    save_handle(res["handle"])
    tool(f'state_save  ->  handle {res["handle"]}  (version {res["version"]})')
    agent(f"Started. Your research handle is {res['handle']}.")


async def source(url: str) -> None:
    as_device("laptop")
    h = load_handle()
    rule("Conversation 1  ·  same session")
    you(f'"Add this source: {url}"')
    res = await call("state_patch", handle=h,
                     ops=[{"op": "append", "path": "sources", "value": url}])
    tool(f'state_patch append  ->  {len(res["state"]["sources"])} sources (version {res["version"]})')
    agent(f"Saved. You now have {len(res['state']['sources'])} source(s) collected.")


async def resume() -> None:
    as_device("phone")
    h = load_handle()
    rule("Conversation 2  ·  a NEW chat, Tuesday  (nothing in memory)")
    you('"What was I working on?"')
    listing = await call("state_list", kind="research")
    info = listing["handles"][0]
    tool(f'state_list  ->  1 research session, last touched by "{info["last_writer"]}"')
    agent(f'You have a research session: "{TOPIC}".')
    you('"Great, let\'s continue."')
    loaded = await call("state_load", handle=h)
    tool(f'state_load  ->  version {loaded["version"]}')
    agent("Here is where we left off:")
    print(f"        topic   {loaded['state']['topic']}")
    for i, s in enumerate(loaded["state"]["sources"], 1):
        print(f"        source {i} {s}")
    print("\n  \033[32mThe state followed you into a brand-new conversation.\033[0m")


async def conflict() -> None:
    h = load_handle()
    rule("Two devices at once  ·  laptop + phone editing the same research")
    as_device("laptop")
    loaded = await call("state_load", handle=h)
    v = loaded["version"]
    you("(laptop) you read the research at version %d" % v)
    agent("(phone) meanwhile, your phone adds a note and saves first...")
    as_device("phone")
    phone_state = {**loaded["state"], "notes": "phone: Graviton pricing looks great"}
    await call("state_save", kind="research", handle=h, state=phone_state, expect_version=v)
    tool("phone state_save  ->  wins, version %d" % (v + 1))
    agent("(laptop) now the laptop tries to save its own edit at the old version...")
    as_device("laptop")
    laptop_state = {**loaded["state"], "notes": "laptop: benchmark ARM64 first"}
    res = await call("state_save", kind="research", handle=h, state=laptop_state, expect_version=v)
    tool(f'laptop state_save  ->  {res["error"]["code"]}', ok=False)
    agent("mcpstate handed the laptop the phone's current state to merge, not a silent clobber:")
    current = res["error"]["current"]
    print(f'        current notes: "{current["state"]["notes"]}"  (by {current["last_writer"]})')
    agent("(laptop) the agent merges both intents and re-saves at the new version...")
    merged = {**current["state"], "notes": current["state"]["notes"]
              + " + benchmark ARM64 first"}
    ok = await call("state_save", kind="research", handle=h, state=merged,
                    expect_version=current["version"])
    tool(f'laptop state_save  ->  merged, version {ok["version"]}')
    print("\n  \033[32mNo write was lost. The conflict became a merge the agent could reason about.\033[0m")


ACTIONS = {"start": start, "resume": resume, "conflict": conflict}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    action = sys.argv[1]
    if action == "source":
        asyncio.run(source(sys.argv[2]))
    elif action in ACTIONS:
        asyncio.run(ACTIONS[action]())
    else:
        print(f"unknown action {action!r}; try: start | source <url> | resume | conflict")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
