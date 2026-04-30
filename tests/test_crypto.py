from crypto_utils import (
    generate_keypair,
    serialize_public_key,
    deserialize_public_key,
    sign,
    verify,
)


def test_two_keypairs_are_different():
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    assert serialize_public_key(pub1) != serialize_public_key(pub2)


def test_serialize_deserialize_pubkey():
    priv, pub = generate_keypair()
    hex_str = serialize_public_key(pub)
    assert isinstance(hex_str, str)
    assert len(hex_str) == 66
    restored = deserialize_public_key(hex_str)
    assert serialize_public_key(restored) == hex_str


def test_serialize_is_hex():
    _, pub = generate_keypair()
    hex_str = serialize_public_key(pub)
    int(hex_str, 16)


def test_deserialize_invalid_hex():
    try:
        deserialize_public_key("not_hex")
        assert False
    except Exception:
        pass


def test_sign_returns_hex_string():
    priv, _ = generate_keypair()
    sig = sign(priv, b"test")
    assert isinstance(sig, str)
    bytes.fromhex(sig)


def test_sign_different_messages_different_sigs():
    priv, _ = generate_keypair()
    sig1 = sign(priv, b"message1")
    sig2 = sign(priv, b"message2")
    assert sig1 != sig2


def test_sign_and_verify():
    priv, pub = generate_keypair()
    pub_hex = serialize_public_key(pub)
    message = b"hello world"
    sig = sign(priv, message)
    assert verify(pub_hex, sig, message)


def test_verify_long_message():
    priv, pub = generate_keypair()
    pub_hex = serialize_public_key(pub)
    msg = b"x" * 10000
    sig = sign(priv, msg)
    assert verify(pub_hex, sig, msg)


def test_verify_wrong_message():
    priv, pub = generate_keypair()
    pub_hex = serialize_public_key(pub)
    sig = sign(priv, b"hello")
    assert not verify(pub_hex, sig, b"wrong message")


def test_verify_wrong_key():
    priv1, _ = generate_keypair()
    _, pub2 = generate_keypair()
    sig = sign(priv1, b"test")
    assert not verify(serialize_public_key(pub2), sig, b"test")


def test_verify_bad_signature_hex():
    _, pub = generate_keypair()
    pub_hex = serialize_public_key(pub)
    assert not verify(pub_hex, "deadbeef", b"test")


def test_verify_bad_pubkey():
    priv, pub = generate_keypair()
    sig = sign(priv, b"test")
    assert not verify("badpubkey", sig, b"test")


def test_verify_never_raises():
    assert not verify("zzzz", "zzzz", b"zzzz")
    assert not verify("", "", b"")
