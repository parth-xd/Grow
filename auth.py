"""
Authentication module for multi-user SaaS

Features:
- Google OAuth integration
- JWT token generation and validation
- User session management
- Secure password handling
"""

import os
import jwt
import json
from datetime import datetime, timedelta
from functools import wraps
from cryptography.fernet import Fernet
import requests
from flask import request, jsonify, current_app
from sqlalchemy import text

# Configuration
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret-key-change-in-production')
JWT_EXPIRATION_HOURS = 24
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
# Support both GOOGLE_REDIRECT_URI and derive from FLASK_HOST/PORT
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI')
if not GOOGLE_REDIRECT_URI:
    FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = os.getenv('PORT', os.getenv('FLASK_PORT', '5000'))
    # For production, use environment-provided host; for local dev use localhost
    if FLASK_HOST == '0.0.0.0':
        GOOGLE_REDIRECT_URI = f'http://localhost:{FLASK_PORT}/api/auth/google/callback'
    else:
        GOOGLE_REDIRECT_URI = f'http://{FLASK_HOST}:{FLASK_PORT}/api/auth/google/callback'

# Encryption for API keys
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if ENCRYPTION_KEY:
    cipher = Fernet(ENCRYPTION_KEY.encode())
else:
    cipher = None

class AuthManager:
    """Handle authentication and user management"""
    
    def __init__(self, db):
        """
        Args:
            db: SQLAlchemy database instance
        """
        self.db = db
    
    def generate_jwt(self, user_id, email):
        """Generate JWT token for user"""
        payload = {
            'user_id': str(user_id),
            'email': email,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
        return token
    
    def verify_jwt(self, token):
        """Verify JWT token and return user info"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def get_user_from_token(self, token):
        """Get user object from JWT token"""
        payload = self.verify_jwt(token)
        if not payload:
            return None
        
        # Query database for user
        result = self.db.session.execute(text("""
            SELECT id, email, name, is_admin FROM users 
            WHERE id = :user_id AND is_active = TRUE
        """), {'user_id': payload['user_id']})
        
        user = result.fetchone()
        if user:
            return {
                'id': user[0],
                'email': user[1],
                'name': user[2],
                'is_admin': user[3]
            }
        return None
    
    def authenticate_google(self, auth_code):
        """
        Exchange Google auth code for user info
        
        Returns:
            {
                'id': google_id,
                'email': email,
                'name': name,
                'picture': profile_picture_url
            }
        """
        try:
            # Exchange code for token with Google
            token_url = 'https://oauth2.googleapis.com/token'
            token_data = {
                'code': auth_code,
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'redirect_uri': GOOGLE_REDIRECT_URI,
                'grant_type': 'authorization_code'
            }
            
            token_response = requests.post(token_url, data=token_data)
            token_response.raise_for_status()
            token_json = token_response.json()
            
            id_token = token_json.get('id_token')
            
            # Decode ID token to get user info
            user_info = jwt.decode(id_token, options={"verify_signature": False})
            
            return {
                'id': user_info.get('sub'),
                'email': user_info.get('email'),
                'name': user_info.get('name'),
                'picture': user_info.get('picture')
            }
        
        except Exception as e:
            print(f"Google auth error: {e}")
            return None
    
    def get_or_create_user(self, google_info):
        """Get or create user from Google info"""
        
        # Check if user exists
        result = self.db.session.execute(text("""
            SELECT id, email, name FROM users 
            WHERE google_id = :google_id
        """), {'google_id': google_info['id']})
        
        user = result.fetchone()
        
        if user:
            # Update last login
            self.db.session.execute(text("""
                UPDATE users SET last_login = CURRENT_TIMESTAMP
                WHERE id = :user_id
            """), {'user_id': user[0]})
            self.db.session.commit()
            
            return {
                'id': user[0],
                'email': user[1],
                'name': user[2]
            }
        
        else:
            # Create new user
            import uuid
            user_id = str(uuid.uuid4())
            
            self.db.session.execute(text("""
                INSERT INTO users (id, google_id, email, name, profile_picture_url, is_active)
                VALUES (:id, :google_id, :email, :name, :picture, TRUE)
            """), {
                'id': user_id,
                'google_id': google_info['id'],
                'email': google_info['email'],
                'name': google_info['name'],
                'picture': google_info.get('picture')
            })
            
            # Create user settings
            self.db.session.execute(text("""
                INSERT INTO user_settings (user_id)
                VALUES (:user_id)
            """), {'user_id': user_id})
            
            self.db.session.commit()
            
            return {
                'id': user_id,
                'email': google_info['email'],
                'name': google_info['name']
            }
    
    def encrypt_api_key(self, api_key):
        """Encrypt API key for storage"""
        if not cipher:
            raise ValueError("ENCRYPTION_KEY not configured")
        return cipher.encrypt(api_key.encode()).decode()
    
    def decrypt_api_key(self, encrypted_key):
        """Decrypt API key from storage"""
        if not cipher:
            raise ValueError("ENCRYPTION_KEY not configured")
        try:
            return cipher.decrypt(encrypted_key.encode()).decode()
        except:
            return None
    
    def save_api_credentials(self, user_id, api_key, api_secret):
        """Save encrypted API credentials"""
        
        encrypted_key = self.encrypt_api_key(api_key)
        encrypted_secret = self.encrypt_api_key(api_secret)
        
        # Upsert credentials
        self.db.session.execute(text("""
            INSERT INTO api_credentials (user_id, encrypted_groww_api_key, encrypted_groww_secret)
            VALUES (:user_id, :key, :secret)
            ON CONFLICT (user_id) DO UPDATE SET
                encrypted_groww_api_key = :key,
                encrypted_groww_secret = :secret,
                updated_at = CURRENT_TIMESTAMP
        """), {
            'user_id': user_id,
            'key': encrypted_key,
            'secret': encrypted_secret
        })
        
        self.db.session.commit()
        return True
    
    def get_api_credentials(self, user_id):
        """Get decrypted API credentials for user"""
        result = self.db.session.execute(text("""
            SELECT encrypted_groww_api_key, encrypted_groww_secret
            FROM api_credentials
            WHERE user_id = :user_id
        """), {'user_id': user_id})
        
        row = result.fetchone()
        if not row:
            return None
        
        try:
            api_key = self.decrypt_api_key(row[0])
            api_secret = self.decrypt_api_key(row[1])
            return {'api_key': api_key, 'api_secret': api_secret}
        except:
            return None
    
    def has_api_credentials(self, user_id):
        """Check if user has saved API credentials"""
        result = self.db.session.execute(text("""
            SELECT COUNT(*) FROM api_credentials WHERE user_id = :user_id
        """), {'user_id': user_id})
        
        count = result.scalar()
        return count > 0


def token_required(f):
    """Decorator: Verify JWT token on protected routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(' ')[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Missing authentication token'}), 401
        
        # Verify token
        auth_manager = AuthManager(current_app.db)
        user = auth_manager.get_user_from_token(token)
        
        if not user:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Pass user to route
        request.user = user
        return f(*args, **kwargs)
    
    return decorated


def admin_required(f):
    """Decorator: Verify user is admin"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(request, 'user') or not request.user.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated
