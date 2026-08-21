"""
Password hashing and verification using passlib[bcrypt].

Why passlib instead of bcrypt directly?
  - passlib handles algorithm upgrades gracefully (CryptContext.needs_update())
  - If we ever add argon2 as a second scheme, it's a one-line config change
  - The spec (T-15) explicitly calls for passlib[bcrypt]

Why bcrypt at 12 rounds?
  - 12 rounds = 2^12 = 4,096 key-derivation iterations (~250ms on modern hardware)
  - Intentionally slow — that cost is negligible to a real user, ruinous to a
    brute-force attacker who must pay it for every guess
  - 10 is the minimum acceptable today; 12 is the safe default
"""

from passlib.context import CryptContext

# CryptContext is the stable interface. It embeds the algorithm name and cost
# factor inside every hash it produces, so future algorithm migrations are
# transparent — old hashes verify fine while new ones use the updated scheme.
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",  # marks old-cost hashes as needing rehash
    bcrypt__rounds=12,  # cost factor — never lower this in production
)


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password with bcrypt. Returns a 60-char string that
    encodes algorithm + cost factor + salt + digest:

        $2b$12$<22-char base64 salt><31-char base64 digest>

    The salt is generated internally by passlib via os.urandom — you must
    never generate or supply your own salt.

    Raises:
        ValueError: if plain is empty (defence-in-depth; schema validation
                    should have caught this earlier, but we enforce here too)
    """
    if not plain:
        raise ValueError("Password must not be empty")
    return str(_pwd_context.hash(plain))


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a stored bcrypt hash.

    passlib extracts the salt and cost factor from the stored hash, re-runs
    the derivation, and compares in constant time (no timing side-channel).

    Returns True only on a match. Never raises on a wrong password — always
    returns False so callers cannot distinguish "bad password" from "hash
    format error" via exception type.

    Note: never use this function for anything other than passwords. For
    constant-time comparison of arbitrary tokens, use secrets.compare_digest().
    """
    if not plain:
        return False
    try:
        return bool(_pwd_context.verify(plain, hashed))
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    """
    Return True if the stored hash was produced with an old cost factor or
    deprecated scheme and should be upgraded on next successful login.

    Usage in the login handler:
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(plain)
            await db.commit()

    This gives you a zero-downtime cost-factor upgrade path — existing users
    are silently migrated as they log in, without any forced password reset.
    """
    return bool(_pwd_context.needs_update(hashed))
