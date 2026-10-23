# Enable capabilities / 功能开启指南

[Quick start](GETTING_STARTED.md) · [YOLO](OPTIONAL_YOLO.md) · [Troubleshooting](TROUBLESHOOTING.md)

Start with the model and phone tools, then add one capability and verify it.
There is no license key that unlocks every service, and no need to enable every
Android permission. The matrix below covers the retained capability groups;
[Feature scope](FEATURE_SCOPE.md) lists excluded implementations.

先跑通模型与手机工具，再逐项接入并验收。没有“全部解锁密钥”；完整能力也不等于所有权限一次全开。
下表覆盖保留的能力组，未分发的实现见[功能范围](FEATURE_SCOPE.md)。

<a id="models"></a>
## 1. Model and vision / 模型与看图

**Settings → Providers & Models / 设置 → 服务商与模型**

| Field / 配置 | What to supply / 填什么 |
| --- | --- |
| Protocol / 协议 | The endpoint's actual OpenAI-compatible or Anthropic-compatible protocol / 与服务商实际协议匹配 |
| URL / 接口 | The provider-issued API base, not its website or a guessed endpoint / 服务商提供的 API 地址，不填官网首页 |
| Key / 密钥 | Your own user key, entered locally / 在本机填写自己的用户密钥 |
| Model / 模型 | Enter the exact name in **Default model ID**; fetching a list is optional / 直接填写**默认模型 ID**，无需先获取列表 |
| Proxy / 代理 | Empty unless needed; any configured proxy must be reachable from the phone / 无需则留空，配置时必须由手机可达 |

Check **text → harmless tool call → synthetic image** separately. A working chat
does not prove tool execution or vision works. A phone-local proxy can work without
USB; a computer-only localhost address cannot. See [Network](NETWORK.md).

Main-model selection does **not** automatically configure every visual helper.
For image questions, ask GAgent:

> 按 memory/vision_sop.md 和 vision_api.template.py 配置看图能力。复用我已配置、支持图片的模型，
> 不输出密钥；先用合成图片自测，再查看当前设置页。不要修改其他配置。
>
> Configure vision from the bundled SOP and template using my existing image-capable provider. Do not print credentials; test a synthetic image first.

The local adapter is `memory/vision_api.py`, created from
[`vision_api.template.py`](../app/src/main/assets/gacore/memory/vision_api.template.py).
Set `DEFAULT_BACKEND` to `claude` or `openai`, and set the matching
`CLAUDE_CONFIG_KEY` or `OPENAI_CONFIG_KEY` to the **configuration name** in `mykey`,
not the literal API key. Changing the chat model alone does not change this reference.

Both visual protocols reuse the core URL builder. OpenAI-compatible bases such as
`https://example.com`, `https://example.com/v1` and a complete
`https://example.com/v1/chat/completions` resolve without duplicating `/v1`.
Use your provider's documented endpoint; the template's OpenAI path uses **Chat
Completions**, not Responses. An existing user-created `memory/vision_api.py` is
preserved on upgrade: compare its URL construction with the current template if
vision still returns 404. Back up that file before adapting it.

中文要点：视觉适配器引用已有配置的**名称**，不复制密钥。两种协议复用内核的 URL 规则；
OpenAI 模板使用 Chat Completions。升级会保留用户已有的 `vision_api.py`，旧适配器仍报 404
时先备份，再按新模板修正路径。只查看配置名称与协议元信息，不打印凭据对象。

## 2. Phone and local features / 手机与本地能力

| Capability / 能力 | Enable / 开启 | Verify / 核验 |
| --- | --- | --- |
| GUI and screenshots / 手机操作与截图 | Android 11+ arm64; enable GAgent accessibility and overlay access / 开启无障碍与悬浮窗 | `droid.ping()` reports the device; a fresh screenshot matches the current screen / 新截图与当前画面一致 |
| Persistent progress / 持续显示进度 | Settings → Always-on floating window / 设置 → 悬浮窗常开 | During a harmless running task: Home → GAgent → Home / 运行无副作用任务时切后台核验 |
| OCR / 文字识别 | Bundled; no separate account or model download / 已内置 | `droid.look(cache=False)` returns readable labels on a text-rich screen / 有文字页面返回识别项 |
| YOLO / 图标检测 | Install compatible ONNX; [guide](OPTIONAL_YOLO.md) / 按指南独立安装 | Real detections and loaded model, not just a file / 实际检测与已加载模型 |
| Files and memory / 文件与记忆 | Local tools are included; allow shared-storage access when needed / 本地工具已含，按需授权共享存储 | Create and read back a new test file; review saved procedures / 创建并读回测试文件 |
| Browser / 内置浏览器 | Sign in through the app browser; task/background WebViews share cookies / 在内置浏览器登录，任务与后台 WebView 复用 Cookie | Verify the URL, content and session; [background guide](../app/src/main/assets/gacore/memory/offscreen_sop.md) / 核对地址、内容与登录态 |
| Scheduled agent tasks / 定时任务 | Ask the agent to create a bounded schedule using `droid.alarm_set` / 创建明确的定时任务 | `droid.alarm_list()`; check actual delivery and cancellation / 核验列表、到达与取消 |
| Notification rules / 通知规则 | Grant Android Notification access; define explicit rules using the [notification SOP](../app/src/main/assets/gacore/memory/notif_trigger_sop.md) / 授权通知使用权并配置规则 | `droid.notif_trigger_status()` and a new synthetic notification / 状态与新建测试通知 |
| Feishu / 飞书 | Own app credentials and scopes; follow [bot setup](../app/src/main/assets/gacore/memory/feishu_bot_sop.md) and [API tools](../app/src/main/assets/gacore/memory/lark_sop.md) / 自有应用凭据与授权范围 | Verify status and a test-space interaction; no unsolicited messages / 测试空间核验 |
| Sensing / 感知 | Explicitly activate needed features and permissions using the [sensing SOP](../app/src/main/assets/gacore/memory/sense_sop.md) / 按需主动开启 | Check a short capture, stop state and local retention policy / 短时采集、停止与留存核验 |
| Wireless ADB / 无线 ADB | Settings → Wireless debugging self-connect; follow the [setup guide](../app/src/main/assets/gacore/memory/adb_self_setup.md) / 设置 → 无线调试自连 | Check the actual paired connection; ordinary GUI use does not require ADB / 核验配对，普通 GUI 无需 ADB |
| Virtual display / 虚拟屏 | Compatible wireless ADB/device and `vdisplay.vd_probe()` / 兼容设备与探测 | Explicitly experimental; verify display, input and teardown on that device / 实验能力，逐机验收创建、输入与停止 |
| Vendor assistant / 厂商助手 | Use discovery from the [adapter guide](../app/src/main/assets/gacore/memory/vendor_assistant_sop.md) / 按规程发现可用助手 | No universal OEM support; check the actual assistant and outcome / 不保证所有厂商支持 |
| Local evolution / 本地修改保留 | Included asset-update/evolution machinery; keep your own backups / 已保留更新融合机制，仍需备份 | Verify specific edited files after upgrade; do not assume every change survives / 升级后逐项核对 |

Notification access is different from permission to **post** notifications. Android
background limits can delay scheduled work and restrict recording. Sensing does
not guarantee always-on recording or background location on every system.

WeChat always uses the **visual route**: screenshot, OCR/optional YOLO, configured
vision and gestures. Do not enable a node-tree helper to bypass that boundary.

<a id="modules"></a>
## 3. Optional services / 可选服务

Open **Settings → Optional modules / 设置 → 可选组件**. Obtain the addresses and
credentials from a compatible service you operate or are authorized to use.
The Android repository contains clients, not a one-command deployment of these servers.

| Form section / 表单 | Fields / 字段 | Requirements / 要求 |
| --- | --- | --- |
| PC Link | `url`, `token` | WSS signaling endpoint, individual credential compatible with request signing, paired computer / WSS、逐用户兼容凭据与配对电脑 |
| Mesh / GAnet | `url`, `token`, `owner_id` | HTTPS API, user token and numeric identity issued by that server / HTTPS、用户令牌及服务签发的数字身份 |
| Streaming ASR | `url`, `token`, `model` | Compatible WSS relay; default `step-asr-1.1-stream`, PCM16/16 kHz mono; microphone permission / 兼容中继、模型与麦克风授权 |
| APK build service | `url`, `token` | HTTPS builder and own token; [project-to-APK workflow](../app/src/main/assets/gacore/memory/apk_factory_sop.md); workers/signing stay server-side / 构建工作节点与签名在服务端 |
| Model provider / GA Plan | Use Providers & Models instead / 使用服务商与模型页 | Provider-issued endpoint, user key and model / 服务商签发的接口、用户密钥与模型 |

An importable [profile example](examples/integrations.example.json) shows the exact
JSON shape: `schema: 1` and an `integrations` object. Its `.invalid` URLs and example
credentials are placeholders, **not working services**. Replace them privately,
remove unused module entries, import, review, then press Save. Import alone only
fills the form. Keep real profiles out of Git, issues and screenshots.

At an unchanged URL, a blank token keeps the saved value. Changing the URL requires
the new service's credential; clearing the URL disables the module. A successful
Save validates configuration, not server interoperability. Test one read-only
connection before a real task. [Protocols and authority](OFFICIAL_MODULES.md).

示例必须替换后才能使用，真实配置不提交仓库。地址不变时令牌留空会保留旧值；改地址需新凭据；
清空地址停用。保存成功不代表服务连通，更不代表获得了服务端权限。

<a id="jev"></a>
## 4. Optional Jev navigation / 可选 Jev 导航

Jev is a text-candidate selector, not a chat model, image model or YOLO replacement.
It is disabled until a private `files/ga/jev_config.json` enables selected packages
and supplies your key; use the [example](../app/src/main/assets/gacore/jev_config.example.json)
and [Jev guide](../app/src/main/assets/gacore/memory/jev_phone_use.md).
This adapter pins `jev-1.13.0` and its protocol. It is not configured in the normal
model-provider or optional-service form.

Use only on permitted readable screens. It must fall back without action on
unsupported, sensitive or ambiguous pages; **do not allowlist WeChat**. The main
planner still owns intent, permissions and final-state verification. Missing or
disabled configuration does not prevent ordinary phone use.

Jev 单独配置、默认关闭，不是“选成主模型就生效”。只用于获准的可读文字导航场景，
不用于微信，也不代替任务完成核验。公开配对研究见
[AndroidBench](https://androidbench.gaagent.ai/#jev-study)，不能直接推断所有任务提速。

## 5. A useful stopping point / 配置完成的判断

- Text, a real harmless tool call and a synthetic image each work / 文本、工具、合成图分别通过。
- The current screen is observed and one harmless action is checked / 当前观察与单步结果一致。
- Background progress stays visible with the chosen overlay setting / 浮窗符合设置。
- Each added model/service passes its own test; unconfigured services remain disabled / 各组件独立验收。
- You know how to stop the task, disable a module and revoke its user credential / 能停止、停用和撤销凭据。

Record the configuration names and outcomes, not keys. Hardware and service
coverage remain bounded by [Validation](VALIDATION.md).

### PC Link build bootstrap / 构建默认配置

A trusted build can set the Actions secret `GAGENT_PCLINK_DEFAULTS` to a JSON
object containing `url` (WSS) and `token` (relay request signing). The build writes
an ignored `pclink_defaults.json` asset. This is extractable client access material,
not an account, model-provider or administrator secret. Never put those secrets
in this profile. Source and APK audits still reject other secret formats.
No default is committed to source. Missing bootstrap leaves PC Link unconfigured
and the UI opens Optional modules. A custom PC Link URL and token override the
entire bootstrap; clearing that URL restores the build default. Unpair to stop
saved-room reconnect. Network connection starts only after pairing or restoring
an existing pair. The original `ga-pclink:v1:` nine-digit QR protocol is unchanged.

受信构建可通过上述 Actions secret 注入默认中继，源码不保存凭据。
安装包中的中继接入材料可被提取，不可使用账户、模型服务商或管理密钥。
扫码后才连接；已有配对会自动重连。自定义地址和令牌整体覆盖默认配置，
清空 PC Link 地址恢复默认，解除配对停止重连。无默认配置的自行构建包会
明确提示打开可选组件配置，不再把缺配置显示成普通未链接。
