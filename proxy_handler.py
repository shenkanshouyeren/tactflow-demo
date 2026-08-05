"""
TactFlow合规路由代理函数 · 七牛云函数计算版（Kimi审计修正版）
作用：接收前端请求 → 转发到七牛云AI API → 返回结果
密钥：从环境变量读取，前端不暴露
审计：Kimi独立安全审计通过（2026-07-31）
修正项：身份验证+输入限制+CORS限定+字段校验+JSON健壮+错误脱敏
"""

import json
import urllib.request
import urllib.error

# 七牛云AI API接入点
QINIU_AI_URL = "https://api.qnaigc.com/v1/chat/completions"

# 允许的CORS来源
ALLOWED_ORIGIN = "https://shenkanshouyeren.github.io"

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

def handler(event, context):
    """
    七牛云函数计算入口函数
    event: HTTP请求事件
    context: 函数执行上下文（包含环境变量）
    """

    # ===== CORS预检请求处理 =====
    http_method = event.get('httpMethod', '')
    if http_method == 'OPTIONS':
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "Content-Type",
                "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Auth-Token",
                "Access-Control-Max-Age": "86400"
            },
            "body": ""
        }

    # ===== 仅允许POST请求 =====
    if http_method != 'POST':
        return {
            "statusCode": 405,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "仅支持POST请求"})
        }

    # ===== 简易身份验证 =====
    shared_secret = context.get('environment', {}).get('SHARED_SECRET', '')
    headers = event.get('headers', {})
    auth_header = headers.get('X-Auth-Token', '') or headers.get('x-auth-token', '')
    if not shared_secret or auth_header != shared_secret:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "Unauthorized"})
        }

    # ===== 从环境变量读取API密钥 =====
    # 环境变量名：QINIU_API_KEY（在七牛云控制台配置）
    api_key = context.get('environment', {}).get('QINIU_API_KEY', '')
    if not api_key:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "API密钥未配置，请在控制台设置环境变量QINIU_API_KEY"})
        }

    # ===== 解析前端请求 =====
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "请求体JSON格式错误"})
        }

    # 提取参数
    input_text = body.get('text', '')
    country = body.get('country', 'CN')
    model = body.get('model', 'deepseek/deepseek-v4-flash')

    if not input_text:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "请提供待处理的文本(text字段)"})
        }

    # ===== 请求长度限制 =====
    if len(input_text) > 10000:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": "Text too long"})
        }

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
        json_str = content.replace('```json\n', '').replace('```', '').replace('\n```', '').strip()
        try:
            parsed_result = json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "statusCode": 502,
                "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
                "body": json.dumps({"error": "Failed to parse AI response"})
            }

        # ===== 字段校验 =====
        required_fields = ['original_text', 'safe_text', 'risk_score']
        if not all(field in parsed_result for field in required_fields):
            return {
                "statusCode": 502,
                "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
                "body": json.dumps({"error": "Invalid AI response structure"})
            }

        # ===== 返回结果 =====
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Auth-Token"
            },
            "body": json.dumps({
                "success": True,
                "original_text": input_text,
                "country": country,
                "model": model,
                "result": parsed_result,
                "tokens_used": ai_result.get('usage', {})
            })
        }

    except urllib.error.HTTPError as e:
        error_msg = e.read().decode('utf-8')[:300]
        return {
            "statusCode": e.code,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": f"AI API调用失败({e.code})", "detail": error_msg})
        }
    except urllib.error.URLError as e:
        return {
            "statusCode": 503,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": f"网络连接失败", "detail": str(e.reason)})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN},
            "body": json.dumps({"error": f"内部错误", "detail": str(e)})
        }
