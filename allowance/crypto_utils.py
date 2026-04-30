from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature

CURVE = ec.SECP256R1()
SIGNATURE_ALGO = ec.ECDSA(hashes.SHA256())


def generate_keypair():
    private_key = ec.generate_private_key(CURVE)
    return private_key, private_key.public_key()


def serialize_public_key(public_key):
    raw = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint,
    )
    return raw.hex()``


def deserialize_public_key(hex_str):
    raw = bytes.fromhex(hex_str)
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, raw)


def sign(private_key, message: bytes) -> str:
    sig = private_key.sign(message, SIGNATURE_ALGO)
    return sig.hex()


def verify(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    try:
        pub = deserialize_public_key(public_key_hex)
        sig = bytes.fromhex(signature_hex)
        pub.verify(sig, message, SIGNATURE_ALGO)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False
