# Python Backend Integration Example

This file shows how to integrate the setup endpoint in your Flask app.

## Add to your app.py:

```python
from flask import request, jsonify
from flask_cors import CORS  # Install: pip install flask-cors
import os
from auth_manager import require_auth, get_current_user, update_groww_api_key

# Enable CORS to allow requests from Next.js frontend
CORS(app)

@app.route('/api/auth/set-api-key', methods=['POST'])
@require_auth
def api_set_api_key():
    """
    Receive Groww API credentials from the frontend and store them.
    
    Expected JSON payload:
    {
        "api_key": "user's groww api key",
        "api_secret": "user's groww api secret"
    }
    """
    try:
        data = request.json
        api_key = data.get('api_key')
        api_secret = data.get('api_secret')
        
        if not api_key:
            return jsonify({"error": "API key required"}), 400
        
        # Store the API credentials for the authenticated user.
        user = get_current_user()
        update_groww_api_key(user.id, api_key, api_secret or None)
        
        return jsonify({"message": "API key saved successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Optional: Add a route to retrieve user config
@app.route('/api/user-config/<email>', methods=['GET'])
def get_user_config(email):
    """Get stored API config for a user (after verification)"""
    try:
        config_file = f"user_configs/{email}.json"
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                return jsonify(config), 200
        else:
            return jsonify({"status": "error", "message": "No config found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
```

## Installation Requirements

Add to your requirements.txt:
```
flask-cors>=4.0.0
requests>=2.31.0
```

Then run:
```bash
pip install -r requirements.txt
```

## CORS Configuration

If you're deploying Next.js and Flask on different ports/domains, 
ensure CORS is properly configured:

```python
from flask_cors import CORS

# Allow requests from Next.js frontend
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:3000",  # Development
            "https://yourdomain.com"   # Production
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})
```

## Notes

- The Flask route is authenticated (`@require_auth`), so the frontend must send a valid session/JWT.
- If your setup page still posts to `/api/setup`, update it to call `/api/auth/set-api-key` instead.

## Next Steps

1. Expose `/api/auth/set-api-key` in your Flask app
2. Wire the setup form to call that route
3. Verify API credentials are being stored
4. Load credentials when user logs back in
5. Use them to fetch trading data from Groww API
