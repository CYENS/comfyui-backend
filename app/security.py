from passlib.context import CryptContext

# pbkdf2_sha256 avoids bcrypt backend issues and has no 72-byte password limit.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)
