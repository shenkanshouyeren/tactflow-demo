"""
TactFlow合规路由代理函数 · Vercel Python runtime 版
作用：接收前端请求 → 转发到七牛云AI API → 返回结果
密钥：从环境变量读取，前端不暴露

审计历史：
- 2026-07-31 Kimi 独立安全审计通过（七牛云版）
- 2026-08-02 MiniMAX Vercel 适配（仅 7 项技术差异，不修 Bug A/B，不改 index.html）
- 2026-08-02 Arya 技术守护人审核修正（身份验证顺序+Content-Type转录错误）

适配约束（守夜人 8.2 决策）：
- A. Bug A/B 不修，后续 P1 修（验证先于优化）
- B. ALLOWED_ORIGIN 当前临时 "*"，部署后由守夜人更新为 Vercel 实际域名
- C. vercel.json 不动，Vercel 自动识别 api/*.py

叙事锚点保护：index.html / 钩子文案 / 双国选择器 / 设计元素 不可覆盖
"""

import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# 七牛云AI API接入点
QINIU_AI_URL = "https://api.qnaigc.com/v1/chat/completions"

# 允许的CORS来源
# 当前：临时 "*"（Vercel 完整替代模式，前端+API同源，零CORS问题）
# 部署后：由守夜人手动更新为 Vercel 实际域名
ALLOWED_ORIGIN = "*"

# TactFlow合规路由引擎系统提示词
SYSTEM_PROMPT = """你是TactFlow数据合规路由引擎v1.0。你的唯一任务是：对用户输入的文本进行合规风险扫描和数据脱敏处理。

工作流程：
1. 扫描文本中所有敏感数据字段
2. 根据目标国家的法规判断合规风险等级
3. 对每个字段执行对应脱敏策略
4. 生成脱敏后的完整文本

脱敏策略4级体系：
- L1 REDACT：完全删除，用[REDACTED]替代
- L2 MASK：部分遮蔽（手机号→138****5678，邮箱→z***@example.com）
- L3 HASH：加盐哈希，格式[HASH:6位值]（如张三→[HASH:a3f2c1]）
- L4 TOKENIZE：令牌化，格式[TOKEN:8位值]（如银行卡→[TOKEN:7b2d9f1a]）

CN规则（中国PIPL）：
身份证号→L1 REDACT、手机号→L2 MASK、姓名→L3 HASH、银行卡号→L4 TOKENIZE、邮箱→L2 MASK、地址→L3 HASH

SG规则（新加坡PDPA）：
NRIC→L1 REDACT、手机号→L2 MASK、邮箱→L2 MASK、地址→L3 HASH、姓名→L3 HASH

风险等级：高=违反核心条款可致罚款诉讼、中=合规灰色地带需评估、低=建议性条款可优化

你必须严格输出JSON格式，不要在JSON前后添加任何文字：
{"desensitized_text":"脱敏后完整文本","fields":[{"field_type":"字段类型","original_value":"原始值","desensitized_value":"脱敏值","risk_level":"高/中/低","strategy":"L1/L2/L3/L4","strategy_name":"REDACT/MASK/HASH/TOKENIZE","regulation":"PIPL/PDPA"}],"risk_summary":"一句话风险摘要","compliance_score":0到100的数字}"""


class handler(BaseHTTPRequestHandler):
    """Vercel Python runtime 入口，基于 BaseHTTPRequestHandler

    适配说明（仅 7 项技术差异，不改业务逻辑）：
    1.1 入口：def → class
    1.2 HTTP 方法：event.get('httpMethod') → self.command
    1.3 请求体：event.get('body') → self.rfile.read(length).decode('utf-8')
    1.4 请求头：event.get('headers').get() → self.headers.get()
    1.5 环境变量：context.get('environment', {}).get() → os.environ.get()
    1.6 CORS 头：return dict → self.send_header()
    1.7 错误响应：body=json.dumps() → self.wfile.write(json.dumps().encode('utf-8'))

    Arya审核修正（2处）：
    - 身份验证移到body解析之前（安全顺序修正）
    - do_OPTIONS Content-Type值从'Content-Type'改为'application/json'（转录错误修正）
    """

    # ===== CORS 预检请求处理 =====
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')  # Arya修正：原'Content-Type'为转录错误
        self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Token')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()
        self.wfile.write(b'')

    # ===== 主业务逻辑（POST） =====
    def do_POST(self):
        # ===== 简易身份验证（Arya修正：移到body解析之前） =====
        # 1.4 / 1.5 适配：headers只依赖self.headers，不需要body
        shared_secret = os.environ.get('SHARED_SECRET', '')
        auth_header = self.headers.get('X-Auth-Token', '') or self.headers.get('x-auth-token', '')
        if not shared_secret or auth_header != shared_secret:
            self._send_json(401, {"error": "Unauthorized"})
            return

        # ===== 从环境变量读取API密钥 =====
        api_key = os.environ.get('QINIU_API_KEY', '')
        if not api_key:
            self._send_json(500, {"error": "API密钥未配置，请在控制台设置环境变量QINIU_API_KEY"})
            return

        # ===== 读取请求体（1.3 适配） =====
        try:
            length = int(self.headers.get('Content-Length', 0))
        except (ValueError, TypeError):
            length = 0

        if length <= 0:
            raw_body = '{}'
        else:
            try:
                raw_body = self.rfile.read(length).decode('utf-8')
            except Exception:
                # 与原"请求体JSON格式错误"语义对齐
                self._send_json(400, {"error": "请求体JSON格式错误"})
                return

        # ===== 解析前端请求 =====
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "请求体JSON格式错误"})
            return

        # 提取参数
        input_text = body.get('text', '')
        country = body.get('country', 'CN')
        model = body.get('model', 'deepseek/deepseek-v4-flash')

        if not input_text:
            self._send_json(400, {"error": "请提供待处理的文本(text字段)"})
            return

        # ===== 请求长度限制 =====
        if len(input_text) > 10000:
            self._send_json(400, {"error": "Text too long"})
            return

        # ===== 构建AI API请求 =====
        user_message = f"[目标国家：{country}] 请对以下文本进行合规风险扫描和脱敏处理：\n\n{input_text}"

        ai_request = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 2000,
            "temperature": 0.1
        }

        # ===== 调用七牛云AI API =====
        try:
            req_data = json.dumps(ai_request).encode('utf-8')
            req = urllib.request.Request(
                QINIU_AI_URL,
                data=req_data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                ai_result = json.loads(resp.read().decode('utf-8'))

            # 提取AI回复内容
            content = ai_result['choices'][0]['message']['content']

            # 解析AI输出的JSON（处理可能的markdown包裹）
            # 注：Bug B（解析脆弱）不在本次修复范围
            json_str = content.replace('```json\n', '').replace('```', '').replace('\n```', '').strip()
            try:
                parsed_result = json.loads(json_str)
            except json.JSONDecodeError:
                self._send_json(502, {"error": "Failed to parse AI response"})
                return

            # ===== 字段校验 =====
            # 注：Bug A（字段名不匹配）不在本次修复范围
            required_fields = ['original_text', 'safe_text', 'risk_score']
            if not all(field in parsed_result for field in required_fields):
                self._send_json(502, {"error": "Invalid AI response structure"})
                return

            # ===== 返回结果 =====
            self._send_json(200, {
                "success": True,
                "original_text": input_text,
                "country": country,
                "model": model,
                "result": parsed_result,
                "tokens_used": ai_result.get('usage', {})
            })

        except urllib.error.HTTPError as e:
            error_msg = e.read().decode('utf-8')[:300]
            self._send_json(e.code, {"error": f"AI API调用失败({e.code})", "detail": error_msg})
        except urllib.error.URLError as e:
            self._send_json(503, {"error": f"网络连接失败", "detail": str(e.reason)})
        except Exception as e:
            self._send_json(500, {"error": f"内部错误", "detail": str(e)})

    # ===== 非 POST / OPTIONS 方法返回 405 =====
    def do_GET(self):
        self._send_json(405, {"error": "仅支持POST请求"})

    def do_PUT(self):
        self._send_json(405, {"error": "仅支持POST请求"})

    def do_DELETE(self):
        self._send_json(405, {"error": "仅支持POST请求"})

    def do_PATCH(self):
        self._send_json(405, {"error": "仅支持POST请求"})

    def do_HEAD(self):
        self._send_json(405, {"error": "仅支持POST请求"})

    # ===== 统一 JSON 响应辅助方法 =====
    def _send_json(self, status, body_dict):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Token')
        self.end_headers()
        self.wfile.write(json.dumps(body_dict).encode('utf-8'))
