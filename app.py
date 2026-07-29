import os
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

ORIGIN = os.environ.get("ORIGIN_API", "")
BARK_KEY = os.environ.get("BARK_API_KEY", "")

app = FastAPI(title="wife-mcp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def check_on_wife(limit=10):
    try:
        r = requests.get(f"{ORIGIN}/activity/summary", timeout=10)
        data = r.json()
    except Exception as e:
        return f"查询失败: {e}"

    apps = data.get("recent_apps", [])
    sessions = data.get("sessions", {})

    lines = [
        f"最近打开: {', '.join([x['app'] for x in apps]) if apps else '暂无记录'}"
    ]

    for app_name, secs in sessions.items():
        m, s = divmod(secs, 60)
        lines.append(f"{app_name}: {m}分{s}秒")

    return "\n".join(lines)


def bark_alert(title="该上报", content=""):
    if not content:
        return "内容不能为空"

    url = f"https://api.day.app/{BARK_KEY}/{title}/{content}"

    try:
        r = requests.get(url, timeout=10)
        return "推送成功" if r.status_code == 200 else "推送失败"
    except Exception as e:
        return f"推送异常: {e}"


TOOLS = [
    {
        "name": "check_on_wife",
        "description": "查询老婆的手机活动",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"}
            }
        }
    },
    {
        "name": "bark_alert",
        "description": "给老婆发送推送",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["content"]
        }
    }
]


FUNCS = {
    "check_on_wife": check_on_wife,
    "bark_alert": bark_alert
}


@app.post("/mcp")
async def mcp(req: Request):
    body = await req.json()

    method = body.get("method")
    params = body.get("params") or {}
    rid = body.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "查岗MCP",
                    "version": "1.0"
                }
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": TOOLS
            }
        }

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}

        if name not in FUNCS:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {
                    "code": -32601,
                    "message": "未知工具"
                }
            }

        result = FUNCS[name](**args)

        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": str(result)
                    }
                ]
            }
        }

    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {
            "code": -32601,
            "message": f"未知方法: {method}"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )
