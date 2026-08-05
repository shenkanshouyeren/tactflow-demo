# 烤土豆行动 · 部署指南 V3（代理方案修正版）

> **V3核心变更**（基于7/30官方文档核实）：
> 1. V2错误修正：函数计算**不在免费额度列表中**（第三方文章声称"100万次免费"≠官方事实）
> 2. 新增替代方案：七牛云容器轻应用C1M1（750小时/月免费≈全月运行）→零额外成本
> 3. API密钥不再明文写入文档→改为"在控制台复制你的密钥"
> 4. 步骤编号重新整理→逻辑清晰
> 5. 架构图更新→3套方案可选

---

## 架构图（V3）

```
用户iPhone Safari
  │
  │ POST {text, country, model}
  ▼
代理层（以下3种任选其一）
  │ ┌─ 方案①：七牛云容器轻应用（C1M1免费750h）⭐推荐
  │ ├─ 方案②：七牛云函数计算（需额外付费）
  │ └─ 方案③：Vercel免费部署（5分钟）
  │
  │ 环境变量：QINIU_API_KEY = [你的密钥，绝不写入文档]
  │ 内部调用：https://api.qnaigc.com/v1/chat/completions
  │ SYSTEM_PROMPT + 请求构建 = 代理内部完成
  ▼
七牛云AI API（DeepSeek-V4-Flash）
  │
  │ JSON合规分析结果
  ▼
代理层 → 加CORS头 → 返回前端
  │
  ▼
用户看到：原文vs脱敏对比 + 风险评分 + 处理明细
```

**安全优势**：密钥只在代理层环境变量中→前端代码零密钥→公开页面安全。

---

## Step 1：选择代理方案

> ⚠️ 7/30官方文档核实结论：**函数计算不在免费额度列表中**。
> 但**容器轻应用C1M1有750小时/月免费**≈744小时/月→刚好够一个实例持续运行。

### 方案①：七牛云容器轻应用（免费750h/月）⭐ 推荐

```
优势：零额外成本 + C1M1(1核1GB)可运行Python代理 + 持续运行
劣势：需打包Docker镜像 → Safari操作可能有门槛
操作路径：
1. Safari → portal.qiniu.com → 容器轻应用 → 创建C1M1实例
2. 部署Python代理服务（Docker镜像方式）
3. 配置环境变量 QINIU_API_KEY
4. 获取公网URL → 替换index.html中的PROXY_URL
```

### 方案②：七牛云函数计算（需额外付费）

```
优势：按请求触发 → 不需要持续运行 → 适合低频演示
劣势：不在免费额度内 → 需付费（具体价格需在控制台确认）
操作路径：
1. Safari → portal.qiniu.com → 数据处理 → 函数计算 → 开通
2. 创建tactflow-proxy函数 → Python 3.x → 粘贴proxy_handler.py代码
3. 配置HTTP触发器 → POST+OPTIONS
4. 配置环境变量 QINIU_API_KEY
5. 获取触发器URL → 替换index.html中的PROXY_URL
```

### 方案③：Vercel免费部署（5分钟方案）

```
优势：完全免费 + 手机可操作 + 自动CORS + 5分钟部署
劣势：需GitHub账号 + 依赖第三方平台
详见下方备用方案章节
```

---

## Step 2：创建代理服务（根据方案不同）

### 方案① 操作步骤：容器轻应用

```
1. Safari → portal.qiniu.com → 登录
2. 左侧菜单 → 容器轻应用 → 创建实例
3. 基本配置：
   - 规格：C1M1（免费750h/月）
   - 镜像：Python运行环境（或自定义Docker镜像）
   - 端口：对外暴露HTTP端口（如8080）
4. 部署代理代码：
   - 方式A：在控制台代码编辑器中粘贴proxy_handler.py内容
   - 方式B：上传Docker镜像到七牛云镜像仓库 → 容器引用该镜像
5. 点击「创建」或「部署」
```

### 方案② 操作步骤：函数计算

```
1. Safari → portal.qiniu.com → 登录
2. 左侧菜单 → 数据处理 → 函数计算 → 开通
3. 创建函数：
   - 函数名称：tactflow-proxy
   - 运行环境：Python 3.x
   - 内存：256MB（合规分析不需要大内存）
   - 超时时间：30秒（AI API调用需10-20秒）
   - 入口函数：handler.handler
4. 触发器配置：
   - 类型：HTTP触发器
   - 路径：/api/compliance
   - 方法：POST + OPTIONS（必须加OPTIONS，否则CORS预检失败）
   - 鉴权：匿名访问（公开演示）
5. 点击「创建」
6. 进入代码编辑 → 粘贴proxy_handler.py代码 → 保存部署
```

> 💡 如果Safari上代码编辑不好用 → 联系七牛云客服（你确认每个位置都有人工客服）

---

## Step 3：配置环境变量（密钥安全存储）

> ⚠️ 密钥是生存资产，绝不写入任何文档或代码。
> 密钥只在代理层环境变量中 → 前端代码零密钥 → 公开页面安全。

```
1. 代理服务详情页 → 找到「环境变量」或「配置」
2. 添加环境变量：
   - 名称：QINIU_API_KEY
   - 值：在七牛云控制台 → AI API Key管理页 → 复制你的密钥
3. 点击「保存」

⚠️ 安全建议：
- 密钥曾明文暴露 → 建议在AI API Key管理中设置限流：
  100 tokens/秒 + 50000 tokens/日
- 前端HTML源代码中搜索sk- → 应找不到任何密钥
```

---

## Step 4：获取代理URL + 测试

```
1. 代理服务详情页 → 查看公网URL/触发器URL
2. URL格式：
   - 容器轻应用：https://xxx.qiniu.com:8080/api/compliance
   - 函数计算：https://xxx.region.qiniu.com/api/compliance
3. iPhone Safari → 打开该URL → 应返回CORS OPTIONS响应或405（正常）
4. Arya帮你用curl测试POST请求：

   curl -X POST https://[你的代理URL]/api/compliance \
     -H "Content-Type: application/json" \
     -d '{"text":"张三身份证310101199001011234","country":"CN","model":"deepseek/deepseek-v4-flash"}'

5. 期望返回：JSON合规分析结果（含desensitized_text + fields + risk_summary + compliance_score）
```

---

## Step 5：更新前端HTML + 部署

```
1. 打开index.html → 找到 PROXY_URL 行：
   const PROXY_URL = 'YOUR_PROXY_URL_HERE';
2. 替换为Step 4获取的实际URL：
   const PROXY_URL = 'https://xxx.qiniu.com/api/compliance';
3. ⚠️ 前端代码中不再包含API密钥 → 安全！
4. 上传index.html到静态托管：
   - 七牛云对象存储 → 上传 → CDN分发（10GB/月免费）
   - 或GitHub Pages / Netlify / Vercel
   - 或直接分享HTML文件给客户（ima/邮件/微信）
5. iPhone Safari → 打开页面 → 输入文本 → 点击「开始检查」→ 看到结果
```

---

## Step 6：落地验证（不可跳过 ⚡）

```
验证清单（守夜人iPhone上逐项确认）：

✅ 代理服务是否创建成功？→ 控制台显示代理实例/函数列表
✅ 环境变量是否配置？→ 配置页显示QINIU_API_KEY（值隐藏）
✅ 公网URL是否可访问？→ Safari打开代理URL有响应
✅ POST请求是否返回合规分析？→ curl测试返回JSON结果
✅ 前端HTML是否正常加载？→ Safari打开HTML页面不报错
✅ 前端→代理→AI→前端全链路？→ 输入文本→看到脱敏结果
✅ 密钥是否安全？→ HTML源代码中搜索sk- → 找不到（零密钥）
```

---

## 备用方案

**方案A：七牛云客服协助**
- 守夜人已确认每个位置都有人工客服
- 打开七牛云小程序 → 联系客服 → 说明"需要创建代理服务做API转发"
- 客服可能远程协助或提供更简化的创建路径

**方案B：Vercel免费部署（5分钟方案）**
```
1. 手机浏览器 → vercel.com → 注册（GitHub账号）
2. 创建新项目 → 上传Python代理代码
3. Vercel自动生成公开URL
4. 环境变量 → Settings → Environment Variables → QINIU_API_KEY
5. 优势：手机友好 + 免费额度足够 + 自动CORS处理
6. 劣势：需GitHub账号 + 依赖第三方平台
```

**方案C：ima知识库内嵌（零部署方案）**
```
1. compliance-radar Skill发布到ima广场
2. Skill内部直接调用ima AI推理能力（不需要七牛云）
3. 用户通过ima App对话体验
4. 优势：零部署、iPhone完全可操作、ima生态内传播
5. 劣势：不是独立API演示、潜在客户必须是ima用户
```

> 决策权交还守夜人：①/②/③/A/B/C 哪个优先？还是并行推进？

---

## 修正记录

| 版本 | 日期 | 核心变更 | 错误修正 |
|---|---|---|---|
| V1 | 7/28 | 纯前端直连API | — |
| V2 | 7/29 | 云函数代理（CORS+密钥安全） | — |
| V3 | 7/31 | 3套方案+容器轻应用替代 | ①函数计算免费额度（误引第三方）②API密钥明文 ③步骤编号混乱 |

---

## 算力消耗记录

本轮预估：8-10算力（搜索2+fetch1+文件读写3+编辑3）
