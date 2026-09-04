import hashlib, secrets

def hash_password(pw, iterations=260_000):
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
        return dk.hex() == dk_hex
    except: return False

def hash_password_fast(pw):
    """Fast hash for temporary/bulk import passwords — throwaway, user must
    change on first login. Iteration count is stored in the hash itself."""
    return hash_password(pw, iterations=100)