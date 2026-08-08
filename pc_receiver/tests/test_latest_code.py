from datetime import datetime, timedelta, timezone
from threading import Thread
from time import sleep
from uuid import uuid4

from app.models.messages import SmsCodeMessage
from app.storage.latest_code import LatestCodeStore


def message(code="583921", sender="10690000", received=None):
    now = received or datetime.now(timezone.utc)
    return SmsCodeMessage(protocolVersion=1, messageId=uuid4(), type="sms_code", sender=sender, code=code, smsTextMasked="验证码 58****", receivedAt=now, sentAt=now, nonce="abcdefghijklmnop", hmac="0" * 64)


def test_consume_is_atomic():
    store = LatestCodeStore()
    store.put(message())
    assert store.get(consume=True).code == "583921"
    assert store.get() is None


def test_wait_filters_sender_and_after():
    store = LatestCodeStore()
    after = datetime.now(timezone.utc)
    thread = Thread(target=lambda: (sleep(0.05), store.put(message(sender="10691234", received=after + timedelta(seconds=1)))))
    thread.start()
    found = store.wait(1, "1069", after)
    thread.join()
    assert found and found.code == "583921"


def test_expiry():
    now = [datetime.now(timezone.utc)]
    store = LatestCodeStore(ttl_seconds=5, now=lambda: now[0])
    store.put(message())
    now[0] += timedelta(seconds=6)
    assert store.get() is None
