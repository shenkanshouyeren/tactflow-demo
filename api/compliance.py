"""
TactFlow合规路由代理函数 · Vercel Python runtime版
"""

import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

QINIU_AI_URL = "https://api.qnaigc.com/v1/chat/completions"
ALLOWED_ORIGIN = "*"

SYSTEM_PROMPT = """你是TactFlow数据合规路由引擎v1.0。你的唯一任务是：对用户输入的文本进行合规风险扫描和数据脱敏处理。

工作流程：
1. 扫描文本中所有敏感数据字段
2. 根据目标国家的法规判断合规风险等级
3. 对每个字段执行对应脱敏策略
4. 生成脱敏后的完整文本

脱敏策略4级体系：
- L1 REDACT：完全删除，用[REDACTED]替代
- L2 MASK：部分遮蔽（手机号→138****5678，邮箱→z***@example.com）
- L3 HASH：加盐哈希，格式[HASH:6位值]
- L4 TOKENIZE：令牌化，格式[TOKEN:8位值]

CN规则（中国PIPL）：
身份证号→L1 REDACT、手机号→L2 MASK、姓名→L3 HASH、银行卡号→L4 TOKENIZE、邮箱→L2 MASK、地址→L3 HASH

SG规则（新加坡PDPA）：
NRIC→L1 REDACT、手机号→L2 MASK、邮箱→L2 MASK、地址→L3 HASH、姓名→L3 HASH

风险等级：高=违反核心条款可致罚款诉讼、中=合规灰色地带需评估、低=建议性条款可优化

输出JSON格式：
{"desensitized_text":"脱敏后完整文本","fields":[{"field_type":"字段类型","original_value":"原始值","desensitized_value":"脱敏值","risk_level":"高/中/低","strategy":"L1/L2/L3/L4","strategy_name":"REDACT/MASK/HASH/TOKENIZE","regulation":"PIPL/PDPA"}],"risk_summary":"一句话风险摘要","compliance_score":0到100的数字}"""


def build_cors_headers():
    return {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Auth-Token",
        "Access-Control-Max-Age": "86400"
    }


def send_json_response(self, status_code, data):
    self.send_response(status_code)
    for key, value in build_cors_headers().items():
        self.send_header(key, value)
    self.send_header("Content-Type", "application/json")
    self.end_headers()
    self.wfile.write(json.dumps(data).encode("utf-8"))


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        for key, value in build_cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_GET(self):
        send_json_response(self, 200, {"service": "TactFlow合规路由代理", "status": "running", "version": "v1.0-vercel"})

    def do_POST(self):
        shared_secret = os.environ.get("SHARED_SECRET", "")
        token = self.headers.get("X-Auth-Token", "") or self.headers.get("x-auth-token", "")
        if shared_secret and token != shared_secret:
            send_json_response(self, 401, {"error": "Unauthorized"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            send_json_response(self, 400, {"error": "请求体为空"})
            return

        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            send_json_response(self, 400, {"error": "请求体JSON格式错误"})
            return

        input_text = body.get("text", "")
        country = body.get("country", "CN")
        model = body.get("model", "deepseek/deepseek-v4-flash")

        if not input_text:
            send_json_response(self, 400, {"error": "请提供待处理的文本(text字段)"})
            return

        if len(input_text) > 10000:
            send_json_response(self, 400, {"error": "Text too long"})
            return

        api_key = os.environ.get("QINIU_API_KEY", "")
        if not api_key:
            send_json_response(self, 500, {"error": "API密钥未配置，请在Vercel环境变量中设置QINIU_API_KEY"})
            return

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

        try:
            req_data = json.dumps(ai_request).encode("utf-8")
            req = urllib.request.Request(
                QINIU_AI_URL,
                data=req_data,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                ai_result = json.loads(resp.read().decode("utf-8"))

            content = ai_result["choices"][0]["message"]["content"]
            json_str = content.replace("```json\n", "").replace("```", "").replace("\n```", "").strip()
            try:
                parsed_result = json.loads(json_str)
            except json.JSONDecodeError:
                send_json_response(self, 502, {"error": "Failed to parse AI response"})
                return

            required_fields = ["desensitized_text", "fields", "risk_summary", "compliance_score"]
            if not all(field in parsed_result for field in required_fields):
                send_json_response(self, 502, {"error": "Invalid AI response structure"})
                return

            send_json_response(self, 200, {
                "success": True,
                "original_text": input_text,
                "country": country,
                "model": model,
                "result": parsed_result,
                "tokens_used": ai_result.get("usage", {})
            })

        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8")[:300]
            send_json_response(self, e.code, {"error": f"AI API调用失败({e.code})", "detail": error_msg})
        except urllib.error.URLError as e:
            send_json_response(self, 503, {"error": "网络连接失败", "detail": str(e.reason)})
        except Exception as e:
            send_json_response(self, 500, {"error": "内部错误", "detail": str(e)})

    def log_message(self, format, *args):
        pass
