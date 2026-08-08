from app.security.replay_guard import ReplayGuard


def test_rejects_replay_until_ttl():
    now = [0.0]
    guard = ReplayGuard(10, clock=lambda: now[0])
    assert guard.accept("nonce")
    assert not guard.accept("nonce")
    now[0] = 11
    assert guard.accept("nonce")
