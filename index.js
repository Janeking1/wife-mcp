const express = require('express');
const app = express();
app.use(express.json());

// 模拟数据库存储
let records = [];

// MCP端点 - 初始化
app.post('/mcp', (req, res) => {
  const { method, id } = req.body;

  if (method === 'initialize') {
    return res.json({
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'wife-mcp', version: '1.0.0' }
      }
    });
  }

  if (method === 'tools/list') {
    return res.json({
      jsonrpc: '2.0',
      id,
      result: {
        tools: [
          {
            name: 'get_current_time',
            description: '获取当前时间',
            inputSchema: { type: 'object', properties: {} }
          },
          {
            name: 'get_activity_summary',
            description: '获取应用使用情况',
            inputSchema: { type: 'object', properties: {} }
          }
        ]
      }
    });
  }

  if (method === 'tools/call') {
    const { name } = req.body.params;

    if (name === 'get_current_time') {
      const now = new Date();
      return res.json({
        jsonrpc: '2.0',
        id,
        result: {
          content: [{ type: 'text', text: now.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }]
        }
      });
    }

    if (name === 'get_activity_summary') {
      return res.json({
        jsonrpc: '2.0',
        id,
        result: {
          content: [{ type: 'text', text: '暂无记录' }]
        }
      });
    }

    return res.json({
      jsonrpc: '2.0',
      id,
      error: { code: -32601, message: '未知工具' }
    });
  }

  return res.json({
    jsonrpc: '2.0',
    id,
    error: { code: -32601, message: '未知方法' }
  });
});

// 兼容原有路径
app.post('/report', (req, res) => {
  const { app_name, event } = req.body;
  records.push({ app_name, event, timestamp: new Date().toISOString() });
  res.json({ status: 'ok' });
});

app.get('/activity/summary', (req, res) => {
  const recent = records.slice(-5).map(r => r.app_name);
  res.json({ recent_apps: recent, sessions: {} });
});

app.get('/ping', (req, res) => res.send('pong'));

module.exports = app;
