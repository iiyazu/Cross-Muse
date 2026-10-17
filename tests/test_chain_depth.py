"""Chain control plane: serial depth and per-agent revisits cap a chain (a fan-out does not), the host renewal
policy extends them a bounded number of times, and the review gate keeps a review loop on one chain."""
from test_evidence import FG, done, handoffs, roster


def ping_pong(h, n=10):
    h.plan_claude(*[{"as": a, "calls": [["xmuse_send", {"to": b, "body": f"ping {i}"}]]}
                    for i, (a, b) in enumerate([("claude-a", "claude-b"), ("claude-b", "claude-a")] * n)])
    return h.send("claude-a", "start the ping-pong")


def notices(h):
    return [n["body"] for n in h.q("select body from messages where kind='notice'")]


def test_revisits_stop_a_loop_before_the_wake_fuse(make):
    h = make([("claude-a", "claude"), ("claude-b", "claude")], max_chain_revisits=3)
    m = ping_pong(h)
    h.wait_quiet(30)
    assert [t["agent_id"] for t in h.turns()] == ["claude-a", "claude-b"] * 3
    c = h.q("select * from chains where id=?", m["chain"])[0]
    assert (c["state"], c["note"], c["wakes"]) == ("capped", "max_chain_revisits", 6)
    assert h.q("select count(*) n from deliveries where state='held'")[0]["n"] == 1
    path = "->".join(["claude-a", "claude-b"] * 3 + ["claude-a"])
    assert any(f"capped (max_chain_revisits); path {path};" in n for n in notices(h)), notices(h)


def test_serial_depth_caps_a_pipeline_and_a_fan_out_is_one_hop(make):
    ids = ["claude-a", "claude-b", "claude-c", "claude-d"]
    h = make([(i, "claude") for i in ids], max_chain_depth=3)
    h.plan_claude({"as": "claude-a", "calls": [["xmuse_send", {"to": "claude-b", "body": "1"}],
                                               ["xmuse_send", {"to": "claude-c", "body": "1"}],
                                               ["xmuse_send", {"to": "claude-d", "body": "1"}]]},
                  *[{"as": a, "calls": [["xmuse_send", {"to": "human", "body": "ok"}]]} for a in ids[1:]])
    m = h.send("claude-a", "fan out")
    h.wait_quiet()
    assert len(h.turns()) == 4  # one hop to three peers: depth 1 each, not 3
    assert {x["depth"] for x in h.q("select depth from messages where sender='claude-a'")} == {1}
    assert h.q("select state from chains where id=?", m["chain"])[0]["state"] == "open"

    h.plan_claude(*[{"as": a, "calls": [["xmuse_send", {"to": b, "body": "next"}]]} for a, b in zip(ids, ids[1:])])
    m = h.send("claude-a", "pipeline")
    h.wait_quiet()
    assert [t["agent_id"] for t in h.turns()[4:]] == ["claude-a", "claude-b", "claude-c"]
    c = h.q("select * from chains where id=?", m["chain"])[0]
    assert (c["state"], c["note"]) == ("capped", "max_chain_depth")
    assert any("path claude-a->claude-b->claude-c->claude-d" in n for n in notices(h)), notices(h)


def test_host_renewals_extend_the_control_plane_a_bounded_number_of_times(make):
    h = make([("claude-a", "claude"), ("claude-b", "claude")], max_chain_revisits=2, chain_host_renewals=1)
    m = ping_pong(h)
    h.wait_quiet(30)
    assert len(h.turns()) == 8  # 2 each, renewed once (+2 each), then held for the user
    c = h.q("select * from chains where id=?", m["chain"])[0]
    assert (c["state"], c["note"], c["renewals"], c["max_revisits"]) == ("capped", "max_chain_revisits", 1, 4)
    assert sum("renewed by the host policy (1/1) after max_chain_revisits" in n for n in notices(h)) == 1


def test_default_is_no_renewal_and_the_fuses_never_renew(make):
    h = make([("claude-a", "claude"), ("claude-b", "claude")], max_chain_wakes=3, chain_host_renewals=5)
    m = ping_pong(h)
    h.wait_quiet(30)
    assert len(h.turns()) == 3
    c = h.q("select * from chains where id=?", m["chain"])[0]
    assert (c["note"], c["renewals"]) == ("max_chain_wakes", 0)
    assert not any("renewed" in n for n in notices(h)), notices(h)


def test_the_review_gate_keeps_the_loop_on_the_done_chain(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)])
    roster(h, rev="reviewer")
    out = done(h, "dev")
    assert out["review"] == "rev"
    d = h.q("select chain_id, depth from messages where kind='done'")[0]
    (r,) = handoffs(h)
    assert (r["chain_id"], r["depth"]) == (d["chain_id"], d["depth"])
    c = h.q("select * from chains where id=?", d["chain_id"])[0]
    assert c["max_wakes"] > 0 and c["max_depth"] == 8 and c["max_revisits"] == 3  # the budgetless done chain got one
