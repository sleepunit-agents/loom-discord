"""The poller: shadow logs and delivers nothing; a message is handled once per addressed agent (per-bot
de-duplication); live hands each to the sink and keeps the cursor when loom doesn't take one."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from loomdiscord import adapter, routing
from loomvenue import common
from test.fixtures import GATES, ROUTES, msg


class FakeDiscord:
    """One bot's view: the guild's channels and each channel's messages. Records every call; it has no post."""

    def __init__(self, channels, messages):
        self.channels, self.messages, self.calls = channels, messages, []

    def call(self, path, method="GET", body=None):
        self.calls.append((method, path))
        assert method == "GET", "the poller only reads"
        if path.endswith("/channels"):
            return [{"id": c, "name": f"c{c}", "type": 0} for c in self.channels]
        if path.endswith("/threads/active"):
            return {"threads": []}
        cid = path.split("/")[2]
        msgs = self.messages.get(cid, [])
        if "limit=1" in path and "after" not in path:
            return msgs[-1:] if msgs else []
        after = int(path.split("after=")[1].split("&")[0])
        return [m for m in reversed(msgs) if int(m["id"]) > after]


class Poller(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="loom-discord-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.msgs = {"30": [msg(100, "11", "old")]}
        self.apis = {"kit": FakeDiscord(["30", "39"], self.msgs), "bolt": FakeDiscord(["30"], self.msgs)}

    def make(self, sink=None):
        views = lambda agent: routing.View(agent, ROUTES, GATES)  # noqa: E731
        return adapter.Adapter(self.dir, self.apis, views, common.ShadowLog(self.dir, "discord"), sink=sink)

    def log(self):
        p = self.dir / common.ShadowLog.NAME
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_first_sight_replays_nothing_and_ignored_channels_arent_polled(self):
        a = self.make()
        self.assertEqual(a.tick(), 0)
        self.assertFalse(any("/channels/39/" in p for _, p in self.apis["kit"].calls))
        self.assertEqual(self.log(), [])

    def test_shadow_logs_what_it_would_deliver_and_nothing_else(self):
        a = self.make()
        a.tick()
        self.msgs["30"] += [msg(101, "11", "secret plans"), msg(102, "99", "a stranger"),
                            msg(103, "11", "<@13> and <@19>", mentions=["13", "19"])]
        a.tick()
        got = sorted((x["id"], x["agent"], x["place"]) for x in self.log())
        self.assertEqual(got, [("101", "kit", "channel:30"), ("103", "bolt", "channel:30"), ("103", "kit", "channel:30")])
        self.assertNotIn("secret", (self.dir / common.ShadowLog.NAME).read_text())
        a.tick()   # nothing new: nothing logged twice
        self.assertEqual(len(self.log()), 3)

    def test_a_message_seen_twice_by_one_bot_is_handled_once(self):
        a = self.make()
        a.tick()
        self.msgs["30"].append(msg(104, "11", "hi"))
        a.tick()
        a.state["cursors"]["kit"]["30"] = "100"   # the cursor went back (a restore): the same message again
        a.tick()
        self.assertEqual([x["id"] for x in self.log()], ["104"])

    def test_live_hands_each_to_the_sink_and_keeps_the_cursor_on_a_failure(self):
        took = []
        ok = {"v": False}
        a = self.make(sink=lambda agent, m, ch, hit, label: (took.append((agent, m["id"], label, hit[0])), ok["v"])[1])
        a.tick()
        self.msgs["30"].append(msg(105, "11", "hi"))
        a.tick()
        self.assertEqual(took, [("kit", "105", "#c30", "robin")])
        a.tick()   # loom didn't take it: offered again
        self.assertEqual(len(took), 2)
        ok["v"] = True
        a.tick()
        a.tick()
        self.assertEqual(len(took), 3)
        self.assertEqual(self.log(), [], "live writes no shadow log")

    def test_live_a_guests_daily_cap(self):
        took = []
        a = self.make(sink=lambda agent, m, ch, hit, label: took.append(m["id"]) or True)
        self.msgs["31"] = [msg(200, "12", "x")]
        self.apis["kit"].channels.append("31")
        a.tick()
        self.msgs["31"] += [msg(201 + i, "12", "guest") for i in range(3)]
        a.tick()
        self.assertEqual(took, ["201", "202"])   # daily_spawns: 2

    def test_no_view_routes_nothing(self):
        a = adapter.Adapter(self.dir, self.apis, lambda agent: None, common.ShadowLog(self.dir, "discord"))
        self.assertEqual(a.tick(), 0)
        self.assertEqual(self.apis["kit"].calls, [])


if __name__ == "__main__":
    unittest.main()
