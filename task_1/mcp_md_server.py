import os
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 15):
    raise RuntimeError("Запускайте сервер только на Python 3.15.x.")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

DATA_DIR = Path(os.getenv("MCP_DATA_DIR", str(Path(__file__).with_name("documents")))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROTOCOL = "2025-03-26"
TOOLS = [
    {"name": "list_md_files", "description": "Показать имена Markdown-файлов в локальной папке.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_md_file", "description": "Прочитать содержимое одного Markdown-файла.", "inputSchema": {"type": "object", "properties": {"filename": {"type": "string", "description": "Имя файла, например guide.md"}}, "required": ["filename"], "additionalProperties": False}},
    {"name": "create_md_file", "description": "Создать новый Markdown-файл, не перезаписывая существующий.", "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}, "required": ["filename", "content"], "additionalProperties": False}},
]
app = FastAPI(title="Локальный MCP сервер Markdown")


def safe_path(name):
    if not isinstance(name, str) or not name.endswith(".md") or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Укажите имя одного .md файла без пути.")
    path = (DATA_DIR / name).resolve()
    if path.parent != DATA_DIR:
        raise ValueError("Доступ разрешён только к файлам в папке сервера.")
    return path


def call_tool(name, arguments):
    # Выполняет одну из трёх операций над файлами в каталоге документов.
    if name == "list_md_files":
        files = sorted(p.name for p in DATA_DIR.iterdir() if p.is_file() and p.suffix == ".md" and p.resolve().parent == DATA_DIR)
        return "\n".join(files) if files else "В папке пока нет .md файлов."
    if name == "read_md_file":
        return safe_path(arguments.get("filename", "")).read_text(encoding="utf-8")
    if name == "create_md_file":
        content = arguments.get("content")
        if not isinstance(content, str) or len(content) > 1_000_000:
            raise ValueError("Содержимое должно быть текстом не длиннее 1 МБ.")
        path = safe_path(arguments.get("filename", ""))
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
        return f"Создан файл {path.name}."
    raise ValueError(f"Неизвестный инструмент: {name}")


@app.get("/")
async def health():
    return {"server": "local-markdown-mcp", "endpoint": "/mcp", "protocol": PROTOCOL}


@app.post("/mcp")
async def mcp(request: Request):
    # Обрабатывает MCP JSON-RPC: инициализацию, список инструментов и вызовы.
    packet = await request.json()
    request_id = packet.get("id")
    method = packet.get("method", "")
    if request_id is None:
        return Response(status_code=202)
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "local-markdown", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = packet.get("params", {})
            text = call_tool(params.get("name", ""), params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        else:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as error:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(error)}], "isError": True}}
