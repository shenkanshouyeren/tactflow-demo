import os
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

QINIU_AI_URL = "https://api.qnaigc.com/v1/chat/completions"
ALLOWED_ORIGIN = "*"
MAX_INPUT_LENGTH = 10000

SYSTEM_PROMPT = """你是一位专业的合规审查专家。你的任务是：
1. 仔细阅读用户提供的文本内容
2. 从合规角度进行全面审查，识别可能存在的法律风险、合规问题和改进建议
3. 按照以下结构给出你的分析结果：

## 合规评估概览
- 风险等级：[高/中/低]
- 整体评价：[一段话概述]

## 详细分析
### 1. 法律合规性
[分析文本是否符合相关法律法规]

### 2. 内容规范性
[分析文本内容是否规范]

### 3. 风险提示
[指出潜在风险点]

### 4. 改进建议
[给出具体改进建议]

请用专业、客观的语言进行分析，确保每个观点都有依据。"""

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.end_headers()

    def do_POST(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_INPUT_LENGTH + 1000:
            self._send_error(413, "Input too large")
            return
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
            return
        text = data.get("text", "")
        if not text or len(text) > MAX_INPUT_LENGTH:
            self._send_error(400, "Text empty or exceeds limit")
            return
        auth_token = self.headers.get("X-Auth-Token", "")
        shared_secret = os.environ.get("SHARED_SECRET", "")
        if shared_secret and auth_token != shared_secret:
            self._send_error(401, "Unauthorized")
            return
        api_key = os.environ.get("QINIU_API_KEY", "")
        if not api_key:
            self._send_error(500, "API key not configured")
            return
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
        payload = json.dumps({
            "model": "deepseek-r1-0528",
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.3
        }).encode("utf-8")
        req = urllib.request.Request(
            QINIU_AI_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            self._send_success(content)
        except urllib.error.HTTPError as e:
            self._send_error(502, f"AI service error: {e.code}")
        except Exception as e:
            self._send_error(502, f"Request failed: {str(e)}")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))

    def _send_success(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps({"result": content}).encode("utf-8"))

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))
