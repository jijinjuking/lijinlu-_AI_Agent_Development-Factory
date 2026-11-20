"""
最小 WebSocket 测试应用
用于排查 WebSocket 403 问题
"""
from fastapi import FastAPI, WebSocket

app = FastAPI()


@app.websocket("/ws-test")
async def websocket_test(websocket: WebSocket):
    """最简单的 WebSocket 端点"""
    await websocket.accept()
    print("✅ WebSocket 连接成功（测试应用）")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except Exception as e:
        print(f"WebSocket 断开: {e}")


@app.get("/health")
async def health():
    return {"status": "ok"}
