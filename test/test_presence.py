"""What the runtime asks of a place (`send --describe`), what it says of a body at work (`send --status`), and what
the adapter does with that: 👀 and typing while a body works, off once it posts or is done; the stop word stops it
(t-1756)."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from loomdiscord import adapter, routing
from loomvenue import common
from test.fixtures import GATES, ROUTES, msg
from test.test_send import cli


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Doc:
    def __init__(self, doc):
        self._doc = doc

    def doc(self):
        return self._doc


class Bot:
    """One bot: reads its channels, and records each post, reaction and typing pulse."""

    def __init__(self, messages, threads=()):
        self.messages, self.threads, self.posts, self.reacts, self.typed = messages, list(threads), [], [], []

    def call(self, path, method="GET", body=None):
        if path.endswith("/channels"):
            return [{"id": c, "name": f"c{c}", "type": 0} for c in ("30", "31", "32")]
        if path.endswith("/threads/active"):
            return {"threads": self.threads}
        cid = path.split("/")[2]
        msgs = self.messages.get(cid, [])
        if "limit=1" in path and "after" not in path:
            return msgs[-1:] if msgs else []
        after = int(path.split("after=")[1].split("&")[0])
        return [m for m in reversed(msgs) if int(m["id"]) > after]

    def post(self, cid, text):
        self.posts.append((cid, text))
        return {"id": "900"}

    def react(self, cid, mid, add=True):
        self.reacts.append((cid, mid, add))

    def typing(self, cid):
        self.typed.append(cid)


def answer_of(cfg, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.send(cfg, argv, stdin=io.StringIO(""))
    return json.loads(out.getvalue())


class Describe(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="loom-discord-p-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cfg = cli.config({"DISCORD_BOTS": '{"kit": "kit-discord-token"}', "DISCORD_DATA": str(self.dir)})
        routes = dict(ROUTES, onterris_channels={"30": "pond"}, packages_channel="32",
                      channels=dict(ROUTES["channels"], **{"34": {"primary": "kit", "guest_venue": True, "readers": ["sam"]}}))
        self.docs = (Doc(routes), Doc(GATES))

    def about(self, place):
        return cli.describe(self.cfg, "kit", place, docs=self.docs)

    def test_a_guest_venue_by_the_route_map_or_by_a_guests_own_venues(self):
        self.assertEqual(self.about("channel:34"), {"ok": True, "guest": True, "peer": False, "venue": "34", "readers": ["sam"], "notes": []})
        # Kim (tier 1) may wake kit in 31: a guest's venue is a guest venue, Kim its reader.
        self.assertEqual(self.about("channel:31")["guest"], True)
        self.assertEqual(self.about("channel:31")["readers"], ["kim"])
        plain = self.about("channel:30")
        self.assertEqual((plain["guest"], plain["readers"], plain["notes"]), (False, [], ["onterris_channels"]))

    def test_a_peer_venue_and_its_pair(self):
        a = self.about("channel:33")
        self.assertEqual((a["peer"], a["pair"]), (True, "Hooky"))
        self.assertEqual(self.about("channel:32")["notes"], ["packages_channel"])

    def test_a_thread_goes_by_its_parent_and_an_unknown_one_isnt_described(self):
        self.assertEqual(self.about("thread:77")["ok"], False)
        common.save_json(self.dir / "state.json", {"parents": {"77": "31"}})
        a = self.about("thread:77")
        self.assertEqual((a["ok"], a["guest"], a["venue"], a["readers"]), (True, True, "31", ["kim"]))

    def test_unreadable_gates_or_routes_describe_nothing(self):
        self.assertEqual(cli.describe(self.cfg, "kit", "channel:30", docs=(Doc(None), Doc(GATES)))["ok"], False)
        self.assertEqual(cli.describe(self.cfg, "bolt", "channel:30", docs=self.docs)["ok"], False)

    def test_describe_and_status_work_in_shadow_and_post_nothing(self):
        self.assertEqual(self.cfg["mode"], "shadow")
        a = answer_of(self.cfg, ["--place", "channel:30", "--agent", "kit", "--status", "working", "--message", "kit:101"])
        self.assertEqual(a, {"ok": True})
        self.assertTrue(common.Presence(self.dir).working("kit", "channel:30"))
        self.assertEqual(answer_of(self.cfg, ["--place", "channel:30", "--agent", "kit", "--status", "busy"])["ok"], False)


class Presence(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="loom-discord-p-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.clock = Clock()
        self.msgs = {"30": [msg(100, "11", "old")], "32": [msg(200, "11", "old")]}
        self.bot = Bot(self.msgs)
        self.presence = common.Presence(self.dir, now=self.clock)
        views = lambda agent: routing.View(agent, ROUTES, GATES)  # noqa: E731
        self.a = adapter.Adapter(self.dir, {"kit": self.bot}, views, common.ShadowLog(self.dir, "discord"),
                                 sink=lambda *x: True, now=self.clock, presence=self.presence)

    def test_while_a_body_works_its_message_has_eyes_and_the_place_types_until_it_posts(self):
        self.presence.status("kit", "channel:30", "working", ["kit:101"])
        self.a.show()
        self.assertEqual(self.bot.reacts, [("30", "101", True)])
        self.assertEqual(self.bot.typed, ["30"])
        self.a.show()   # again: no second 👀, another typing pulse
        self.assertEqual((len(self.bot.reacts), len(self.bot.typed)), (1, 2))
        # The body posts (its send): the reply is the acknowledgment. 👀 off, no more typing.
        self.clock.t += 5
        self.presence.posted("kit", "channel:30")
        self.a.show()
        self.assertEqual(self.bot.reacts[-1], ("30", "101", False))
        self.assertEqual(len(self.bot.typed), 2)
        # A follow-up it took: 👀 on that one, typing again.
        self.clock.t += 5
        self.presence.status("kit", "channel:30", "working", ["kit:102"])
        self.a.show()
        self.assertEqual(self.bot.reacts[-1], ("30", "102", True))
        self.assertEqual(len(self.bot.typed), 3)
        # Done (its turn over) without posting: 👀 off, and the place forgotten.
        self.presence.status("kit", "channel:30", "done")
        self.a.show()
        self.assertEqual(self.bot.reacts[-1], ("30", "102", False))
        self.assertEqual(self.presence.all(), [])
        self.assertEqual(len(self.bot.typed), 3)

    def test_a_body_the_runtime_stopped_speaking_of_is_shown_no_more(self):
        self.presence.status("kit", "channel:30", "working", ["kit:101"])
        self.a.show()
        self.clock.t += common.STATUS_FRESH_S + 1
        self.a.show()
        self.assertEqual(self.bot.reacts, [("30", "101", True), ("30", "101", False)])
        self.assertEqual(self.presence.all(), [])

    def test_the_stop_word_where_a_body_works_stops_it(self):
        self.a.tick()                      # first sight: the cursors
        self.presence.status("kit", "channel:30", "working", ["kit:101"])
        self.clock.t += 1
        self.msgs["30"].append(msg(102, "11", "<@19> stop!", mentions=["19"]))
        self.a.tick()
        self.assertEqual(self.presence.status("kit", "channel:30", "working"), {"ok": True, "stop": True})
        self.assertEqual(self.bot.posts, [("30", "Stopped here.")])
        self.assertTrue(self.a.handled("102", "kit"), "the stop isn't a summons")
        # Done: the stop is spent; the next body there isn't stopped by it.
        self.presence.status("kit", "channel:30", "done")
        self.clock.t += 1
        self.assertEqual(self.presence.status("kit", "channel:30", "working", ["kit:103"]), {"ok": True})

    def test_the_stop_word_from_a_stranger_or_where_nothing_works_is_just_a_message(self):
        self.a.tick()
        self.msgs["30"].append(msg(102, "99", "stop"))      # a stranger
        self.msgs["30"].append(msg(103, "11", "stop"))      # the owner, but no body works in 30
        self.a.tick()
        self.assertEqual(self.bot.posts, [])
        self.assertEqual(list((self.dir / "stops").glob("*/*")) if (self.dir / "stops").exists() else [], [])

    def test_in_a_peer_venue_a_stop_holds_peer_turns_until_a_person_speaks(self):
        self.a.tick()
        took = []
        self.a.sink = lambda agent, m, ch, hit, label: took.append(m["id"]) or True
        routes = dict(ROUTES, channels=dict(ROUTES["channels"], **{"32": {"primary": "kit", "peer": True}}))
        self.a.views = lambda agent: routing.View(agent, routes, GATES)
        self.msgs["32"].append(msg(201, "11", "cancel."))
        self.msgs["32"].append(msg(202, "13", "<@19> your turn", bot=True, mentions=["19"]))
        self.a.tick()
        self.assertEqual(took, [], "the peer's turn is held")
        self.assertTrue(self.a.state["peer_stopped"]["kit"]["channel:32"])
        self.msgs["32"].append(msg(203, "11", "ok, carry on"))
        self.msgs["32"].append(msg(204, "13", "<@19> again", bot=True, mentions=["19"]))
        self.a.tick()
        self.assertEqual(took, ["203", "204"])


if __name__ == "__main__":
    unittest.main()
