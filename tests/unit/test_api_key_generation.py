"""Pure, DB-free tests for API key generation and hashing — see
app.auth.api_keys. No fixtures, no database: this is exactly the
"generate a key" concern, independent of persistence.
"""

from app.auth.api_keys import (
    ADMIN_KEY_PREFIX,
    STUDENT_KEY_PREFIX,
    generate_admin_key,
    generate_student_key,
    hash_key,
)


def test_student_key_is_generated_with_the_student_prefix() -> None:
    material = generate_student_key()

    assert material.plaintext.startswith(STUDENT_KEY_PREFIX)


def test_admin_key_is_generated_with_the_admin_prefix() -> None:
    material = generate_admin_key()

    assert material.plaintext.startswith(ADMIN_KEY_PREFIX)


def test_generated_keys_have_at_least_256_bits_of_random_entropy() -> None:
    """secrets.token_urlsafe(32) encodes 32 random bytes = 256 bits as
    ~43 base64url characters. Check the random suffix (everything after
    the non-secret role prefix) is long enough to carry that entropy.
    """
    material = generate_student_key()
    secret_suffix = material.plaintext.removeprefix(STUDENT_KEY_PREFIX)

    assert len(secret_suffix) >= 43


def test_generated_keys_are_not_derived_from_weak_material() -> None:
    """Two independently generated keys must never collide — a
    lightweight proxy for "this isn't a deterministic/weak generator
    like a timestamp or a small random module seed."
    """
    first = generate_student_key()
    second = generate_student_key()

    assert first.plaintext != second.plaintext


def test_key_prefix_is_a_short_slice_of_the_plaintext_not_the_whole_thing() -> None:
    material = generate_student_key()

    assert material.plaintext.startswith(material.key_prefix)
    assert len(material.key_prefix) < len(material.plaintext)


def test_hash_is_deterministic_for_identical_plaintext() -> None:
    plaintext = generate_student_key().plaintext

    assert hash_key(plaintext) == hash_key(plaintext)


def test_different_keys_have_different_hashes() -> None:
    first = generate_student_key().plaintext
    second = generate_student_key().plaintext

    assert hash_key(first) != hash_key(second)


def test_hash_is_a_sha256_hex_digest() -> None:
    material = generate_student_key()

    assert material.key_hash == hash_key(material.plaintext)
    assert len(material.key_hash) == 64
    assert all(c in "0123456789abcdef" for c in material.key_hash)
