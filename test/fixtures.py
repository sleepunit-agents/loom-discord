"""A made-up household: agents kit and bolt, people robin (owner), kim (a guest in channel 31), a peer bot."""
GATES = {"people": {"robin": {"name": "Robin", "tier": 3, "discord": ["11"]},
                    "kim": {"name": "Kim", "tier": 1, "discord": ["12"], "venues": ["31"], "daily_spawns": 2},
                    "lee": {"name": "Lee", "tier": 2, "discord": ["15"]}},
         "agents": {"bolt": {"name": "Bolt", "kind": "peer agent bot", "discord": ["13"]}}}
ROUTES = {"guild": "1", "bots": {"kit": "19", "bolt": "13"}, "bot_roles": {"kit": ["91"]},
          "webhook_peers": {"14": "Hooky"}, "ignore": ["39"],
          "channels": {"30": {"primary": "kit"}, "31": {"primary": "kit", "guest_venue": True},
                       "32": {"primary": "bolt", "peer": True}, "33": {"primary": "kit", "peer": True, "pair": "Hooky"}},
          "threads": {}}


def msg(n, uid, text="", bot=False, mentions=(), roles=(), webhook=None, type_=0):
    m = {"id": str(n), "type": type_, "content": text, "author": {"id": uid, "username": f"u{uid}", "bot": bot},
         "mentions": [{"id": x} for x in mentions], "mention_roles": list(roles),
         "timestamp": "2026-11-02T12:00:00+00:00"}
    if webhook:
        m["webhook_id"] = webhook
    return m
