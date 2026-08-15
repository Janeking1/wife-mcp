import json, os, requests
import psycopg2
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

JST = timedelta(hours=9)

# =============================================
# 原有：Railway 后端地址 + ntfy 配置（不动）
# =============================================
ORIGIN_API = "https://wife-received-production.up.railway.app"
NTFY_TOPIC = "wifetest"

# =============================================
# 新增：记忆库数据库连接（硬编码，直接写死）
# =============================================
DATABASE_URL = "postgresql://postgres:pHvLGdbXoYYEJamucchbTkIXmEtbEOZK@autorack.proxy.rlwy.net:39007/railway"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# =============================================
# 原有函数：查岗 + ntfy 推送（完全不动）
# =============================================
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


# =============================================
# 新增：5个记忆库工具函数
# =============================================
def get_kernel():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM core_firmware WHERE id = 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return "未找到内核数据，请先通过录入页面喂入聊天记录"
    # 字段顺序：id, identity, values, taboos, style, safety_rule, updated_at, version
    return f"🧠 内核设定\n身份：{row[1]}\n价值观：{row[2]}\n禁忌：{row[3]}\n说话风格：{row[4]}\n安全尺子：{row[5]}"

def query_memory(keywords=None, layer=None):
    conn = get_db_connection()
    cur = conn.cursor()
    sql = "SELECT * FROM compressed_memory WHERE category IN ('永久', '近况')"
    params = []
    if layer:
        sql += " AND layer = %s"
        params.append(layer)
    if keywords:
        kw_list = keywords.strip().split()
        if kw_list:
            placeholders = ','.join(['%s'] * len(kw_list))
            sql += f" AND trigger_keywords && ARRAY[{placeholders}]"
            params.extend(kw_list)
    sql += " ORDER BY hotness DESC, generated_date DESC LIMIT 20"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return "没有找到匹配的记忆"
    lines = []
    for row in rows:
        # 字段顺序：id, category, layer, content, generated_date, hotness, retention_score, trigger_keywords, needs_confirmation
        lines.append(f"[{row[2]}] {row[3]}（热度：{row[5]}，录入：{row[4]}）")
    return "\n".join(lines)

def get_todos():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM todos WHERE due_date >= CURRENT_DATE ORDER BY due_date ASC LIMIT 30")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return "今天没有待办事项 ✅"
    lines = []
    for row in rows:
        lines.append(f"📌 {row[1]}（截止：{row[2]}）")
    return "\n".join(lines)

def get_emotion(days=7):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM emotion_curve WHERE record_date >= CURRENT_DATE - %s ORDER BY record_date DESC", (days,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return f"最近 {days} 天没有情绪记录"
    lines = []
    for row in rows:
        # 字段顺序：id, record_date, mood_tag, reason, created_at
        reason_text = f"（{row[3]}）" if row[3] else ""
        lines.append(f"{row[1]}：{row[2]}{reason_text}")
    return "\n".join(lines)

def get_relationship():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM relationship WHERE id = 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return "未找到关系数据"
    # 字段顺序：id, ai_nickname, user_nickname, stage, milestones, last_auto_trigger_date, updated_at
    return f"👫 关系状态\nAI叫你：{row[1] or '未设置'}\n你叫AI：{row[2] or '未设置'}\n阶段：{row[3] or '刚认识'}\n里程碑：{row[4] or '无'}"


# =============================================
# MCP 工具列表（原有2个 + 新增5个 = 7个）
# =============================================
TOOLS = [
    # ---- 原有 ----
    {"name": "check_on_wife", "description": "查岗老婆的手机活动", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "ntfy_alert", "description": "给老婆手机发推送弹窗", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["content"]}},
    # ---- 新增记忆库 ----
    {"name": "get_kernel", "description": "获取AI的核心人格设定（身份、价值观、禁忌、说话风格、安全尺子）", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query_memory", "description": "根据关键词或层级查询压缩记忆库，返回匹配的记忆条目", "inputSchema": {"type": "object", "properties": {"keywords": {"type": "string"}, "layer": {"type": "string", "enum": ["事实","协议","状态","身体","情感","根"]}}}},
    {"name": "get_todos", "description": "查询今天的待办事项", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_emotion", "description": "查询最近的情绪记录", "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}},
    {"name": "get_relationship", "description": "获取你和AI之间的关系状态", "inputSchema": {"type": "object", "properties": {}}},
]

FUNCS = {
    "check_on_wife": check_on_wife,
    "ntfy_alert": ntfy_alert,
    "get_kernel": get_kernel,
    "query_memory": query_memory,
    "get_todos": get_todos,
    "get_emotion": get_emotion,
    "get_relationship": get_relationship,
}


# =============================================
# FastAPI 应用（完全不动）
# =============================================
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

@app.get("/cron/check_and_push")
async def cron_check_and_push():
    result = check_on_wife(limit=10)
    push_result = ntfy_alert("📱 定时查岗", result)
    return {"status": "ok", "message": result, "push": push_result}
