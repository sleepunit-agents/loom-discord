"""The venue's `send` (agent-runtime.md, "Outbound"): --place and --agent, the text on stdin, {ok, id?}; posted as
that agent's own bot; nothing at all in shadow."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

from loomdiscord import adapter
from loomvenue import common

BIN = Path(__file__).resolve().parent.parent / "bin" / "loom-discord"
loader = importlib.machinery.SourceFileLoader("loom_discord_bin", str(BIN))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class FakeSecrets:
    def __init__(self, ok=True):
        self.ok, self.asked = ok, []

    def get(self, agent, name):
        self.asked.append((agent, name))
        if not self.ok:
            raise common.SecretRefused("the secrets policy says ask")
        return "t0ken"


class FakeApi:
    posts = []

    def __init__(self, token):
        self.token = token

    def post(self, cid, text):
        FakeApi.posts.append((self.token, cid, text))
        return {"id": f"m{len(FakeApi.posts)}"}


def run_send(cfg, argv, text, secrets=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.send(cfg, argv, stdin=io.StringIO(text), secrets=secrets or FakeSecrets(), api_for=FakeApi)
    return code, json.loads(out.getvalue())


class Send(unittest.TestCase):
    def setUp(self):
        FakeApi.posts = []
        self.cfg = cli.config({"DISCORD_MODE": "live", "DISCORD_BOTS": '{"kit": "kit-discord-token"}'})

    def test_shadow_posts_nothing(self):
        cfg = cli.config({"DISCORD_BOTS": '{"kit": "kit-discord-token"}'})
        self.assertEqual(cfg["mode"], "shadow")
        sec = FakeSecrets()
        code, ans = run_send(cfg, ["--place", "channel:30", "--agent", "kit"], "hello", sec)
        self.assertEqual((code, ans["ok"]), (1, False))
        self.assertIn("shadow", ans["reason"])
        # Said as shadow, so the runtime can hand a DM to the old bridge meanwhile (t-1920); for good either way.
        self.assertEqual((ans["permanent"], ans["shadow"]), (True, True))
        self.assertEqual((FakeApi.posts, sec.asked), ([], []))

    def test_live_posts_as_the_agents_own_bot(self):
        code, ans = run_send(self.cfg, ["--place", "thread:50", "--agent", "kit"], "Hi Robin!")
        self.assertEqual((code, ans), (0, {"ok": True, "id": "m1"}))
        self.assertEqual(FakeApi.posts, [("t0ken", "50", "Hi Robin!")])

    def test_a_long_reply_is_split_under_discords_limit(self):
        text = ("line\n" * 900)
        code, ans = run_send(self.cfg, ["--place", "channel:30", "--agent", "kit"], text)
        self.assertEqual(code, 0)
        self.assertGreater(len(FakeApi.posts), 1)
        self.assertTrue(all(len(p[2]) <= cli.MAX_POST for p in FakeApi.posts))
        self.assertEqual("".join(p[2] + "\n" for p in FakeApi.posts).count("line"), 900)

    def test_no_bot_for_the_agent_or_a_refused_secret_says_why(self):
        _, ans = run_send(self.cfg, ["--place", "channel:30", "--agent", "bolt"], "x")
        self.assertEqual(ans, {"ok": False, "reason": "no Discord bot for bolt", "permanent": True})
        _, ans = run_send(self.cfg, ["--place", "channel:30", "--agent", "kit"], "x", FakeSecrets(ok=False))
        self.assertFalse(ans["ok"])
        self.assertNotIn("t0ken", json.dumps(ans))

    def test_a_place_that_isnt_discords(self):
        _, ans = run_send(self.cfg, ["--place", "dm:U1", "--agent", "kit"], "x")
        self.assertFalse(ans["ok"])
        _, ans = run_send(self.cfg, ["--agent", "kit"], "x")
        self.assertIn("usage", ans["reason"])
        self.assertEqual(FakeApi.posts, [])


class FailingApi:
    """Discord answering every post with one failure."""
    def __init__(self, error):
        self.error = error

    def __call__(self, token):
        return self

    def post(self, cid, text):
        raise self.error


def http(code):
    return urllib.error.HTTPError("https://discord.com/api/v10/channels/30/messages", code, "x", {}, None)


class Permanent(unittest.TestCase):
    """`permanent: true` when no retry will ever post it (agent-runtime.md, "Outbound"): the runtime records it
    refused, doesn't retry it and keeps nothing for a body. A refusal for now says no `permanent`."""

    def setUp(self):
        FakeApi.posts = []
        self.cfg = cli.config({"DISCORD_MODE": "live", "DISCORD_BOTS": '{"kit": "kit-discord-token"}'})

    def ans(self, argv, text="x", cfg=None, secrets=None, api=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.send(cfg or self.cfg, argv, stdin=io.StringIO(text), secrets=secrets or FakeSecrets(),
                            api_for=api or FakeApi)
        self.assertEqual(code, 1)
        return json.loads(out.getvalue())

    def test_shadow_no_bot_a_place_that_isnt_discords_and_nothing_to_send_are_for_good(self):
        shadow = cli.config({"DISCORD_BOTS": '{"kit": "kit-discord-token"}'})
        for argv, text, cfg in ((["--place", "channel:30", "--agent", "kit"], "x", shadow),
                                (["--place", "channel:30", "--agent", "bolt"], "x", None),
                                (["--place", "dm:U1", "--agent", "kit"], "x", None),
                                (["--place", "channel:abc", "--agent", "kit"], "x", None),
                                (["--agent", "kit"], "x", None),
                                (["--place", "channel:30", "--agent", "kit"], "  \n", None)):
            with self.subTest(argv=argv, shadow=cfg is shadow):
                a = self.ans(argv, text, cfg)
                self.assertIs(a["permanent"], True)
                self.assertFalse(a["ok"])
                self.assertEqual(a.get("shadow", False), cfg is shadow, "only the shadow refusal says shadow")
        self.assertEqual(FakeApi.posts, [])

    def test_a_channel_discord_wont_let_it_post_in_is_for_good(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code):
                a = self.ans(["--place", "channel:30", "--agent", "kit"], api=FailingApi(http(code)))
                self.assertEqual(a, {"ok": False, "reason": f"Discord refused the post: HTTPError {code}",
                                     "permanent": True})

    def test_a_rate_limit_a_5xx_the_network_or_an_unallowed_secret_is_for_now(self):
        for err in (adapter.RateLimited(5), http(408), http(500), http(502),
                    urllib.error.URLError("down"), TimeoutError(), ValueError("not JSON")):
            with self.subTest(err=repr(err)):
                a = self.ans(["--place", "channel:30", "--agent", "kit"], api=FailingApi(err))
                self.assertNotIn("permanent", a)
        a = self.ans(["--place", "channel:30", "--agent", "kit"], secrets=FakeSecrets(ok=False))
        self.assertNotIn("permanent", a)

    def test_settings_that_dont_parse_are_for_good(self):
        out = io.StringIO()
        env = {"LOOM_PIECE_NAME": "discord", "DISCORD_BOTS": "not json"}
        with unittest.mock.patch.dict("os.environ", env, clear=True), contextlib.redirect_stdout(out):
            code = cli.main(["send", "--place", "channel:30", "--agent", "kit"])
        self.assertEqual(code, 1)
        self.assertIs(json.loads(out.getvalue())["permanent"], True)


class Secrets(unittest.TestCase):
    def test_only_an_allowed_policy_reads_the_value_and_never_in_argv(self):
        calls = []

        class R:
            def __init__(self, out, code=0):
                self.stdout, self.returncode = out, code

        def run(argv, **kw):
            calls.append((argv, kw.get("env", {}).get("LOOM_SECRETS_ALLOW_GET")))
            if argv[2] == "may":
                return R(json.dumps({"may": "allowed" if argv[3] == "kit" else "ask"}), 0 if argv[3] == "kit" else 1)
            return R("v4lue\n")
        s = common.Secrets(["loom", "secrets", "may", "{agent}", "{name}", "--json"],
                           ["loom", "secrets", "get", "{name}", "--reveal"], run=run, env={})
        self.assertEqual(s.get("kit", "kit-tok"), "v4lue")
        with self.assertRaises(common.SecretRefused):
            s.get("bolt", "kit-tok")
        self.assertEqual([c[0][2] for c in calls], ["may", "get", "may"])
        self.assertEqual(calls[1][1], "1")
        self.assertFalse(any("v4lue" in a for c in calls for a in c[0]))


if __name__ == "__main__":
    unittest.main()
