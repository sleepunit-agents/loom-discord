"""What loom's deliver takes (t-1909): the time, the body's shape, what a refusal means, and the shadow's check.

The first live Discord message was dropped: loom's deliver refuses an `at` that isn't ISO-8601 UTC with at most 3
fraction digits and a `Z`, and the adapter sent Discord's raw `timestamp` (`…58.881000+00:00`); its 400 was then
taken as "refused for good" and the message marked done. These run real Discord timestamps through the adapter's
own body, against loom's own `at` rule, copied below from loom's source."""
import importlib.machinery
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from loomdiscord import adapter, routing
from loomvenue import common
from test.fixtures import GATES, ROUTES, msg

# loom src/backends/conversations.ts (main 720ead5), `ISO_UTC`, the rule parseTurn applies to a delivery's `at`
# (`at is an ISO-8601 UTC time (…Z)`). Copied here on its own, not imported from common, so this test checks
# common's copy too.
LOOM_ISO_UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$"


def loom_takes(at):
    return isinstance(at, str) and "\n" not in at and re.match(LOOM_ISO_UTC, at) is not None


# Real Discord message timestamps, as the API sends them (the first is the message t-1745's live switch dropped).
DISCORD = [
    ("2026-11-06T16:34:58.881000+00:00", "2026-11-06T16:34:58.881Z"),
    ("2026-11-06T16:34:58+00:00", "2026-11-06T16:34:58.000Z"),
    ("2026-11-06T23:59:59.999999+00:00", "2026-11-06T23:59:59.999Z"),     # truncated: never into the next day
    ("2026-11-06T18:34:58.881000+02:00", "2026-11-06T16:34:58.881Z"),
]
# Real Slack ts values (seconds and 6 digits), from t-1745's shadow windows.
SLACK = [
    ("1793828004.242749", "2026-11-04T21:33:24.242Z"),
    ("1793723214.782659", "2026-11-03T16:26:54.782Z"),
    ("1793762896.550436", "2026-11-04T03:28:16.550Z"),
    ("1793828004.999999", "2026-11-04T21:33:24.999Z"),                    # truncated: never into the next second
]

BIN = Path(__file__).resolve().parent.parent / "bin" / "loom-discord"
loader = importlib.machinery.SourceFileLoader("loom_discord_bin_contract", str(BIN))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class Time(unittest.TestCase):
    def test_the_copy_in_common_is_looms_rule(self):
        self.assertEqual(common.ISO_UTC.pattern, LOOM_ISO_UTC.strip("^$"))

    def test_loom_refuses_what_discord_and_the_old_helper_sent(self):
        self.assertFalse(loom_takes("2026-11-06T16:34:58.881000+00:00"))   # Discord's raw timestamp
        self.assertFalse(loom_takes("2026-11-06T16:34:58.881000Z"))        # the old iso(): 6 digits
        self.assertFalse(loom_takes("2026-11-06T16:34:58.881Z\n"))

    def test_a_discord_timestamp(self):
        for raw, want in DISCORD:
            with self.subTest(raw=raw):
                self.assertEqual(common.iso(raw), want)
                self.assertTrue(loom_takes(common.iso(raw)))

    def test_a_slack_ts(self):
        for raw, want in SLACK:
            with self.subTest(raw=raw):
                self.assertEqual(common.iso(raw), want)
                self.assertTrue(loom_takes(common.iso(raw)))

    def test_epoch_seconds_as_numbers(self):
        self.assertEqual(common.iso(1793982898.881), "2026-11-06T16:34:58.881Z")
        self.assertEqual(common.iso(1793982898), "2026-11-06T16:34:58.000Z")
        self.assertTrue(loom_takes(common.iso(1793982898.123456)))

    def test_what_isnt_a_time(self):
        for bad in ("", "soon", "2026-11-06T16:34:58", None, True, float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                common.iso(bad)

    def test_a_snowflakes_time(self):
        # 1568302511436202005: the #pond message t-1745's switch dropped (refused 16:34:23Z).
        self.assertEqual(adapter.snowflake_iso("1568302511436202005"), "2026-11-06T16:34:16.378Z")


class Body(unittest.TestCase):
    """The body the adapter sends for a real Discord message, as loom's deliver checks it."""

    def message(self, ts):
        m = msg("1568302511436202005", "11", "hi")
        m["timestamp"] = ts
        return m

    def body(self, m):
        return adapter.body_of("kit", m, {"id": "30", "name": "pond"}, ("robin", GATES["people"]["robin"]), "#pond")

    def test_a_real_discord_message_meets_the_contract(self):
        for raw, want in DISCORD:
            with self.subTest(raw=raw):
                b = self.body(self.message(raw))
                self.assertEqual(b["at"], want)
                self.assertTrue(loom_takes(b["at"]))
                self.assertEqual(common.contract_problems(b), [])

    def test_no_timestamp_is_the_snowflakes_time(self):
        m = self.message("x")
        del m["timestamp"]
        self.assertEqual(self.body(m)["at"], "2026-11-06T16:34:16.378Z")
        self.assertEqual(self.body(self.message("garbage"))["at"], "2026-11-06T16:34:16.378Z")

    def test_the_check_says_what_loom_would_refuse(self):
        b = self.body(self.message(DISCORD[0][0]))
        self.assertEqual(common.contract_problems(dict(b, at="2026-11-06T16:34:58.881000+00:00")),
                         ["at is an ISO-8601 UTC time (…Z)"])
        self.assertEqual(common.contract_problems(dict(b, at="2026-11-06T16:34:58.881000Z")),
                         ["at is an ISO-8601 UTC time (…Z)"])
        self.assertIn("venue is a venue name: lowercase letters, digits and dashes, at most 32",
                      common.contract_problems(dict(b, venue="Discord")))
        self.assertTrue(common.contract_problems(dict(b, extra=1))[0].startswith('a delivery has no key "extra"'))
        self.assertTrue(common.contract_problems(dict(b, text="")))
        self.assertTrue(common.contract_problems(dict(b, place="")))
        self.assertTrue(common.contract_problems(dict(b, label="a\nb")))
        self.assertTrue(common.contract_problems(dict(b, **{"from": {"kind": "person"}})))
        self.assertTrue(common.contract_problems(dict(b, kind="note")))
        self.assertTrue(common.contract_problems(dict(b, local=True)))
        self.assertEqual(common.contract_problems(dict(b, **{"from": {"kind": "unknown"}})), [])
        self.assertEqual(common.contract_problems("x"), ["a delivery is a JSON object"])


class Verdict(unittest.TestCase):
    """loom's deliver answers (src/delivery.ts; loom-box delivery.mjs's own, passed through by core)."""

    def test_a_malformed_request_is_held(self):
        for status, err in [(400, "bad-input: at is an ISO-8601 UTC time (…Z)"),
                            (400, "bad-input: id is required: the source's own id for the message, 1-200 characters"),
                            (400, 'bad-input: a delivery has no key "extra" (it has id, agent, …)'),
                            (400, "bad-input: malformed JSON"),
                            (400, "at is an ISO-8601 time"),                  # the runtime's own parse
                            (415, "unsupported-media-type: POST /api takes application/json")]:
            with self.subTest(err=err):
                self.assertEqual(common.verdict(status, {"error": err}), common.HOLD)

    def test_a_refusal_about_the_message_itself_is_final(self):
        for status, err in [(403, "forbidden: discord doesn't declare venue x (its loom block's venues)"),
                            (403, "forbidden: kit isn't one of this household's agents"),
                            (403, "forbidden: from {kind: person} comes only from a venue adapter on its own venue"),
                            (409, "conflict: kit:1 was already delivered with a different body"),
                            (413, "oversized: a delivery is 256 KB at most"),
                            (400, "bad-input: text is required: the message, 1-40000 characters"),
                            (400, "text is 1-40000 characters")]:
            with self.subTest(err=err):
                self.assertEqual(common.verdict(status, {"error": err}), common.FINAL)

    def test_the_rest(self):
        self.assertEqual(common.verdict(200, {"conversation": "cv-0", "seq": 1, "body": "fed"}), common.DONE)
        for status in (0, 401, 429, 500, 502, 503, 504):
            self.assertEqual(common.verdict(status, {"error": "x"}), common.RETRY)


class FakeDeliverer:
    def __init__(self, status, ans):
        self.answer, self.bodies = (status, ans), []

    def deliver(self, body):
        self.bodies.append(body)
        return self.answer


class FakeAlerter:
    def __init__(self):
        self.said = []

    def alert(self, key, source, severity, summary, **facts):
        self.said.append((key, source, severity, facts))
        return True


class Sink(unittest.TestCase):
    def sink(self, status, ans):
        d, al = FakeDeliverer(status, ans), FakeAlerter()
        return cli.make_sink({"loom_url": "", "token_file": None, "alert": None}, deliverer=d, alerter=al), d, al

    def call(self, s):
        m = msg("1568302511436202005", "11", "hi")
        m["timestamp"] = DISCORD[0][0]
        return s("kit", m, {"id": "30", "name": "pond"}, ("robin", GATES["people"]["robin"]), "#pond")

    def test_the_body_it_sends_meets_the_contract(self):
        s, d, _ = self.sink(200, {"conversation": "cv-000000000000", "seq": 1, "body": "fed"})
        self.assertIs(self.call(s), True)
        self.assertEqual(d.bodies[0]["at"], "2026-11-06T16:34:58.881Z")
        self.assertEqual(common.contract_problems(d.bodies[0]), [])

    def test_a_malformed_refusal_holds_and_alerts(self):
        s, _, al = self.sink(400, {"error": "bad-input: at is an ISO-8601 UTC time (…Z)"})
        self.assertEqual(self.call(s), common.HOLD)
        self.assertEqual([(k, src, sev) for k, src, sev, _ in al.said], [("hold", "loom-discord", "bad")])
        self.assertEqual(al.said[0][3]["message"], "1568302511436202005")

    def test_a_refusal_about_the_message_is_done_with_no_alert(self):
        s, _, al = self.sink(403, {"error": "forbidden: kit isn't one of this household's agents"})
        self.assertIs(self.call(s), True)
        self.assertEqual(al.said, [])

    def test_no_answer_is_next_tick(self):
        s, _, al = self.sink(0, {"error": "URLError"})
        self.assertIs(self.call(s), False)
        self.assertEqual(al.said, [])


class Alerts(unittest.TestCase):
    def test_once_per_condition_detached_and_no_text(self):
        runs = []
        a = common.Alerter(["/bin/alert"], popen=lambda argv, **kw: runs.append((argv, kw)))
        self.assertTrue(a.alert("hold", "loom-discord", "bad", "held", status=400, error="bad-input: at"))
        self.assertFalse(a.alert("hold", "loom-discord", "bad", "held again"))
        self.assertEqual(runs[0][0], ["/bin/alert", "loom-discord", "--severity", "bad", "--summary", "held",
                                      "--fact", "status=400", "--fact", "error=bad-input: at"])
        self.assertTrue(runs[0][1]["start_new_session"])

    def test_unset_is_the_journal_only(self):
        self.assertFalse(common.Alerter(None).alert("hold", "loom-discord", "bad", "held"))


class FakeDiscord:
    def __init__(self, channels, messages):
        self.channels, self.messages, self.calls = channels, messages, []

    def call(self, path, method="GET", body=None):
        self.calls.append((method, path))
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


class Poll(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="loom-discord-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.msgs = {"30": [msg(100, "11", "old")]}
        self.apis = {"kit": FakeDiscord(["30"], self.msgs)}
        self.runs = []
        self.alerts = common.Alerter(["/bin/alert"], popen=lambda argv, **kw: self.runs.append(argv))

    def make(self, sink=None):
        views = lambda agent: routing.View(agent, ROUTES, GATES)  # noqa: E731
        return adapter.Adapter(self.dir, self.apis, views, common.ShadowLog(self.dir, "discord"), sink=sink,
                               alerter=self.alerts)

    def log(self):
        p = self.dir / common.ShadowLog.NAME
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_a_held_message_isnt_lost_isnt_resent_and_is_tried_again_after_a_restart(self):
        took, answer = [], {"v": common.HOLD}

        def sink(agent, m, ch, hit, label):
            took.append(m["id"])
            return answer["v"]
        a = self.make(sink)
        a.tick()
        self.msgs["30"] += [msg(101, "11", "first"), msg(102, "11", "second")]
        a.tick()
        self.assertEqual(took, ["101"])
        self.assertFalse(a.handled("101", "kit"))
        self.assertIn("kit:101", a.state["held"])
        a.tick()
        a.tick()
        self.assertEqual(took, ["101"], "held: not sent again by the same process, and nothing after it skipped")
        answer["v"] = True                    # the adapter is fixed and restarted
        b = self.make(sink)
        b.tick()
        self.assertEqual(took, ["101", "101", "102"])
        self.assertTrue(b.handled("101", "kit") and b.handled("102", "kit"))
        self.assertEqual(b.state["held"], {})

    def test_the_shadow_checks_each_body_against_the_contract(self):
        a = self.make()
        a.tick()
        good = msg(103, "11", "hi")
        good["timestamp"] = DISCORD[0][0]
        self.msgs["30"].append(good)
        a.tick()
        self.assertEqual([(x["id"], x["contract"]) for x in self.log()], [("103", "ok")])
        self.assertEqual(self.runs, [])

    def test_a_shadow_mismatch_is_logged_and_alerted_once(self):
        a = self.make()
        a.tick()
        real = common.delivery
        try:
            # A future bug in how the body is written: the old helper's 6-digit time.
            common.delivery = lambda *args: dict(real(*args), at="2026-11-06T16:34:58.881000Z")
            self.msgs["30"] += [msg(104, "11", "a"), msg(105, "11", "b")]
            a.tick()
        finally:
            common.delivery = real
        self.assertEqual([(x["id"], x["contract"]) for x in self.log()],
                         [("104", ["at is an ISO-8601 UTC time (…Z)"]), ("105", ["at is an ISO-8601 UTC time (…Z)"])])
        self.assertEqual([r[1:4] for r in self.runs], [["loom-discord", "--severity", "bad"]])
        self.assertIn("--fact", self.runs[0])
        self.assertIn("message=104", self.runs[0])
        self.assertNotIn('"a"', (self.dir / common.ShadowLog.NAME).read_text())


if __name__ == "__main__":
    unittest.main()
