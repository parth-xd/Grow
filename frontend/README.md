# Groww Frontend - Next.js Setup Guide

## Project Structure

```
frontend/
├── app/
│   ├── login/          # Login page with Google OAuth
│   ├── setup/          # Setup page for API credentials
│   ├── api/
│   │   └── auth/       # NextAuth.js endpoints
│   ├── layout.tsx      # Root layout
│   └── globals.css     # Global styles
├── components/ui/      # Reusable components
│   └── container-scroll-animation.tsx
├── lib/                # Utilities and config
│   └── auth.ts         # NextAuth configuration
└── public/             # Static assets
```

## Installation & Setup

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Configure Google OAuth

#### Step 1: Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (name it "Groww Trading")
3. Enable "Google+ API" in APIs & Services

#### Step 3: Create OAuth 2.0 Credentials
1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Select **Web application**
4. Add Authorized redirect URIs:
   - `http://localhost:8000/api/auth/callback/google` (development)
   - `https://yourdomain.com/api/auth/callback/google` (production)
5. Copy your **Client ID** and **Client Secret**

#### Step 4: Set Environment Variables
```bash
# Copy the example file
cp .env.local.example .env.local

# Edit .env.local and add:
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
NEXTAUTH_SECRET=$(openssl rand -base64 32)  # Generate random secret
NEXTAUTH_URL=http://localhost:8000
```

### 5. Run Development Server
```bash
npm run dev -- -p 8000
```

Visit `http://localhost:8000/login` in your browser.

## User Flow

1. **Login Page** (`/login`)
   - User clicks "Continue with Google"
   - Redirected to Google OAuth consent screen
   - After auth, redirected to `/setup`

2. **Setup Page** (`/setup`)
   - User enters Groww API credentials
   - Credentials sent to Python backend via `/api/setup`
   - Redirects to main dashboard (`/index.html`)

3. **Dashboard** (`/index.html`)
   - Your existing dashboard HTML file (unchanged)

## Integration with Python Backend

When the user submits API credentials on the setup page, it sends:
```json
{
  "apiKey": "user's api key",
  "apiSecret": "user's api secret",
  "userEmail": "user's google email"
}
```

You'll need to add an endpoint in your Python Flask app:
```python
@app.route('/api/setup', methods=['POST'])
def setup_api():
    data = request.json
    api_key = data.get('apiKey')
    api_secret = data.get('apiSecret')
    user_email = data.get('userEmail')
    
    # Store credentials in database
    # Validate with Groww API
    
    return jsonify({"status": "success"})
```

## Key Features

✅ Google OAuth 2.0 authentication with NextAuth.js
✅ Smooth scroll animations with Framer Motion
✅ TypeScript for type safety
✅ Tailwind CSS for styling
✅ Responsive design (mobile & desktop)
✅ Session management with NextAuth

## Production Deployment

1. Build the app:
```bash
npm run build
npm start
```

2. Update `.env.local` with production Google OAuth credentials
3. Set `NEXTAUTH_URL` to your production domain
4. Deploy to Vercel, AWS, or your preferred platform

## Troubleshooting

**"GOOGLE_CLIENT_ID not set"**
- Make sure `.env.local` exists and has correct values
- Restart dev server after creating `.env.local`

**"Callback URL mismatch"**
- Ensure Google OAuth redirect URI matches your domain + `/api/auth/callback/google`

**"Session not persisting"**
- Generate a new `NEXTAUTH_SECRET` and add to `.env.local`

## Support

For NextAuth.js documentation: https://next-auth.js.org/
For Next.js documentation: https://nextjs.org/docs
