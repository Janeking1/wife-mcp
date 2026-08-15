import json, os, requests
import psycopg2
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

JST = timedelta(hours=9)

# =============================================
# 原有配置（不动）
# =============================================
ORIGIN_API = "https://wife-received-production.up.railway.app"
NTFY_TOPIC = "wifetest"

# =============================================
# 记忆库数据库连接（硬编码）
# =============================================
DATABASE_URL = "postgresql://postgres:pHvLGdbXoYYEJamucchbTkIXmEtbEOZK@autorack.proxy.rlwy.net:39007/railway"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ---------- 待确认队列（全局列表，仅在内存中暂存，重启丢失，适合调试） ----------
pending_sqls = []

# =============================================
# 原有函数：查岗 + ntfy 推送
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
# 新增：5个记忆库只读工具（跟之前一样）
# =============================================
def get_kernel():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM core_firmware WHERE id = 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return "未找到内核数据"
    return f"身份：{row[1]}\n价值观：{row[2]}\n禁忌：{row[3]}\n风格：{row[4]}\n安全尺子：{row[5]}"

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
    return f"AI叫你：{row[1] or '未设置'}\n你叫AI：{row[2] or '未设置'}\n阶段：{row[3] or '刚认识'}\n里程碑：{row[4] or '无'}"

# =============================================
# 新增：通用 SQL 执行 + 内核修改确认
# =============================================
def run_sql(sql_query):
    """
    执行 SQL，支持 SELECT / UPDATE / INSERT / DELETE，
    但任何涉及 core_firmware 的写操作会被拦截，存入待确认队列。
    """
    sql_clean = sql_query.strip()
    if not sql_clean:
        return "❌ SQL 不能为空"

    # 安全拦截：只允许 SELECT, UPDATE, INSERT, DELETE
    allowed_commands = ["SELECT", "UPDATE", "INSERT", "DELETE"]
    if not any(sql_clean.upper().startswith(cmd) for cmd in allowed_commands):
        return "❌ 只允许 SELECT、UPDATE、INSERT、DELETE 操作"

    # 禁止危险命令（DROP / TRUNCATE / ALTER / CREATE 等）
    dangerous = ["DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"]
    for kw in dangerous:
        if kw in sql_clean.upper():
            return f"❌ 禁止使用 {kw} 操作"

    # 检查是否涉及 core_firmware 的写操作（UPDATE/INSERT/DELETE）
    is_kernel_write = False
    lower_sql = sql_clean.lower()
    if "core_firmware" in lower_sql:
        if sql_clean.upper().startswith("UPDATE") or sql_clean.upper().startswith("INSERT") or sql_clean.upper().startswith("DELETE"):
            is_kernel_write = True

    if is_kernel_write:
        # 存入待确认队列
        pending_sqls.append(sql_clean)
        return "⚠️ 内核修改已暂存，需要你确认。请调用 confirm_kernel_update 工具来执行。"

    # 其他操作直接执行
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql_clean)
        if sql_clean.upper().startswith("SELECT"):
            rows = cur.fetchall()
            cur.close()
            conn.close()
            if not rows:
                return "查询结果为空"
            return "\n".join([str(row) for row in rows])
        else:
            conn.commit()
            affected = cur.rowcount
            cur.close()
            conn.close()
            return f"✅ 执行成功，影响了 {affected} 条记录"
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return f"❌ SQL 执行失败: {e}"

def confirm_kernel_update():
    """执行所有待确认的内核修改"""
    if not pending_sqls:
        return "没有待确认的内核更新"
    conn = get_db_connection()
    cur = conn.cursor()
    executed = []
    errors = []
    for sql in pending_sqls:
        try:
            cur.execute(sql)
            conn.commit()
            executed.append(sql)
        except Exception as e:
            conn.rollback()
            errors.append(f"{sql} -> {e}")
    cur.close()
    conn.close()
    pending_sqls.clear()
    if errors:
        return f"部分执行失败: {'; '.join(errors)}。成功执行的: {len(executed)} 条。"
    return f"✅ 成功执行 {len(executed)} 条内核更新，已生效。"

# =============================================
# MCP 工具列表（原有2个 + 5个只读 + 2个新增 = 9个）
# =============================================
TOOLS = [
    # 原有
    {"name": "check_on_wife", "description": "查岗老婆的手机活动", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "ntfy_alert", "description": "给老婆手机发推送弹窗", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["content"]}},
    # 记忆库只读
    {"name": "get_kernel", "description": "获取AI的核心人格设定", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query_memory", "description": "根据关键词或层级查询压缩记忆库", "inputSchema": {"type": "object", "properties": {"keywords": {"type": "string"}, "layer": {"type": "string", "enum": ["事实","协议","状态","身体","情感","根"]}}}},
    {"name": "get_todos", "description": "查询今天的待办事项", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_emotion", "description": "查询最近的情绪记录", "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}},
    {"name": "get_relationship", "description": "获取你和AI之间的关系状态", "inputSchema": {"type": "object", "properties": {}}},
    # 新增 SQL 工具
    {"name": "run_sql", "description": "执行 SQL 查询或修改（支持 SELECT/UPDATE/INSERT/DELETE），但修改内核表 core_firmware 的操作会被暂存，需调用 confirm_kernel_update 确认", "inputSchema": {"type": "object", "properties": {"sql_query": {"type": "string"}}, "required": ["sql_query"]}},
    {"name": "confirm_kernel_update", "description": "确认并执行所有待确认的内核修改", "inputSchema": {"type": "object", "properties": {}}},
]

FUNCS = {
    "check_on_wife": check_on_wife,
    "ntfy_alert": ntfy_alert,
    "get_kernel": get_kernel,
    "query_memory": query_memory,
    "get_todos": get_todos,
    "get_emotion": get_emotion,
    "get_relationship": get_relationship,
    "run_sql": run_sql,
    "confirm_kernel_update": confirm_kernel_update,
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
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "记忆库MCP", "version": "1.0"}}}
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
