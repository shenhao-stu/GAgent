# 飞书 SOP (lark) — 端内全接口客户端(去 PC 化)

> 触发: 接飞书 / 飞书 / lark / 飞书机器人 / 飞书文档 / 多维表格。
> **飞书=零 ADB**: 主路径 = `import lark_native` 纯 requests 直调开放平台; **不需要无线调试/ADB**(2026-07 session_puwibo6 曾误配 Node 版 lark-cli 需 shell 执行→白打 28 轮 ADB, 教训: 飞书永不走 CLI/Node/PC/ADB)。
> 窄腰 = `lark_native.api(method, path, params=None, payload=None, as_user=False)`: 任何开放平台端点一个入口; code!=0 自动 raise, token 过期自动重刷。

## 一次性配置
用户在开放平台 open.feishu.cn"创建企业自建应用", 拿 App ID(`cli_...`)+App Secret, 然后:
```python
import lark_native
lark_native.save_creds("cli_...", "<app_secret>")   # 只落手机本地 channels/lark.json, 模块自己管路径
lark_native.bot_info()                              # 返回 {app_name, open_id,...} = bot 身份验通
```
- 凭证红线: app_secret 只存 channels/lark.json, 绝不 print/回显/进日志/进 BBS; 配完提醒用户可去开放平台 reset。
- 若要用**用户身份**(读写个人私有资源, 见 ⑤): 应用"安全设置"里把重定向 URL 加上 `http://localhost:3000/callback`(端内 OAuth 回调, 一次性)。

## 权限坑
- 报 99991672 或权限类错 → 引导用户去开放平台"权限管理"加对应 scope 并**发布版本**; bot 永不 auth login。
- bot 看不到用户私有资源(个人日历/云空间/私聊搜索): 改用**用户身份** `api(..., as_user=True)`, 见 ⑤; 别用 bot 硬撞用户资源权限墙。

## ① IM: 发消息 / 群列表
```python
import json, lark_native
lark_native.send_text("ou_xxx", "hi")                                # 默认 open_id
lark_native.send_text("oc_xxx", "hi", receive_id_type="chat_id")     # 发群
# 卡片/富文本: msg_type=interactive/post; ⚠content 必须是 JSON 字符串(json.dumps), 非对象
lark_native.api("POST", "/im/v1/messages", params={"receive_id_type": "chat_id"},
    payload={"receive_id": "oc_xxx", "msg_type": "interactive", "content": json.dumps(
        {"elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "**加粗** [链接](https://x.com)"}}]})})
chats = lark_native.api("GET", "/im/v1/chats", params={"page_size": 100})["items"]   # bot 所在群 → chat_id
```

## ② 多维表格 Base: 记录增删改查
```python
base, tbl = "<app_token>", "<table_id>"   # ⚠wiki 链接里的 base 先走 ③get_node 换 obj_token 才是 app_token
r = lark_native.api("POST", "/bitable/v1/apps/%s/tables/%s/records/search" % (base, tbl),
    params={"page_size": 100}, payload={"filter": {"conjunction": "and", "conditions": [
        {"field_name": "状态", "operator": "is", "value": ["done"]}]}})   # r["items"]
lark_native.api("POST", "/bitable/v1/apps/%s/tables/%s/records/batch_create" % (base, tbl),
    payload={"records": [{"fields": {"标题": "x"}}]})
lark_native.api("PUT", "/bitable/v1/apps/%s/tables/%s/records/%s" % (base, tbl, "rec_xxx"),
    payload={"fields": {"标题": "y"}})
lark_native.api("POST", "/bitable/v1/apps/%s/tables/%s/records/batch_delete" % (base, tbl),
    payload={"records": ["rec_xxx"]})
```
坑(一条一行):
- 日期字段: **写入**值=毫秒时间戳数字(非字符串/秒); **search 过滤**不支持 `>=`, operator 用 is/isGreater/isLess 且 value=`["ExactDate","<毫秒串>"]`(字符串数组, 关键字大小写敏感, 亦可 `["Today"]`)。
- primary field 不可改类型; attachment 字段不可 PATCH 写(上传走专用接口); rollup 禁 COUNT。
- 记录批量 ≤500(超=1254104); 1254291=并发写冲突 → list/写全部**串行**, 批间歇 0.5s。
- 写前先 GET `/bitable/v1/apps/{base}/tables/{tbl}/fields` 读字段类型, 别猜。

## ③ Wiki → Doc: 读知识库文档全文
```python
node = lark_native.api("GET", "/wiki/v2/spaces/get_node", params={"token": "<wiki链接末段token>"})["node"]
# obj_type 分流: docx→下行读全文; bitable→obj_token 当 ②的 app_token; sheet→sheets 接口
text = lark_native.api("GET", "/docx/v1/documents/%s/raw_content" % node["obj_token"])["content"]
```
坑: `/wiki/` 链接 token ≠ file_token, **必先 get_node 换 obj_token**; `/docx/` `/sheets/` 链接 token 可直用。
飞书 Base **网页**写入(canvas+嵌套 iframe)离屏 CDP 撞墙 → 程序化写入永远优先本 SOP 的 bot API, 别啃页面。

## ⑤ 用户身份(OAuth, 无感"点一下授权"; 读写个人私有资源用)
bot 看不到用户私有文档/云空间/日历; 需要时用 user_access_token(标准 OAuth 授权码流, 端内 127.0.0.1:3000 一次性回调, 无需公网)。
**两回合**(别在一个 code_run 里 user_wait 死等, 会撞 code_run 超时):
```python
# 回合1: 生成授权链接, 作为可点链接发给用户(用户浏览器登录+授权)
import lark_native
url = lark_native.user_auth_url(scope="offline_access docx:document drive:drive")   # scope 空格分隔, 须在"权限管理"已开通; offline_access 换 refresh(否则~2h 重授)
# 把 url 发进对话让用户点; 然后本回合结束, 等用户操作

# 回合2: 用户点完授权后, 换 token 并验通
me = lark_native.user_wait()          # 默认 40s; 没拿到可再调续等
# me = {name, open_id, ...}; 之后:
doc = lark_native.api("GET", "/docx/v1/documents/<id>/raw_content", as_user=True)   # 用户身份读个人文档
```
坑(一条一行):
- 一个 code_run 里 `user_wait` 默认 40s < code_run 60s; 超了就下回合再 `user_wait()` 续等, 已捕获的 code 不丢。
- 飞书 App 内 webview 无地址栏 → 授权后回跳 localhost 可能落不进: 让用户点 webview 右上 ··· →"在浏览器中打开/复制链接", 或复制回跳完整 URL 调 `lark_native.user_code_from_url(url)` 兜底。
- 端口 3000 须与"安全设置"注册的 redirect_uri 一致; 被占用会报错(换程序/重启 app)。
- as_user=True 但没授权 → 报错引导 user_auth_url(), **绝不静默降级到 bot 身份**(免得用错身份查不到还不自知)。
- token 自动续期(refresh); refresh 过期(久未用)才需重新 user_auth_url()。

## 分页通用式
```python
items, pt = [], None
while True:
    d = lark_native.api("GET", "/im/v1/chats", params={"page_size": 100, **({"page_token": pt} if pt else {})})
    items += d.get("items", []); pt = d.get("page_token")
    if not d.get("has_more"): break
```

## 红线
- 凭证只经 save_creds() 落 channels/lark.json(不入 APK assets/Evolution/日志); 报错信息可含 code/msg, 不含 secret。

## 收事件(未实现, 诚实声明)
- 收消息需 webhook(要公网)或长连接(lark-oapi wss, pycryptodome 在 Chaquopy 15 打包未验证), 本轮均未实现;
  下一步 = 升 Chaquopy 17 + pip lark-oapi, 长连接线程挂 FloatService 常驻。
- 定时主动推送: 裸 `time.sleep` 循环锁屏后被 Doze 冻死 → 须 AlarmManager.setExactAndAllowWhileIdle/常驻服务。
