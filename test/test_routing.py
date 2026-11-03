"""Routing (bridges.md, "Routing"; what the tests must pin): a mention reaches that agent alone, no mention the
channel's primary or nobody, the gates decide who may wake an agent at all."""
import unittest

from loomdiscord import routing
from loomvenue import common
from test.fixtures import GATES, ROUTES, msg

CH30, CH31, CH32, CH33 = ({"id": c, "name": f"c{c}"} for c in ("30", "31", "32", "33"))


def view(agent="kit", routes=ROUTES, gates=GATES):
    return routing.View(agent, routes, gates)


class Routing(unittest.TestCase):
    def test_no_mention_reaches_the_primary_or_nobody(self):
        self.assertEqual(view("kit").reason(msg(1, "11", "hi"), CH30), "human")
        self.assertIsNone(view("bolt").reason(msg(1, "11", "hi"), CH30))
        self.assertIsNone(view("kit").reason(msg(1, "11", "hi"), {"id": "77", "name": "unrouted"}))

    def test_a_mention_of_another_agent_reaches_that_one_alone(self):
        m = msg(2, "11", "<@13> over to you", mentions=["13"])
        self.assertIsNone(view("kit").reason(m, CH30))
        self.assertEqual(view("bolt").reason(m, CH30), "human-mention")

    def test_a_mention_counts_only_when_written_and_resolved(self):
        reply_ping = msg(3, "11", "thanks", mentions=["19"])          # Discord's reply-ping: not a summons
        self.assertIsNone(view("bolt").reason(reply_ping, CH30))
        self.assertEqual(view("kit").reason(msg(4, "11", "<@19>", mentions=["19"]), {"id": "77"}), "human-mention")
        self.assertIsNone(view("kit").reason(msg(5, "11", "<@19>"), {"id": "77"}))   # written, not resolved

    def test_the_bots_own_managed_role_summons_it(self):
        self.assertEqual(view("kit").reason(msg(6, "11", "<@&91> hey", roles=["91"]), {"id": "77"}), "human-mention")
        self.assertIsNone(view("kit").reason(msg(7, "11", "<@&92> hey", roles=["92"]), {"id": "77"}))

    def test_the_gates_decide_who_may_wake(self):
        self.assertIsNone(view().reason(msg(8, "99", "a stranger"), CH30))
        self.assertIsNone(view().reason(msg(9, "12", "guest outside its venue"), CH30))
        self.assertEqual(view().reason(msg(10, "12", "guest inside"), CH31), "human")
        thread = {"id": "50", "is_thread": True, "parent_id": "31"}
        self.assertEqual(view().reason(msg(11, "12", "in a thread of its venue"), thread), "human")
        self.assertIsNone(view(gates=None).reason(msg(12, "11", "no gates"), CH30))

    def test_peers_wake_only_in_a_peer_venue_with_a_mention(self):
        self.assertIsNone(view().reason(msg(13, "13", "<@19>", bot=True, mentions=["19"]), CH30))
        self.assertEqual(view().reason(msg(14, "13", "<@19>", bot=True, mentions=["19"]), CH32), "peer")
        self.assertIsNone(view().reason(msg(15, "13", "no mention", bot=True), CH32))
        self.assertIsNone(view().reason(msg(16, "88", "<@19>", bot=True, mentions=["19"]), CH32))   # not a peer

    def test_webhooks_route_only_as_a_listed_peer(self):
        self.assertEqual(view().reason(msg(17, "14", "any post", bot=True, webhook="14"), CH33), "peer")
        self.assertIsNone(view().reason(msg(18, "66", "a stray hook", bot=True, webhook="66"), CH33))

    def test_its_own_posts_and_system_messages_never_route(self):
        self.assertIsNone(view().reason(msg(19, "19", "me"), CH30))
        self.assertIsNone(view().reason(msg(20, "11", "pinned", type_=6), CH30))

    def test_polled_ignore_and_only(self):
        v = view()
        self.assertFalse(v.polled("39"))
        self.assertTrue(v.polled("30"))
        v2 = view(routes=dict(ROUTES, only=["31"]))
        self.assertFalse(v2.polled("30"))
        self.assertTrue(v2.polled("31"))

    def test_a_thread_is_its_own_place_and_never_labelled_by_its_name(self):
        th = {"id": "50", "is_thread": True, "parent_id": "30", "name": "the starter message's text"}
        self.assertEqual(routing.place_of(th), "thread:50")
        self.assertEqual(routing.place_of(CH30), "channel:30")
        self.assertEqual(routing.label_of(th, {"30": "general"}), "#general thread")
        self.assertNotIn("starter", routing.label_of(th, {}))

    def test_from_is_a_person_card_or_unknown(self):
        v = view()
        self.assertEqual(common.from_of(v.sender(msg(1, "11"))), {"kind": "person", "slug": "robin"})
        self.assertEqual(common.from_of(v.sender(msg(1, "13", bot=True))), {"kind": "unknown"})   # a peer bot
        self.assertEqual(common.from_of(v.sender(msg(1, "99"))), {"kind": "unknown"})
        self.assertEqual(common.from_of(("Not A Slug", {"agent": False})), {"kind": "unknown"})


if __name__ == "__main__":
    unittest.main()
