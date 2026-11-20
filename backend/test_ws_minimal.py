"""
最简 WebSocket 测试应用 — 隔离环境问题
"""
from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """最简单的 WebSocket 端点，无认证，无中间件"""
    print(f"[TEST] WebSocket connection from {websocket.client}")
    await websocket.accept()
    print("[TEST] WebSocket accepted")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[TEST] Received: {data}")
            await websocket.send_text(f"Echo: {data}")
    except Exception as e:
        print(f"[TEST] WebSocket disconnected: {e}")

@app.get("/health")
async def health():
    return PlainTextResponse("ok")

print("[TEST] Minimal WebSocket app loaded")
