"""
TactFlow合规路由代理函数 · Vercel Python runtime版
作用: 接收前端请求 → 转发到七牛云AI API → 返回结果
密钥: 从环境变量读取, 前端不暴露
迁移: 从七牛云函数计算版 (handler(event, context)) 转为 Vercel版 (handler(request))
"""
import json
import os
import urllib.request
import urllib.error

QINIU_AI_URL = "https://api.qnaigc.com/v1/chat/completions"
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', '*')

SYSTEM_PROMPT = """你是TactFlow数据合规路由引擎 v1.0。你的唯一任务是：对用户输入的文本进行合规风险扫描和数据脱敏处理。

工作流程：
1. 扫描文本中所有敏感数据字段
2. 根据目标国家的法规判断合规风险等级
3. 对每个字段执行对应脱敏策略
4. 生成脱敏后的完整文本

脱敏策略L4体系：
- L1 REDACT：完全删除，用[REDACTED]替代
- L2 MASK：部分遮蔽（手机号→138****5678，邮箱→t***@example.com）
- L3 HASH：加盐哈希，格式[HASH:6位值]（如张三→[HASH:a3f2c1]）
- L4 TOKENIZE：令牌化，格式[TOKEN:8位值]（如银行卡→[TOKEN:7b2d9f1a]）

CN规则（中国PIPL）：
身份证号→L1 REDACT、手机号→L2 MASK、姓名→L3 HASH、银行卡号→L4 TOKENIZE、邮箱→L2 MASK、地址→L3 HASH

SG规则（新加坡PDPA）：
NRIC→L1 REDACT、手机号→L2 MASK、邮箱→L2 MASK、地址→L3 HASH、姓名→L3 HASH

风险等级：高=违反核心条款可致罚款诉讼、中=合规灰色地带需评估、低=建议性条款可优化

你必须严格输出JSON格式，不要在JSON前后添加任何文字：
{
  "desensitized_text": "脱敏后完整文本",
  "fields": [
    {
      "field_type": "字段类型",
      "original_value": "原始值",
      "desensitized_value": "脱敏后值",
      "risk_level": "高/中/低",
      "strategy": "L1/L2/L3/L4",
      "strategy_name": "REDACT/MASK/HASH/TOKENIZE",
      "regulation": "PIPL/PDPA"
    }
  ],
  "risk_summary": "一句话风险摘要",
  "compliance_score": 0到100的数字
}"""


def build_cors_headers():
    return {
        'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, X-Auth-Token',
        'Access-Control-Max-Age': '86400'
    }


def call_qiniu_ai(user_message, country='CN'):
    api_key = os.environ.get('QINIU_API_KEY', '')
    if not api_key:
        raise ValueError('QINIU_API_KEY not configured')

    request_body = {
        'model': 'deepseek/deepseek-v4-flash',
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_message}
        ]
    }

    req = urllib.request.Request(
        QINIU_AI_URL,
        data=json.dumps(request_body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))

    content = result['choices'][0]['message']['content']
    json_str = content.replace('```json\n', '').replace('```', '').strip()
    return json.loads(json_str)


def handler(request):
    method = request.get('method', 'GET')
    headers = request.get('headers', {})

    if method == 'OPTIONS':
        return {
            'statusCode': 204,
            'headers': build_cors_headers(),
            'body': ''
        }

    if method != 'POST':
        return {
            'statusCode': 405,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Method not allowed'})
        }

    shared_secret = os.environ.get('SHARED_SECRET', '')
    token = headers.get('X-Auth-Token') or headers.get('x-auth-token') or ''
    if shared_secret and token != shared_secret:
        return {
            'statusCode': 401,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Unauthorized'})
        }

    try:
        body_str = request.get('body', '{}')
        if isinstance(body_str, str):
            body = json.loads(body_str)
        else:
            body = body_str
        text = body.get('text', '')
        country = body.get('country', 'CN')
        if not text:
            return {
                'statusCode': 400,
                'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'text required'})
            }
    except (json.JSONDecodeError, TypeError) as e:
        return {
            'statusCode': 400,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Invalid JSON', 'detail': str(e)})
        }

    try:
        result = call_qiniu_ai(text, country)
        return {
            'statusCode': 200,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps(result, ensure_ascii=False)
        }
    except urllib.error.HTTPError as e:
        return {
            'statusCode': 502,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'AI service error', 'detail': str(e)})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {**build_cors_headers(), 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Internal error', 'detail': str(e)})
        }
