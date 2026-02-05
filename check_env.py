import os
from dotenv import load_dotenv

# Get the directory where this script is located (backend/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")

print(f"Trying to load .env from: {env_path}")
print(f"File exists: {os.path.exists(env_path)}")

load_dotenv(env_path)

google_key = os.getenv("GOOGLE_API_KEY")
naver_id = os.getenv("NAVER_CLIENT_ID")
naver_secret = os.getenv("NAVER_CLIENT_SECRET")

print(f"GOOGLE_API_KEY loaded: {google_key is not None}")
if google_key:
    print(f"GOOGLE_API_KEY prefix: {google_key[:5]}...")

print(f"NAVER_CLIENT_ID loaded: {naver_id is not None}")
print(f"NAVER_CLIENT_SECRET loaded: {naver_secret is not None}")
