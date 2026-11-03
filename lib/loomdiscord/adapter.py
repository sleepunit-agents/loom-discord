"""loom-discord's poller: each agent's bot polls the server's channels and active threads (shuttle's Discord
bridge, ported: the same cursors, the same first sight, the same rules), routes each message (routing.py), and
either logs it (shadow) or hands it to loom's `deliver` (live).

One platform message is handled once per addressed agent (bridges.md, "Several bots see the same message"): a
message two bots both see, addressed to both, is two deliveries, and a message seen twice by one bot (a cursor
that didn't move, a restart) is one.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from loomvenue import common
from loomdiscord import routing

API = "https://discord.com/api/v10"
THREAD_FIRST_SIGHT_S = 3600     # a thread this young on first sight is read from its start
HANDLED_KEEP_S = 2 * 86400      # how long a handled (message, agent) is remembered
GUEST_DAILY_DEFAULT = 30        # a guest's deliveries a day, unless their entry says (daily_spawns)
ACK_EMOJI = "\U0001F440"       # 👀: a body took this message (shuttle's presence, 2026-09-16)


class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


class Discord:
    """Discord's REST API as one bot. Read-only here, but for `post` (live `send` only)."""

    def __init__(self, token, opener=urllib.request.urlopen):
        self.token, self.opener = token, opener

    def call(self, path, method="GET", body=None):
        req = urllib.request.Request(f"{API}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bot {self.token}",
                                              "User-Agent": "loom-discord (https://github.com/sleepunit-agents/loom-discord, 0.1)",
                                              "Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=20) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    after = float(json.loads(e.read() or b"{}").get("retry_after") or 5)
                except ValueError:
                    after = 5.0
                raise RateLimited(after) from None
            raise

    def post(self, channel_id, content):
        return self.call(f"/channels/{channel_id}/messages", "POST", {"content": content,
                                                                       "allowed_mentions": {"parse": ["users"]}})

    def react(self, channel_id, msg_id, add=True):
        emoji = urllib.parse.quote(ACK_EMOJI)
        return self.call(f"/channels/{channel_id}/messages/{msg_id}/reactions/{emoji}/@me", "PUT" if add else "DELETE")

    def typing(self, channel_id):
        return self.call(f"/channels/{channel_id}/typing", "POST")


def react(api, place, msg_id, add):
    """👀 on (or off) a message in a place: True when done, or when there's nothing left to do (it's gone)."""
    cid = str(place).partition(":")[2]
    if not (cid.isdigit() and str(msg_id).isdigit()):
        return True
    try:
        api.react(cid, msg_id, add)
        return True
    except urllib.error.HTTPError as e:
        return e.code in (403, 404)
    except (RateLimited, urllib.error.URLError, OSError, ValueError):
        return False


def typing(api, place):
    cid = str(place).partition(":")[2]
    if cid.isdigit():
        try:
            api.typing(cid)
        except (RateLimited, urllib.error.URLError, OSError, ValueError):
            pass


class Adapter:
    """The poll loop's state and one tick. `apis` maps agent to its Discord client; `views` gives an agent's
    routing.View (its routes and gates, freshly read); `sink(agent, msg, chan, hit, label)` delivers, or None in
    shadow; `shadow` is the ShadowLog."""

    def __init__(self, data_dir, apis, views, shadow, sink=None, now=time.time, presence=None):
        self.data_dir = Path(data_dir)
        self.state_file = self.data_dir / "state.json"
        self.apis, self.views, self.shadow, self.sink, self.now = apis, views, shadow, sink, now
        self.presence = presence or common.Presence(self.data_dir, now=now)
        self.state = common.load_json(self.state_file, {})
        for k in ("cursors", "handled", "guest_count", "parents", "peer_stopped", "acked"):
            self.state.setdefault(k, {})

    def save(self):
        common.save_json(self.state_file, self.state)

    # -------------------------------------------------------------- one agent's pass

    def channels(self, agent, view):
        api = self.apis[agent]
        chans = [c for c in api.call(f"/guilds/{view.guild}/channels") or []
                 if c.get("type") == 0 and view.polled(c.get("id"))]
        out = [{"id": c["id"], "name": c.get("name", "?")} for c in chans]
        try:
            data = api.call(f"/guilds/{view.guild}/threads/active") or {}
        except urllib.error.HTTPError as e:
            common.log(f"{agent}: threads/active: HTTP {e.code}")
            data = {}
        for t in data.get("threads", []):
            if t.get("type") in (11, 12) and view.polled(t.get("parent_id")):
                out.append({"id": t["id"], "name": t.get("name", "?"), "parent_id": t.get("parent_id"), "is_thread": True})
                # Which channel a thread is under, for `send --describe` (a thread goes by its parent).
                self.state["parents"][str(t["id"])] = str(t.get("parent_id"))
        return out

    # -------------------------------------------------------------- the stop word, and presence

    def stopped(self, agent, view, msg, chan, place):
        """A person said the stop word here: the runtime hears it (its next presence call answers stop) and ends this
        agent's body; in a peer venue, peer turns wait until a person says something else (shuttle's t-591). Live,
        one line says so."""
        self.presence.stop(agent, place, msg["id"])
        if view.entry(chan).get("peer"):
            self.state["peer_stopped"].setdefault(agent, {})[place] = True
        common.log(f"{agent}: the stop word in {place}")
        if self.sink is not None:
            try:
                peer = " I won't take peer turns here until a person says something that isn't stop." if view.entry(chan).get("peer") else ""
                self.apis[agent].post(chan["id"], f"Stopped here.{peer}")
            except Exception as e:  # noqa: BLE001 - best effort
                common.log(f"{agent}: couldn't say it stopped in {place}: {type(e).__name__}")

    def show(self):
        """Live: 👀 on what each working body took, typing while it owes a reply (common.Presence.show)."""
        self.presence.show(self.state["acked"], self.apis, react, typing)
        self.save()

    def handled(self, msg_id, agent):
        return agent in self.state["handled"].get(str(msg_id), {}).get("agents", [])

    def note_handled(self, msg_id, agent):
        h = self.state["handled"].setdefault(str(msg_id), {"at": self.now(), "agents": []})
        if agent not in h["agents"]:
            h["agents"].append(agent)

    def prune(self):
        cut = self.now() - HANDLED_KEEP_S
        self.state["handled"] = {k: v for k, v in self.state["handled"].items() if v.get("at", 0) >= cut}
        day = time.strftime("%Y-%m-%d", time.gmtime(self.now()))
        self.state["guest_count"] = {k: v for k, v in self.state["guest_count"].items() if k.startswith(day)}

    def guest_over_cap(self, view, msg, reason):
        """A guest's daily cap (shuttle's, t-693): live only, a guest's own message (not a peer's) spends one."""
        if reason == "peer":
            return False
        uid = str((msg.get("author") or {}).get("id"))
        rec = view.guests.get(uid)
        if not rec:
            return False
        key = f"{time.strftime('%Y-%m-%d', time.gmtime(self.now()))}:{view.agent}:{uid}"
        n = self.state["guest_count"].get(key, 0)
        if n >= int(rec.get("daily_spawns", GUEST_DAILY_DEFAULT)):
            common.log(f"{view.agent}: a guest's daily cap reached; not delivered")
            return True
        self.state["guest_count"][key] = n + 1
        return False

    def agent_pass(self, agent):
        view = self.views(agent)
        if view is None or not view.bot or not view.guild:
            common.log(f"{agent}: no route map, gates or bot id; nothing routes for it this tick")
            return 0
        api = self.apis[agent]
        cursors = self.state["cursors"].setdefault(agent, {})
        chans = self.channels(agent, view)
        names = {c["id"]: c["name"] for c in chans if not c.get("is_thread")}
        routed = 0
        for ch in chans:
            cid = ch["id"]
            cursor = cursors.get(cid)
            if cursor is None:
                if ch.get("is_thread") and snowflake_age_s(cid, self.now()) < THREAD_FIRST_SIGHT_S:
                    cursors[cid] = cursor = cid
                else:
                    latest = api.call(f"/channels/{cid}/messages?limit=1") or []
                    cursors[cid] = latest[0]["id"] if latest else "0"
                    continue
            try:
                msgs = api.call(f"/channels/{cid}/messages?after={cursor}&limit=100") or []
            except urllib.error.HTTPError as e:
                common.log(f"{agent}: poll {cid}: HTTP {e.code}")
                continue
            if not msgs:
                continue
            msgs.sort(key=lambda m: int(m["id"]))
            stop_at = None
            for m in msgs:
                place = routing.place_of(ch)
                if not self.handled(m["id"], agent) and view.is_stop(m, ch) and (
                        view.entry(ch).get("peer") or self.presence.working(agent, place)):
                    self.stopped(agent, view, m, ch, place)
                    self.note_handled(m["id"], agent)
                    continue
                if view.human_here(m, ch):
                    self.state["peer_stopped"].get(agent, {}).pop(place, None)   # a person's word lifts a stop
                why = view.reason(m, ch)
                if not why or self.handled(m["id"], agent):
                    continue
                if why == "peer" and self.state["peer_stopped"].get(agent, {}).get(place):
                    self.note_handled(m["id"], agent)
                    continue
                if self.sink is None:
                    self.shadow.routed(m["id"], agent, place)
                    self.note_handled(m["id"], agent)
                    routed += 1
                    continue
                if self.guest_over_cap(view, m, why):
                    self.note_handled(m["id"], agent)
                    continue
                ok = self.sink(agent, m, ch, view.sender(m), routing.label_of(ch, names))
                if not ok:
                    stop_at = m["id"]       # loom didn't take it: from here, next tick
                    break
                self.note_handled(m["id"], agent)
                routed += 1
            if stop_at is None:
                cursors[cid] = msgs[-1]["id"]
            else:
                before = [m["id"] for m in msgs if int(m["id"]) < int(stop_at)]
                if before:
                    cursors[cid] = before[-1]
        return routed

    def tick(self):
        self.prune()
        total = 0
        for agent in sorted(self.apis):
            try:
                total += self.agent_pass(agent)
            except RateLimited as e:
                common.log(f"{agent}: {e}; the rest of its pass waits for the next tick")
            except (urllib.error.URLError, OSError, ValueError) as e:
                common.log(f"{agent}: tick: {type(e).__name__}: {getattr(e, 'code', '') or e}")
        self.save()
        return total


def snowflake_age_s(sid, now):
    try:
        return now - (((int(sid) >> 22) + 1420070400000) / 1000)
    except (TypeError, ValueError):
        return 10**9


def snowflake_iso(sid):
    try:
        return common.iso(((int(sid) >> 22) + 1420070400000) / 1000)
    except (TypeError, ValueError):
        return common.iso(time.time())
