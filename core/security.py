import hashlib, os, secrets, hmac

# Production leaves PBKDF2_ITERATIONS unset (=260000). Tests set it low for speed.
DEFAULT_ITERATIONS = max(int(os.environ.get("PBKDF2_ITERATIONS", "260000")), 1)

def hash_password(pw, iterations=None):
    iterations = iterations or DEFAULT_ITERATIONS
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iterations)
    return f"{iterations}:{salt}:{dk.hex()}"

def verify_password(pw, stored):
    try:
        parts = stored.split(":")
        if len(parts) == 3:
            iterations, salt, dk_hex = parts
            iterations = int(iterations)
        else:
            salt, dk_hex = parts
            iterations = 260_000
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iterations)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception: return False

def hash_password_fast(pw):
    """Fast hash for temporary/bulk import passwords — throwaway, user must
    change on first login. Iteration count is stored in the hash itself."""
    return hash_password(pw, iterations=100)