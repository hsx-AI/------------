from app.security.hmac_utils import canonical_json_bytes, generate_hmac


def test_canonical_json_is_sorted_compact_utf8():
    assert canonical_json_bytes({"b": 2, "a": "中文"}) == '{"a":"中文","b":2}'.encode()


def test_hmac_excludes_hmac_field():
    one = {"b": 2, "a": 1, "hmac": "ignored"}
    two = {"a": 1, "b": 2, "hmac": "different"}
    assert generate_hmac(one, b"secret") == generate_hmac(two, b"secret")


def test_android_python_golden_vector():
    message = {"protocolVersion": 1, "messageId": "550e8400-e29b-41d4-a716-446655440000", "type": "sms_code", "sender": "10690000", "code": "583921", "smsTextMasked": "您的验证码为 58****", "receivedAt": "2026-08-01T11:00:00+08:00", "sentAt": "2026-08-01T11:00:01+08:00", "nonce": "abcdefghijklmnop", "hmac": ""}
    assert generate_hmac(message, "shared-secret-测试".encode()) == "12222e9ed1e68b7a1205435df12e8a34ec8f4d8ddb1cf2d7c25b23c18f883824"
