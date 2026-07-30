import json, os, requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

JST = timedelta(hours=9)
ORIGIN_API = os.environ.get("ORIGIN_API", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def check_on_wife(limit=10):
    try:
        r = requests.get(f"{ORIGIN_API}/activity/summary", timeout=10)
        data = r.json()
    except Exception as e:
        return f"查岗失败: {e}"
    
    apps = data.get("recent_apps", [])
    ses = data.get("sessions", {})
    lines = ["最近打开: " + ", ".join(apps) if apps else "暂无记录"]
    if ses:
        for app, seconds in sorted(ses.items(), key=lambda x: x[1], reverse=True):
            minutes = seconds // 60
            lines.append(f"{app}: {minutes}分钟")
    return "\n".join(lines)

def telegram_alert(title="", content=""):
    if not content:
        return "内容为空"
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return "Telegram 未配置"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"【{title}】\n{content}",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return "推送成功" if r.status_code == 200 else f"推送失败: {r.text}"
    except Exception as e:
        return f"推送异常: {e}"

TOOLS = [
    {
        "name": "check_on_wife",
        "description": "查岗老婆的手机活动",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}
    },
    {
        "name": "telegram_alert",
        "description": "给老婆手机发推送弹窗",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
            "required": ["content"]
        }
    }
]

FUNCS = {"check_on_wife": check_on_wife, "telegram_alert": telegram_alert}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 测试根路由 - 用来验证服务是否正常运行
@app.get("/")
async def root():
    return {"status": "ok", "message": "MCP proxy is running"}

@app.post("/mcp")
async def mcp(req: Request):
    body = await req.json()
    method, params = body.get("method"), body.get("params") or {}
    rid = body.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "查岗MCP", "version": "1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in FUNCS:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "未知工具"}}
        result = FUNCS[name](**args)
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(result)}]}}
    
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": f"未知方法: {method}"}}
