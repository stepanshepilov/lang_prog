import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if sys.version_info[:2] != (3, 15):
    raise RuntimeError("Запускайте сервер только на Python 3.15.x.")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
API_KEY = os.getenv("LLM_API_KEY", "")
API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4.1-flash")
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")
RPC_ID = 0
SYSTEM = "Ты полезный русскоязычный помощник. Для вопросов о локальных заметках используй MCP-инструменты."
app = FastAPI(title="Локальный AI чат")


def post_json(url, payload, headers=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    request = urllib.request.Request(url, json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def send_notification(url, payload, headers):
    request = urllib.request.Request(url, json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=30):
        pass


def mcp_headers():
    return {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


async def mcp_call(method, params=None):
    global RPC_ID
    RPC_ID += 1
    payload = {"jsonrpc": "2.0", "id": RPC_ID, "method": method, "params": params or {}}
    response = await asyncio.to_thread(post_json, MCP_URL, payload, mcp_headers())
    if "error" in response:
        raise RuntimeError(response["error"].get("message", "Ошибка MCP"))
    return response.get("result", {})


async def mcp_notify(method):
    payload = {"jsonrpc": "2.0", "method": method}
    await asyncio.to_thread(send_notification, MCP_URL, payload, mcp_headers())


async def complete(messages, tools):
    if not API_KEY:
        raise RuntimeError("Задайте ключ API в переменной окружения LLM_API_KEY.")
    payload = {"model": MODEL, "messages": messages, "temperature": 0.3}
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    data = await asyncio.to_thread(post_json, API_URL, payload, {"Authorization": f"Bearer {API_KEY}"})
    return data["choices"][0]["message"]


@app.get("/")
async def home():
    return FileResponse(ROOT / "index.html")


@app.websocket("/ws")
async def chat(websocket: WebSocket):
    await websocket.accept()
    history = [{"role": "system", "content": SYSTEM}]
    # Инициализирует MCP и преобразует его инструменты в формат LLM.
    try:
        await mcp_call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "task-1-chat", "version": "1.0"}})
        await mcp_notify("notifications/initialized")
        available = (await mcp_call("tools/list")).get("tools", [])
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}} for t in available]
        await websocket.send_json({"type": "status", "text": f"MCP подключён · {len(tools)} инструмента"})
    except Exception as error:
        tools = []
        await websocket.send_json({"type": "status", "text": f"MCP недоступен: {str(error)[:180]}"})
    # Ведёт историю диалога и выполняет запрошенные моделью вызовы MCP.
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("clear"):
                history = [{"role": "system", "content": SYSTEM}]
                await websocket.send_json({"type": "reset"})
                continue
            prompt = data.get("message", "").strip()
            if not prompt:
                continue
            history.append({"role": "user", "content": prompt})
            await websocket.send_json({"type": "status", "text": "Думаю…"})
            try:
                for _ in range(4):
                    message = await complete(history, tools)
                    history.append(message)
                    calls = message.get("tool_calls") or []
                    legacy = not calls and message.get("function_call")
                    if legacy:
                        calls = [{"id": "legacy", "function": message["function_call"]}]
                    if not calls:
                        await websocket.send_json({"type": "message", "text": message.get("content") or ""})
                        await websocket.send_json({"type": "status", "text": "Готово"})
                        break
                    for call in calls:
                        function = call["function"]
                        name = function["name"]
                        await websocket.send_json({"type": "status", "text": f"Локальный MCP: {name}"})
                        try:
                            args = json.loads(function.get("arguments") or "{}")
                            result = await mcp_call("tools/call", {"name": name, "arguments": args})
                            output = "\n".join(item.get("text", "") for item in result.get("content", []))
                        except Exception as error:
                            output = str(error)
                        if legacy:
                            history.append({"role": "function", "name": name, "content": output})
                        else:
                            history.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": output})
                else:
                    await websocket.send_json({"type": "error", "text": "Слишком много вызовов MCP для одного ответа."})
            except Exception as error:
                await websocket.send_json({"type": "error", "text": str(error)[:600]})
                await websocket.send_json({"type": "status", "text": "Ошибка"})
    except WebSocketDisconnect:
        pass
