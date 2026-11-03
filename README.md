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

## Not here (yet)

Bridge features that are about bodies, not routing, and are the runtime's now or later: the human "stop" word in a
peer venue, the peer-turn budget, a guest venue's readers' cards, typing and the 👀 reaction, the channel notes and
the extension tick (the packages channel). `render` isn't declared: loom's generic render shows these conversations.

## Tests

    python3 -m unittest discover -s test -t .

`lib/loomvenue/common.py` is the same file in loom-slack.

AGPL-3.0-or-later.
