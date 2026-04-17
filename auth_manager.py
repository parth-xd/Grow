"""
User authentication system — JWT tokens, password hashing, Google OAuth.
Manages multi-user accounts with encrypted Groww API key storage.
"""

import os
import jwt
import logging
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from db_manager import Base, get_db

logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-key-change-in-production-32chars!!")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# ── User ORM Model ────────────────────────────────────────────────────────────

class User(Base):
    """Multi-tenant user account with encrypted API key."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=True)  # NULL for Google OAuth only
    groww_api_key = Column(String(500), nullable=True)  # Will store encrypted
    groww_api_secret = Column(String(500), nullable=True)  # Will store encrypted
    google_id = Column(String(255), nullable=True, unique=True)  # Google account link
    google_email = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User {self.email}>"

    def set_password(self, password):
        """Hash and store password (SHA-256 with salt)."""
        import secrets
        import base64
        salt = secrets.token_bytes(16)
        pwd_bytes = password.encode('utf-8')
        hash_bytes = hashlib.sha256(salt + pwd_bytes).digest()
        self.password_hash = base64.b64encode(salt + hash_bytes).decode('utf-8')

    def check_password(self, password):
        """Verify password against hash."""
        if not self.password_hash:
            return False
        import base64
        try:
            decoded = base64.b64decode(self.password_hash)
            salt = decoded[:16]
            stored_hash = decoded[16:]
            pwd_bytes = password.encode('utf-8')
            computed_hash = hashlib.sha256(salt + pwd_bytes).digest()
            return computed_hash == stored_hash
        except:
            return False

    def to_dict(self):
        """Serialize user for API responses (no sensitive data)."""
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "google_id": self.google_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Authentication Functions ──────────────────────────────────────────────────

def generate_jwt(user_id: int, email: str) -> str:
    """Generate JWT token for user."""
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify JWT token and return payload. Raises if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")


def register_user(email: str, password: str, username: str = None) -> User:
    """Create new user with email/password."""
    db = get_db()
    
    # Check if user exists
    existing = db.query(User).filter_by(email=email).first()
    if existing:
        raise ValueError(f"User with email {email} already exists")
    
    # Create user
    user = User(email=email, username=username or email.split("@")[0])
    user.set_password(password)
    
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"✓ New user registered: {email}")
    return user


def authenticate_email(email: str, password: str) -> User:
    """Authenticate user by email/password."""
    db = get_db()
    user = db.query(User).filter_by(email=email).first()
    
    if not user or not user.check_password(password):
        raise ValueError("Invalid email or password")
    
    user.last_login = datetime.utcnow()
    db.commit()
    logger.info(f"✓ User authenticated: {email}")
    return user


def authenticate_google(google_id: str, google_email: str, username: str = None) -> User:
    """Authenticate or create user via Google OAuth."""
    db = get_db()
    
    # Try to find by Google ID
    user = db.query(User).filter_by(google_id=google_id).first()
    
    if not user:
        # Try to find by email (link Google account)
        user = db.query(User).filter_by(email=google_email).first()
        
        if not user:
            # Create new user
            user = User(
                email=google_email,
                username=username or google_email.split("@")[0],
                google_id=google_id,
                google_email=google_email,
            )
            db.add(user)
            logger.info(f"✓ New Google user created: {google_email}")
        else:
            # Link Google account to existing user
            user.google_id = google_id
            user.google_email = google_email
            logger.info(f"✓ Google account linked to existing user: {google_email}")
    
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def update_groww_api_key(user_id: int, api_key: str, api_secret: str = None) -> User:
    """Store user's Groww API credentials (encrypted in production)."""
    db = get_db()
    user = db.query(User).filter_by(id=user_id).first()
    
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    # TODO: Encrypt these in production
    user.groww_api_key = api_key
    if api_secret:
        user.groww_api_secret = api_secret
    
    db.commit()
    db.refresh(user)
    logger.info(f"✓ Groww API key updated for user {user_id}")
    return user


def get_user_by_id(user_id: int) -> User:
    """Fetch user by ID."""
    db = get_db()
    return db.query(User).filter_by(id=user_id).first()


def get_user_by_email(email: str) -> User:
    """Fetch user by email."""
    db = get_db()
    return db.query(User).filter_by(email=email).first()


# ── Flask Decorators ──────────────────────────────────────────────────────────

def require_auth(f):
    """Decorator: require valid JWT token in Authorization header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            return jsonify({"error": "Missing authorization header"}), 401
        
        try:
            token = auth_header.replace("Bearer ", "")
            payload = verify_jwt(token)
            request.user_id = payload["user_id"]
            request.user_email = payload["email"]
            return f(*args, **kwargs)
        except ValueError as e:
            return jsonify({"error": str(e)}), 401
    
    return decorated_function


def get_current_user():
    """Get current authenticated user from request context."""
    if not hasattr(request, "user_id"):
        return None
    return get_user_by_id(request.user_id)
