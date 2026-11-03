# loom-discord

loom's Discord venue adapter (loom's `docs/specs/agent-runtime.md`, "The sources"; `conversations.md`, "Venues";
`bridges.md`). A thin piece: it holds each agent's own Discord bot (one bot per agent per platform), routes each
message to an agent, and hands it to loom's `deliver`. The runtime gets the conversation a body; when the agent
answers, the runtime runs this piece's `send`, which posts as that agent's bot. It never starts a body and never
names a harness (agent-runtime.md, test 1: `test/test_contract.py` fails if it does). Removing it leaves every
conversation in loom.

```
loom pieces install --from github:sleepunit-agents/loom-discord#<commit>
loom pieces set discord 'DISCORD_BOTS={"kit": "kit-discord-token"}'
loom discord status
```

## Routing

Each agent's bot polls the server's text channels and active threads (as the bridge it replaces did: a bot gets DMs
only over the gateway, so there are no Discord DMs here yet). A message is the agent's when (`lib/loomdiscord/routing.py`):

1. it mentions the agent's bot, explicitly (`<@id>`, resolved by Discord) or by the bot's own managed role. A
   message addressed only to another agent's bot isn't this one's;
2. it mentions nobody, and the channel's primary (the route map) is this agent;
3. it's a peer bot's or a listed webhook peer's, in a peer venue, with an explicit mention (or, in a pair channel,
   any post from the paired webhook);
4. and the gates let its author wake the agent there: tier 2 and up anywhere, a guest (tier 1) only in its venues,
   a stranger nowhere.

**Once per addressed agent:** one platform message two bots see, addressed to both, is two deliveries; a message
one bot sees twice is one. In live mode a guest has a daily cap (`daily_spawns` in their gate entry, 30 by default).

**Where the rules come from.** The gates are the runtime's (`loom runtime gates people --agent a --json`). The route
map (`guild`, `bots`, `bot_roles`, `channels`/`threads` with `primary`, `peer`, `pair`, `guest_venue`,
`webhook_peers`, `ignore`, `only`) is read with `DISCORD_ROUTES_COMMAND`, by default shuttle's
`loom shuttle routes --agent a --json`, until the runtime holds the routes too. Either one unreadable fails closed:
nothing routes for that agent until it answers.

## The delivery

```json
{"id": "<agent>:<message id>", "agent": "kit", "venue": "discord", "place": "channel:<id>" | "thread:<id>",
 "label": "#general" | "#general thread", "from": {"kind": "person", "slug": "robin"} | {"kind": "unknown"},
 "kind": "message", "at": "<the message's time>", "text": "<its content and attachment links>"}
```

`from` is a person card's slug when the gates resolve the author to a person, else `{kind: unknown}` (a peer bot,
a webhook). A thread is its own place, and is never labelled with its own name (Discord defaults that to the
starter message's text). The text goes only to `deliver`, which puts it in loom's audit log; the turn in loom is
metadata only. This piece logs ids, counts and reasons, never text or a token.

## Shadow mode

`DISCORD_MODE=shadow` (the default) receives and routes, delivers nothing and posts nothing (`send` answers
`{ok: false}`), and writes one line per message it would deliver to `<DISCORD_DATA>/shadow-routes.jsonl`:
`{at, platform, id, agent, place}`, the same line shuttle's bridges write. Then:

```
loom-discord compare --start 2026-11-03T00:00:00Z --adapter '<data>/shadow-routes.jsonl' --bridge '<bridge state>/shadow-routes.jsonl'
```

matches the two by message id: every message first seen in the window (less 10 minutes at each end) must have the
same agents and places on both sides, and there must be at least 20. Exit 0 agree, 1 disagree, 3 too few.

## Send

`loom-discord send --place <place> --agent <agent>`, the text on stdin: posted as that agent's bot, split under
Discord's 2000 characters, answering `{ok, id?}` or `{ok: false, reason}` (no bot for that agent, a secret the policy
doesn't allow, shadow mode). Run by anything but loom's piece dispatch (the runtime runs it by its bin name), it
goes through `loom discord send …` so the piece's own settings apply.

## Bot tokens

`DISCORD_BOTS` names, for each agent, the secret its token comes from. The secrets piece decides: only when
`loom secrets may <agent> <name>` answers `allowed` does this piece read the value (host-side, `get --reveal`). The
value stays in the process, never in argv, a log or a file.

## Settings

| Name | What |
|---|---|
| `DISCORD_MODE` | `shadow` (default) or `live` |
| `DISCORD_BOTS` | `{"agent": "secret name"}` |
| `DISCORD_DATA` | cursors and the shadow log (default `${LOOM_PIECE_HOME}/data`) |
| `DISCORD_POLL_S` | seconds between polls (30) |
| `DISCORD_TOKEN_FILE` | live: a piece token of this piece's, to deliver with (`loom token create --piece discord/<name>`) |
| `DISCORD_LOOM_URL` | loom's address (`http://127.0.0.1:8787`) |
| `DISCORD_ROUTES_COMMAND`, `DISCORD_GATES_COMMAND` | JSON argvs printing `{"doc": …}`, `{agent}` filled in |

## What the runtime asks of a place

Before a body starts, the runtime runs the declared send argv with `--describe` (it posts nothing, in shadow too):

```json
{"ok": true, "guest": false, "peer": true, "venue": "<channel id>", "readers": [], "notes": ["<route map key>"], "pair": "<name>"}
```

- **A guest venue** is one the route map marks `guest_venue`, or one a guest (a tier-1 gate entry) has in its `venues`,
  because the guest reads every reply there. Its `readers` are the route map's `readers` and those guests. The
  runtime then gives the body the agent's guest floor, the readers' cards and the narrowed tools, or no body.
- **A thread** goes by its parent channel, as the poller last saw it. A thread it never saw isn't described (`ok:
  false`), so no body starts there.
- **`notes`** are the route map's other keys that list the channel, such as a set of channels with rules of their own.
  The agent's policy maps a note's name to its brief file.
- Unreadable gates or routes answer `ok: false`.

## A body at work, and the stop word

The runtime runs `--status working --message <delivery id>` when a message reaches a body, again every 15 s while it
works, and `--status done` when its turn is over. That call only writes the piece's data dir; the poller, live, shows
it between polls every 8 s: 👀 on each message the body took, and typing while it owes a reply. 👀 comes off once the
agent's `send` posts there after it (the reply is the acknowledgment) or the body is done.

**The stop word:** a message that's only "stop" or "cancel" (its mentions aside), from a person the gates let wake the
agent there, stops the agent's body in that place when one is working there or it's a peer venue. It isn't delivered.
The runtime hears it on its next `--status` (`{ok: true, stop: true}`) and ends the body; live, one line says so. In a
peer venue, peer turns then wait until a person says something else.

## Not here (yet)

The peer-turn budget, and the extension tick (the packages channel). `render` isn't declared: loom's generic render
shows these conversations.

## Tests

    python3 -m unittest discover -s test -t .

`lib/loomvenue/common.py` is the same file in loom-slack.

AGPL-3.0-or-later.
