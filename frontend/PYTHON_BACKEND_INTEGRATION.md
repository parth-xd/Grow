# Python Backend Integration Example

This file shows how to integrate the setup endpoint in your Flask app.

## Add to your app.py:

```python
from flask import request, jsonify
from flask_cors import CORS  # Install: pip install flask-cors
import os

# Enable CORS to allow requests from Next.js frontend
CORS(app)

@app.route('/api/setup', methods=['POST'])
def setup_api():
    """
    Receive Groww API credentials from frontend and store them.
    
    Expected JSON payload:
    {
        "apiKey": "user's groww api key",
        "apiSecret": "user's groww api secret",
        "userEmail": "user's google email"
    }
    """
    try:
        data = request.json
        api_key = data.get('apiKey')
        api_secret = data.get('apiSecret')
        user_email = data.get('userEmail')
        
        if not all([api_key, api_secret, user_email]):
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
        # 1. Validate API credentials with Groww
        # You can test by making a simple API call:
        # response = requests.get(
        #     'https://api.groww.in/...',
        #     headers={'Authorization': f'Bearer {api_key}'}
        # )
        
        # 2. Store in database or file
        # Option A: Store in JSON file
        import json
        user_config = {
            "email": user_email,
            "api_key": api_key,
            "api_secret": api_secret,
            "timestamp": datetime.now().isoformat()
        }
        
        config_file = f"user_configs/{user_email}.json"
        os.makedirs("user_configs", exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(user_config, f)
        
        # Option B: Store in database (if you have one set up)
        # db.add_user_config(user_email, api_key, api_secret)
        
        return jsonify({"status": "success", "message": "API credentials saved"}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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

## User Config Storage Structure

When saved to JSON, the structure looks like:
```json
{
    "email": "user@gmail.com",
    "api_key": "groww_api_key_xyz",
    "api_secret": "groww_api_secret_abc",
    "timestamp": "2024-04-19T10:30:00.000000"
}
```

## Next Steps

1. Add the `/api/setup` endpoint to your Flask app
2. Test it by submitting the form on the setup page
3. Verify API credentials are being stored
4. Load credentials when user logs back in
5. Use them to fetch trading data from Groww API
