"""Which agent a Discord message is for (bridges.md, "Routing"), ported from shuttle's adapters/discord.py.

Pure: given one agent's view (its bot, its route map, its gates), say why a message wakes that agent, or None.

  1. A DM is for the agent whose bot received it (a polling bot never sees DMs: Discord gives a bot its DMs only
     over the gateway, so this adapter, like the bridge it replaces, polls the server's channels and threads).
  2. In a shared channel a mention decides: an explicit <@bot> (or the bot's own managed role) is that agent's,
     and a message addressed only to a peer isn't this one's.
  3. No mention goes to the channel's primary, if it has one (the route map's `primary`).
  4. A peer bot or a webhook peer wakes an agent only in a peer venue, with an explicit mention (or any post from
     the paired webhook in a pair channel).
  5. The gates: tier 2 and up anywhere, a guest only inside its venues, a stranger nowhere.

The route map is the household's, assembled for one agent (shuttle's `routes --agent`): `guild`, `bots`
{agent: bot user id}, `bot_roles`, `channels` and `threads` {id: {primary, peer, pair, guest_venue}},
`webhook_peers` {webhook id: name}, `ignore` and `only` (channel ids), `guests`.
"""
import re

from loomvenue import common

MENTION = re.compile(r"<@!?(\d+)>")
ROLE_MENTION = re.compile(r"<@&(\d+)>")
ANY_MENTION = re.compile(r"<@[!&]?\d+>")


class View:
    """One agent's view of the server: its bot user id, its route map and its gates."""

    def __init__(self, agent, routes, gates):
        self.agent = agent
        self.routes = routes if isinstance(routes, dict) else {}
        self.bot = str((self.routes.get("bots") or {}).get(agent) or "")
        self.guild = self.routes.get("guild")
        self.who = common.index(gates, "discord") if isinstance(gates, dict) else {}
        self.webhook_peers = {str(k): v for k, v in (self.routes.get("webhook_peers") or {}).items()
                              if not str(k).startswith("_") and v}
        self.peers = {str(v) for k, v in (self.routes.get("bots") or {}).items() if k != agent and v} | set(self.webhook_peers)
        self.bot_roles = {}
        bots = self.routes.get("bots") or {}
        for key, rids in (self.routes.get("bot_roles") or {}).items():
            uid = bots.get(key)
            if uid:
                for rid in (rids if isinstance(rids, list) else [rids]):
                    self.bot_roles[str(rid)] = str(uid)
        self.ignore = {str(x) for x in (self.routes.get("ignore") or {})}
        self.only = {str(x) for x in (self.routes.get("only") or ())}
        self.guests = {uid: rec for uid, (_, rec) in self.who.items() if not rec["agent"] and rec.get("tier") == 1}

    def polled(self, cid):
        """Does this agent read channel `cid` (a thread goes by its parent)?"""
        cid = str(cid)
        return cid not in self.ignore and (not self.only or cid in self.only)

    def entry(self, chan):
        """The effective route for a channel or thread: its own thread entry, else its parent's, else {}."""
        if chan.get("is_thread"):
            ent = (self.routes.get("threads") or {}).get(chan["id"])
            if ent is not None:
                return ent
            return (self.routes.get("channels") or {}).get(chan.get("parent_id"), {})
        return (self.routes.get("channels") or {}).get(chan["id"], {})

    def human_allowed(self, uid, venue):
        return common.may_wake(self.who.get(str(uid), (None, None))[1], venue)[0]

    def explicit_mentions(self, msg):
        """User ids written as <@id> and resolved by Discord (not the automatic reply-ping), plus a bot's own
        managed role, resolved to that bot; never @everyone or another role."""
        resolved = {u.get("id") for u in msg.get("mentions", [])}
        content = msg.get("content", "")
        ids = {m for m in MENTION.findall(content) if m in resolved}
        if self.bot_roles:
            pinged = {str(r) for r in msg.get("mention_roles", [])}
            ids |= {self.bot_roles[r] for r in ROLE_MENTION.findall(content) if r in pinged and r in self.bot_roles}
        return ids

    def reason(self, msg, chan):
        """'human' | 'human-mention' | 'peer' | None: why this message wakes this agent here."""
        entry = self.entry(chan)
        venue = venue_of(chan)
        author = msg.get("author", {})
        aid = author.get("id")
        if not self.bot or aid == self.bot:
            return None
        wh = msg.get("webhook_id")
        if wh is not None and (wh not in self.webhook_peers or aid != wh):
            return None
        if msg.get("type") not in (0, 19):      # DEFAULT and REPLY
            return None
        if not author.get("bot", False) and not self.human_allowed(aid, venue):
            return None                          # a stranger, or a guest outside its venue
        explicit = self.explicit_mentions(msg)
        if author.get("bot", False):
            if aid not in self.peers:
                return None
            if entry.get("peer") and self.bot in explicit:
                return "peer"
            if (entry.get("peer") and entry.get("primary") == self.agent and entry.get("pair")
                    and self.webhook_peers.get(aid) == entry["pair"]):
                return "peer"
            return None
        if self.bot in explicit:
            return "human-mention"
        if explicit & self.peers:
            return None                          # addressed to a peer only
        return "human" if entry.get("primary") == self.agent else None

    def sender(self, msg):
        """The gates' entry for a message's author, or None."""
        return self.who.get(str((msg.get("author") or {}).get("id")))


def venue_of(chan):
    """What a guest's `venues` name: a thread goes by its parent channel."""
    return chan.get("parent_id") if chan.get("is_thread") else chan.get("id")


def place_of(chan):
    """The conversation's place (conversations.md): a channel, or a thread, which is its own conversation."""
    return f"{'thread' if chan.get('is_thread') else 'channel'}:{chan.get('id')}"


def label_of(chan, names):
    """The place's display name. Never a thread's own name: Discord defaults it to the starter message's text."""
    if chan.get("is_thread"):
        parent = names.get(chan.get("parent_id"))
        return f"#{parent} thread" if parent else "thread"
    return f"#{chan.get('name') or chan.get('id')}"


def text_of(msg):
    content = msg.get("content", "")
    for att in msg.get("attachments", []) or []:
        content += f" [attachment: {att.get('filename')} {att.get('url')}]"
    return content
