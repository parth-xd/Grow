#!/usr/bin/env python3
"""
Utility to generate a Groww API access token.

This is a ONE-TIME setup script. Run it once to get your access token,
then paste it into your .env file as GROWW_ACCESS_TOKEN=<token>.

Credentials are read from environment variables:
  GROWW_API_KEY   — your Groww API key (JWT)
  GROWW_API_SECRET — your Groww API secret
"""
import os
from dotenv import load_dotenv
from growwapi import GrowwAPI

load_dotenv()

api_key = os.getenv("GROWW_API_KEY")
secret = os.getenv("GROWW_API_SECRET")

if not api_key or not secret:
    print("✗ Missing credentials. Set these in your .env file:")
    print("  GROWW_API_KEY=<your-api-key>")
    print("  GROWW_API_SECRET=<your-api-secret>")
    exit(1)

print("Generating Groww access token...\n")
try:
    token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
    print(f"✓ SUCCESS! Your access token:\n\n{token}\n")
    print("Copy this and paste into .env as:\nGROWW_ACCESS_TOKEN=" + token)
except Exception as e:
    print(f"✗ Error: {e}")
