import json, os, requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

JST = timedelta(hours=9)

# 直接硬编码 Railway 后端地址（不需要在 Vercel 界面设置环境变量了）
ORIGIN_API = "https://wife-received-production.up.railway.app"
NTFY_TOPIC = "wifetest"

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

def ntfy_alert(title="", content=""):
    if not content:
        return "内容为空"
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    msg = f"【{title}】\n{content}"
    try:
        r = requests.post(url, data=msg.encode('utf-8'))
        return "推送成功" if r.status_code == 200 else f"推送失败: {r.status_code}"
    except Exception as e:
        return f"推送异常: {e}"

TOOLS = [
    {"name": "check_on_wife", "description": "查岗老婆的手机活动", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "ntfy_alert", "description": "给老婆手机发推送弹窗", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["content"]}}
]

FUNCS = {"check_on_wife": check_on_wife, "ntfy_alert": ntfy_alert}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "ok", "message": "MCP proxy is running"}

@app.post("/mcp")
async def mcp(req: Request):
    try:
        body = await req.json()
    except:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}}
    
    method = body.get("method")
    params = body.get("params") or {}
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
        try:
            result = FUNCS[name](**args)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": f"执行工具出错: {e}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(result)}]}}
    
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": f"未知方法: {method}"}}
