from app.auth.password import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_password(self):
        pwd = "my_secure_password"  # pragma: allowlist secret
        hashed = hash_password(pwd)

        assert hashed != pwd
        assert len(hashed) == 60  # bcrypt hashes are exactly 60 chars
        assert hashed.startswith("$2b$12$")

    def test_verify_password(self):
        pwd = "my_secure_password"  # pragma: allowlist secret
        hashed = hash_password(pwd)

        assert verify_password(pwd, hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_handles_invalid_hash(self):
        assert verify_password("my_secure_password", "invalid_hash_string") is False
