"""`read`: a place's messages as the agent's bot sees them, for a piece that acts on a channel with no body (the
packages piece's tracking numbers, t-1965). It reads, routes nothing, posts nothing, and says who may wake the agent."""
import shutil
import tempfile
import unittest
from pathlib import Path

from test.fixtures import GATES, ROUTES, msg
from test.test_send import FakeSecrets, cli


class Doc:
    def __init__(self, doc):
        self._doc = doc

    def doc(self):
        return self._doc


class ReadApi:
    calls, posts, msgs = [], [], []

    def __init__(self, token):
        self.token = token

    def call(self, path, method="GET", body=None):
        ReadApi.calls.append((method, path))
        return list(ReadApi.msgs)

    def post(self, cid, text):
        ReadApi.posts.append((cid, text))


class Read(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="loom-discord-r-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        ReadApi.calls, ReadApi.posts = [], []
        ReadApi.msgs = [msg(102, "12", "1Z999AA10123456784"), msg(101, "11", "add 1Z999AA10123456784 lamp"),
                        msg(103, "13", "<@19> hi", bot=True), msg(104, "99", "a stranger"),
                        msg(105, "19", "my own post", bot=True), msg(106, "14", "hook", webhook="14")]
        # Shadow: reading needs no live mode.
        self.cfg = cli.config({"DISCORD_BOTS": '{"kit": "kit-discord-token"}', "DISCORD_DATA": str(self.dir)})
        self.docs = (Doc(ROUTES), Doc(GATES))

    def read(self, argv, docs=None):
        return cli.read(self.cfg, argv, secrets=FakeSecrets(), api_for=ReadApi, docs=docs or self.docs)

    def test_an_ignored_channel_is_read_oldest_first_and_nothing_is_posted(self):
        ans = self.read(["--place", "channel:39", "--agent", "kit", "--after", "100"])
        self.assertTrue(ans["ok"])
        self.assertEqual([m["id"] for m in ans["messages"]], ["101", "102", "103", "104", "105", "106"])
        self.assertEqual(ReadApi.calls, [("GET", "/channels/39/messages?after=100&limit=100")])
        self.assertEqual(ReadApi.posts, [])
        first = ans["messages"][0]
        self.assertEqual(first, {"id": "101", "at": "2026-11-02T12:00:00.000Z", "from": {"kind": "person", "slug": "robin"},
                                 "person": True, "may_wake": True, "text": "add 1Z999AA10123456784 lamp"})

    def test_who_may_wake_the_agent_there_is_the_gates_word(self):
        by = {m["id"]: m for m in self.read(["--place", "channel:39", "--agent", "kit", "--after", "100"])["messages"]}
        self.assertEqual((by["102"]["person"], by["102"]["may_wake"]), (True, False))    # a guest outside its venue
        self.assertEqual((by["104"]["person"], by["104"]["may_wake"]), (True, False))    # a stranger
        self.assertEqual(by["104"]["from"], {"kind": "unknown"})
        for mid in ("103", "105", "106"):                                                # a bot, itself, a webhook
            self.assertEqual((by[mid]["person"], by[mid]["may_wake"]), (False, False))

    def test_first_sight_reads_the_latest_one(self):
        self.read(["--place", "channel:39", "--agent", "kit"])
        self.assertEqual(ReadApi.calls, [("GET", "/channels/39/messages?limit=1")])

    def test_fails_closed_and_refuses_what_it_cant_read(self):
        self.assertFalse(self.read(["--place", "channel:39", "--agent", "kit"], docs=(Doc(ROUTES), Doc(None)))["ok"])
        self.assertFalse(self.read(["--place", "dm:39", "--agent", "kit"])["ok"])
        self.assertFalse(self.read(["--place", "channel:39", "--agent", "bolt"])["ok"])
        self.assertFalse(self.read(["--place", "channel:39", "--agent", "kit", "--after", "x"])["ok"])
        self.assertFalse(self.read(["--place", "channel:39", "--agent", "kit", "--limit", "101"])["ok"])
        self.assertEqual(ReadApi.calls, [])


if __name__ == "__main__":
    unittest.main()
