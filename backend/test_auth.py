"""
测试 /auth/register /login /me /refresh 完整流程
使用时间戳生成唯一用户名，避免重复
"""
import urllib.request
import urllib.error
import json
import time
import uuid

# 生成唯一用户名
suffix = str(int(time.time()))[-8:]
username = f"testuser_{suffix}"
email = f"test_{suffix}@example.com"
print(f"Using username: {username}, email: {email}")

# 等待后端就绪
for i in range(20):
    try:
        r = urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=2)
        print(f"Backend ready after {i+1} attempts")
        break
    except Exception:
        if i == 19:
            print("Backend NOT ready, aborting")
            raise SystemExit(1)
        time.sleep(0.5)

print()
print("=== Test 1: /auth/test ===")
r = urllib.request.urlopen('http://127.0.0.1:8002/api/v1/auth/test', timeout=5)
print(f"OK {r.status}: {r.read().decode()}")

print()
print("=== Test 2: POST /auth/register ===")
register_body = json.dumps({
    "username": username,
    "email": email,
    "password": "Test123!",
    "display_name": "Test User"
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8002/api/v1/auth/register",
    data=register_body,
    headers={"Content-Type": "application/json"}
)
try:
    r = urllib.request.urlopen(req, timeout=5)
    resp = json.loads(r.read())
    print(f"OK {r.status}: got tokens")
    token = resp["access_token"]
    refresh_token = resp["refresh_token"]
    print(f"  access_token prefix: {token[:30]}...")
    print(f"  refresh_token prefix: {refresh_token[:30]}...")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"FAIL HTTP {e.code}: {body}")
    raise SystemExit(1)

print()
print("=== Test 3: GET /auth/me (with Bearer token) ===")
req2 = urllib.request.Request(
    "http://127.0.0.1:8002/api/v1/auth/me",
    headers={"Authorization": f"Bearer {token}"}
)
try:
    r2 = urllib.request.urlopen(req2, timeout=5)
    user_info = json.loads(r2.read())
    print(f"OK {r2.status}:")
    print(json.dumps(user_info, indent=2, ensure_ascii=False))
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"FAIL HTTP {e.code}: {body}")
    raise SystemExit(1)

print()
print("=== Test 4: POST /auth/login ===")
login_body = json.dumps({
    "username": username,
    "password": "Test123!"
}).encode()
req3 = urllib.request.Request(
    "http://127.0.0.1:8002/api/v1/auth/login",
    data=login_body,
    headers={"Content-Type": "application/json"}
)
try:
    r3 = urllib.request.urlopen(req3, timeout=5)
    resp3 = json.loads(r3.read())
    print(f"OK {r3.status}: got new tokens")
    token = resp3["access_token"]  # use new token
    print(f"  new access_token prefix: {token[:30]}...")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"FAIL HTTP {e.code}: {body}")
    raise SystemExit(1)

print()
print("=== Test 5: POST /auth/refresh ===")
refresh_body = json.dumps({
    "refresh_token": refresh_token
}).encode()
req4 = urllib.request.Request(
    "http://127.0.0.1:8002/api/v1/auth/refresh",
    data=refresh_body,
    headers={"Content-Type": "application/json"}
)
try:
    r4 = urllib.request.urlopen(req4, timeout=5)
    resp4 = json.loads(r4.read())
    print(f"OK {r4.status}: got refreshed access token")
    print(f"  new access_token prefix: {resp4['access_token'][:30]}...")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"FAIL HTTP {e.code}: {body}")
    raise SystemExit(1)

print()
print("=== Test 6: Wrong password → 401 ===")
login_bad = json.dumps({"username": username, "password": "wrong"}).encode()
req5 = urllib.request.Request(
    "http://127.0.0.1:8002/api/v1/auth/login",
    data=login_bad,
    headers={"Content-Type": "application/json"}
)
try:
    urllib.request.urlopen(req5, timeout=5)
    print("FAIL: should have rejected wrong password!")
    raise SystemExit(1)
except urllib.error.HTTPError as e:
    print(f"OK: correctly rejected with HTTP {e.code}")

print()
print("=== Test 7: No token → 401 ===")
req6 = urllib.request.Request("http://127.0.0.1:8002/api/v1/auth/me")
try:
    urllib.request.urlopen(req6, timeout=5)
    print("FAIL: should have rejected missing token!")
    raise SystemExit(1)
except urllib.error.HTTPError as e:
    print(f"OK: correctly rejected with HTTP {e.code}")

print()
print("=" * 40)
print("ALL AUTH TESTS PASSED!")
