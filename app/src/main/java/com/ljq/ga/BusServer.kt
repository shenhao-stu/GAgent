package com.ljq.ga

import ai.onnxruntime.*
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * GA 能力总线: 127.0.0.1:18765, 6端点, 404即文档。
 * py 正典壳 = files/ga/droid.py (agent 只看它, 不直接拼 HTTP)。
 */
object Bus {
    const val PORT = 18765
    const val VER = "0.5"
    private var httpd: BusHttpd? = null
    val boundPort: Int get() = httpd?.listeningPort ?: PORT
    @Volatile var appCtx: android.content.Context? = null   // /adb/* 端点需 Context 建 AdbController

    @Synchronized fun start(ctx: android.content.Context) {
        appCtx = ctx.applicationContext
        if (httpd != null) return
        val auth = LocalBusAuth.create()
        val directory = File(ctx.filesDir, "ga").apply { mkdirs() }
        val tokenFile = File(directory, ".bus_token")
        // Prefer the documented port; coexist with another installed variant.
        val server = BusHttpd(PORT, auth)
        val bound = try {
            server.start(NanoHTTPD.SOCKET_READ_TIMEOUT, true)
            server
        } catch (e: java.io.IOException) {
            server.stop()
            BusHttpd(0, auth).also { it.start(NanoHTTPD.SOCKET_READ_TIMEOUT, true) }
        }
        try {
            tokenFile.writeText(auth.token)
            android.system.Os.chmod(tokenFile.absolutePath, 0x180) // 0600
            val portFile = directory.resolve("bus_port.txt.tmp")
            portFile.writeText(bound.listeningPort.toString())
            check(portFile.renameTo(directory.resolve("bus_port.txt")))
            httpd = bound
        } catch (e: Exception) {
            bound.stop()
            throw e
        }

    }
}

/** ONNX session 管理: path->session, 空闲30min逐出 */
object Onnx {
    val env: OrtEnvironment by lazy { OrtEnvironment.getEnvironment() }
    private val sessions = HashMap<String, Pair<OrtSession, Long>>()
    private const val IDLE_MS = 30 * 60 * 1000L

    @Synchronized
    fun get(path: String): OrtSession {
        if (!File(path).isFile) throw RuntimeException("model not found: $path")
        val now = System.currentTimeMillis()
        val it = sessions.entries.iterator()
        while (it.hasNext()) {
            val e = it.next()
            if (e.key != path && now - e.value.second > IDLE_MS) {
                try { e.value.first.close() } catch (_: Exception) {}
                it.remove()
            }
        }
        val s = sessions[path]?.first ?: Onnx.env.createSession(path, OrtSession.SessionOptions())
        sessions[path] = Pair(s, now)
        return s
    }

    @Synchronized
    fun loaded(): List<String> = sessions.keys.toList()

    fun typeName(t: OnnxJavaType) = when (t) {
        OnnxJavaType.FLOAT -> "float32"; OnnxJavaType.DOUBLE -> "float64"
        OnnxJavaType.INT64 -> "int64"; OnnxJavaType.INT32 -> "int32"
        OnnxJavaType.INT8 -> "int8"; OnnxJavaType.UINT8 -> "uint8"
        OnnxJavaType.BOOL -> "bool"; OnnxJavaType.FLOAT16 -> "float16"
        else -> t.toString().lowercase()
    }

    fun typeOf(s: String) = when (s) {
        "float32" -> OnnxJavaType.FLOAT; "float64" -> OnnxJavaType.DOUBLE
        "int64" -> OnnxJavaType.INT64; "int32" -> OnnxJavaType.INT32
        "int8" -> OnnxJavaType.INT8; "uint8" -> OnnxJavaType.UINT8
        "bool" -> OnnxJavaType.BOOL; "float16" -> OnnxJavaType.FLOAT16
        else -> throw RuntimeException("unsupported dtype: $s")
    }

    fun itemSize(t: OnnxJavaType) = when (t) {
        OnnxJavaType.FLOAT, OnnxJavaType.INT32 -> 4
        OnnxJavaType.DOUBLE, OnnxJavaType.INT64 -> 8
        OnnxJavaType.FLOAT16 -> 2
        else -> 1
    }

    fun info(path: String): String {
        val s = get(path)
        fun side(m: Map<String, NodeInfo>): JSONArray {
            val arr = JSONArray()
            for ((name, ni) in m) {
                val ti = ni.info as TensorInfo
                arr.put(JSONObject().put("name", name)
                    .put("dtype", typeName(ti.type))
                    .put("shape", JSONArray(ti.shape.toList())))
            }
            return arr
        }
        return JSONObject().put("inputs", side(s.inputInfo)).put("outputs", side(s.outputInfo)).toString()
    }

    /** framing: [4B meta_len LE][meta JSON {"inputs":[{name,dtype,shape}]}][raw tensors拼接] → 同构response */
    fun run(path: String, body: ByteArray): ByteArray {
        val s = get(path)
        val metaLen = ByteBuffer.wrap(body, 0, 4).order(ByteOrder.LITTLE_ENDIAN).int
        val meta = JSONObject(String(body, 4, metaLen, Charsets.UTF_8))
        var off = 4 + metaLen
        val feeds = LinkedHashMap<String, OnnxTensor>()
        val inputs = meta.getJSONArray("inputs")
        try {
            for (i in 0 until inputs.length()) {
                val o = inputs.getJSONObject(i)
                val t = typeOf(o.getString("dtype"))
                val sa = o.getJSONArray("shape")
                val shape = LongArray(sa.length()) { sa.getLong(it) }
                var n = itemSize(t).toLong(); for (d in shape) n *= d
                val bb = ByteBuffer.allocateDirect(n.toInt()).order(ByteOrder.nativeOrder())
                bb.put(body, off, n.toInt()); bb.rewind(); off += n.toInt()
                feeds[o.getString("name")] = OnnxTensor.createTensor(env, bb, shape, t)
            }
            s.run(feeds).use { res ->
                val outMeta = JSONArray()
                val blobs = ArrayList<ByteArray>()
                val names = s.outputNames.toList()
                for (i in 0 until res.size()) {
                    val t = res.get(i) as OnnxTensor
                    val bb = t.byteBuffer
                    val bytes = ByteArray(bb.remaining()); bb.get(bytes); blobs.add(bytes)
                    outMeta.put(JSONObject().put("name", names[i])
                        .put("dtype", typeName(t.info.type))
                        .put("shape", JSONArray(t.info.shape.toList())))
                }
                val mb = JSONObject().put("outputs", outMeta).toString().toByteArray(Charsets.UTF_8)
                val out = ByteBuffer.allocate(4 + mb.size + blobs.sumOf { it.size }).order(ByteOrder.LITTLE_ENDIAN)
                out.putInt(mb.size); out.put(mb)
                for (b in blobs) out.put(b)
                return out.array()
            }
        } finally {
            feeds.values.forEach { it.close() }
        }
    }
}

class BusHttpd(port: Int, private val auth: LocalBusAuth) : NanoHTTPD("127.0.0.1", port) {
    companion object {
        // HELP 文档表：单一真值源，逐条 (path, doc) 按原文档顺序排列；分节分隔线附着于该节首条 doc。
        // HELP 正文由此表自动拼接生成，文本内容与拼接结果须与重构前逐字节一致（已用脚本核对）。
        private val ROUTE_DOCS: List<Pair<String, String>> = listOf(
            "/ping" to "GET  /ping                      -> {ver,a11y,pkg:真实前台包名,rot:旋转0..3,w,h:物理屏宽高px,loaded:[model paths]}",
            "/onnx/info" to "GET  /onnx/info?model=<abspath> -> {inputs:[{name,dtype,shape}],outputs:[...]}",
            "/onnx/run" to "POST /onnx/run?model=<abspath>  body/resp同构framing: [4B meta_len LE][meta JSON {\"inputs\"|\"outputs\":[{name,dtype,shape}]}][raw tensors按序拼接,LE]",
            "/a11y/dump" to "GET  /a11y/dump?full=1          -> JSON elements [{t,d,x,y,l,click,edit,scroll,chk,sel}] (须开无障碍)",
            "/a11y/shot" to "GET  /a11y/shot?q=80            -> image bytes (q给出=JPEG质量, 否则PNG; API30+)",
            "/a11y/act" to """POST /a11y/act  body JSON       -> {"op":"tap","x":,"y":} | {"op":"swipe","x1":,"y1":,"x2":,"y2":,"dur":300}
                                   | {"op":"paste","text":,"replace":false} (replace=true 先全选再粘贴=覆盖原文) | {"op":"key","name":"ENTER"}
                                   | {"op":"launch","pkg":} | {"op":"back"} | {"op":"home"}
                                   | {"op":"pkgs","filter":"美团"} -> {apps:[{pkg,label}]} 模糊匹配包名/应用名
                                   | {"op":"install_apk","path":"<abspath>"} 装任意APK(APK工厂产物)→拉起系统安装器,用户确认""",
            "/adb/pair" to "--- app内自连无线ADB(类LADB纯Kotlin,补A11y外shell能力; 用户须先手动开发者选项>无线调试) ---\nPOST /adb/pair    body {host,port,code}  -> {ok,msg} 用配对弹窗的 IP:配对端口+6位码 配对(仅一次,证书持久化)",
            "/adb/connect" to "POST /adb/connect body {host,port?}      -> {ok,msg} port省略/0 ⇒ 自动发现(复用端口→5555→mDNS,一点即连); 显式port ⇒ 先断后连",
            "/adb/shell" to "POST /adb/shell   body {cmd,timeout_ms,max_bytes?} -> {out} 非交互命令收全输出(断线自愈重连); 超max_bytes(默认256KB)报错须分页/落文件; 勿用top/logcat -f长驻",
            "/adb/shell_detached" to "POST /adb/shell_detached body {tag,cmd}  -> {ok,tag} 起held-stream命令(流不关,立即返回): 保活常驻子进程(如VdHelper); 命令须自带 1>_LOG 2>&1 3>&-",
            "/adb/shell_close" to "POST /adb/shell_close    body {tag}      -> {ok,closed} 清该tag的GA侧held流引用(真kill靠调用方pid kill, 因3>&-断fd3)",
            "/adb/status" to "GET  /adb/status                         -> {connected,paired,error,port} connected=libadb派生真值; port=上次成功端口",
            "/web/ensure_fg" to "--- 浏览器容器(webcdp.py 正典封装, 优先用它; 默认走前台) ---\nGET/POST /web/ensure_fg                  -> {ok,url,visible} 幂等拉起/复用前台任务浏览器(可见+可截图+可CDP, webcdp role='fg' 默认路)",
            "/web/ensure" to "GET/POST /web/ensure                     -> {ok,title,url,viewport} 幂等建/复用离屏浏览器WebView(后台不遮挡对话页, webcdp role='browser')",
            "/notifications" to "--- 通知读取/回复/控制(用户须先手动: 设置>通知>通知使用权限>GA 允许) ---\nGET  /notifications                      -> JSON [{key,pkg,title,text,time,canReply}] 当前所有系统通知列表",
            "/notifications/reply" to "POST /notifications/reply   body {key,text} -> {ok} 快捷回复通知(微信/Telegram等)",
            "/notifications/dismiss" to "POST /notifications/dismiss body {key}      -> {ok} 取消单条通知",
            "/notifications/dismiss_pkg" to "POST /notifications/dismiss_pkg body {pkg}  -> {count} 清除指定包名所有通知",
            "/notifications/status" to "GET  /notifications/status                  -> {enabled} 查询通知使用权状态",
            "/notif-trigger/start" to "--- 原生通知触发（规则持久化；通知字段仅用于筛选，执行内容固定取自规则 task） ---\nPOST /notif-trigger/start body {rules:[...]} -> {ok,running,listener_enabled,rule_count,error} 完整替换规则并启动；未授权时通过 error 显式返回",
            "/notif-trigger/status" to "GET  /notif-trigger/status                  -> {ok,running,listener_enabled,rule_count,error} 查询运行与授权状态",
            "/notif-trigger/rules" to "GET  /notif-trigger/rules                   -> {ok,running,listener_enabled,rule_count,error,rules:[...]} 查询完整规则；失败时不含 rules",
            "/notif-trigger/rules/add" to "POST /notif-trigger/rules/add body {rule:{...}} -> {ok,running,listener_enabled,rule_count,error,rules:[...]} 校验并追加规则；失败时不含 rules",
            "/notif-trigger/rules/set-enabled" to "POST /notif-trigger/rules/set-enabled body {id,enabled} -> {ok,running,listener_enabled,rule_count,error,rules:[...]} 启用或禁用规则；失败时不含 rules",
            "/notif-trigger/rules/delete" to "POST /notif-trigger/rules/delete body {id}  -> {ok,running,listener_enabled,rule_count,error,rules:[...]} 删除规则；失败时不含 rules",
            "/notif-trigger/stop" to "POST /notif-trigger/stop                    -> {ok,running,listener_enabled,rule_count,error} 停止触发并取消本能力尚未完成的任务；保留规则",
            "/alarm/set" to "POST /alarm/set body {id,at,every,prompt}   -> {ok} 注册/更新定时闹钟(at=下次触发epoch ms, every=重复间隔ms,0为一次性)",
            "/alarm/del" to "POST /alarm/del body {id}                    -> {ok} 删除闹钟",
            "/alarm/list" to "GET  /alarm/list                            -> {alarms:[{id,at,every,prompt}]} 列出全部闹钟",
            "/net/join" to "--- GA 门控入网(tsnet 嵌入, py 正典壳 = gacore/ganet.py: 登录GAuth->provision换key->join) ---\nPOST /net/join   body {controlUrl,authKey?,hostname?,forwardPort?,remoteAddr?} -> {running,ip,forwards} 恢复/首次入网+可选转发",
            "/net/forward" to "POST /net/forward body {forwardPort,remoteAddr} -> {running,ip,forwards} 只切换本地转发目标，不重启节点",
            "/net/status" to "GET  /net/status                         -> {running,ip,forwards}",
            "/net/down" to "POST /net/down                           -> {ok} 退网+关转发(幂等)",
            "/sense/loc" to "--- 真实世界感知 L0 原子(正典封装 gacore/sense.py, 优先用它; 默认全关, 采集须用户显式动作开启) ---\nGET  /sense/loc?mode=stay|move|once&timeout_ms=8000 -> {ok,fix:{lat,lon,acc_m,ts,stale_ms}|null,granted,provider:fused|manager|none,degraded_to} stay=只吃缓存点(零射频, 静止时的省电档); fix:null 仍 ok:1(「没拿到」是已知状态不是错误)",
            "/sense/near" to "GET  /sense/near?ms=4000                    -> {ok,granted,wifi:{bssid_hash}|null,ble:[{hash,rssi}],caps:{ble,wifi},degraded_to} MAC/BSSID 一律加盐hash后才落盘; ble 的 hash 因 A12+ MAC 随机化只在单次会话内可比对, 不可跨天匹配; WiFi 只读当前连接的一个, 不做全量扫描; ble:[] 必须连 caps.ble 一起读 —— caps=screen_off|scan_failed_N 时空数组不等于「附近没人」(A8.1+ 熄屏直接丢弃无过滤扫描结果且不回调失败)",
            "/sense/cal" to "GET  /sense/cal?from=<ms>&to=<ms>&limit=50  -> {ok,granted,events:[{id,title,start,end,location,allday,cal,attendees:[{name,email_h}]}]} 只查与区间重叠的事件(不做全量同步); 未授权回 granted:false+events:[] 而非报错",
            "/sense/motion" to "GET  /sense/motion                          -> {ok,granted,state:still|walking|vehicle|unknown,confidence:0-100,degraded_to} 无 ACTIVITY_RECOGNITION 退加速度方差(零权限一定可用); 兼作定位的省电门控(still 就别开定位)",
            "/sense/session" to "POST /sense/session body {\"action\":\"start|stop|status\",\"sources\":[\"mic\",\"loc\",\"near\"],\"label\":\"\",\"policy\":{\"seg_ms\":300000,\"max_bytes\":536870912,\"vad_rms\":0}}\n                                   -> {ok,sid,started_at,label,uptime_ms,sources:{mic|loc|near:{state:on|off|denied|silenced|unsupported,reason}},degraded_to,need_perm:[],perm_blocked:[]} 单源拿不到不导致会话失败; start 须由前台用户动作发起(A14 后台起 microphone 型 FGS 直接抛 → degraded_to=bg_start_blocked); start 会为 sources 里缺权限的源就地申请一次(不等结果), need_perm=还没授的, perm_blocked=系统不再弹框的(走 /sense/perm settings); 授权后要再 start 一次该源才进本次会话; sources 可含 cal/motion —— 它们不是常驻源(status 不报), 只为在 start 时一并申请权限",
            "/sense/mic" to "POST /sense/mic body {\"action\":\"segments\",\"sid\":\"\"} -> {ok,sid,segments:[{id,kind:audio.seg|audio.gap,path,from,to,bytes,valid,reason,codec,rate,speech_ms}]} sid 省略=当前/最近一次会话; 被抢麦/通话中/配额满/写不进磁盘一律写 valid:false 的 gap 而不是丢弃(假录音比没录音危险得多); bytes 是 close 后的磁盘真实长度, 与声称写入量对不上的分片一律降级成 reason=io 的缺口",
            "/sense/perm" to "POST /sense/perm body {\"action\":\"status|request|settings\",\"kinds\":[\"mic\",\"loc\",\"loc_fine\",\"near\",\"cal\",\"motion\"],\"wait_ms\":0}\n                                   -> {ok,kinds:{<kind>:{granted,blocked,perms}},need:[],blocked:[],requested:[],can_prompt,degraded_to:''|needs_permission|needs_settings|no_activity} 采集类 dangerous 权限的按需申请(manifest 声明 ≠ 已授予): request 只在 GA 前台时弹系统框(平台要求), 且只该由用户显式动作触发; blocked=用户已选\"不再询问\", 系统不再弹框 ⇒ action=settings 深链应用详情页; wait_ms>0 = 有界等用户点完再回真值",
            "/sense/keepalive" to "POST /sense/keepalive body {\"action\":\"status|settings\"} -> {ok,ignoring_batt,bg_restricted,needs_setup,manufacturer,vendor_hint,opened} 保活自检(A16): 探测电池白名单/后台受限, 按 ROM 出定制引导文案(vendor_hint); action=settings 拉起电池豁免请求或应用详情页。needs_setup=true 时长时采集有被杀风险, 应引导用户按 vendor_hint 操作。纯查询不改系统状态",
        )

        val HELP: String by lazy {
            val header = "GA bus v${Bus.VER} @127.0.0.1:${Bus.boundPort}  (正典封装: files/ga/droid.py, 优先用它)"
            (listOf(header) + ROUTE_DOCS.map { it.second }).joinToString("\n")
        }
    }

    private fun json(s: String) = newFixedLengthResponse(Response.Status.OK, "application/json", s)

    // 路由注册表：path -> handler。取代原 if/else when 链，端点集合/路径/参数/响应体逐字不变，
    // 未命中路径落 else 分支返回 HELP（404 即文档，行为不变）。
    private val routes: Map<String, (IHTTPSession, Map<String, String>) -> Response> = linkedMapOf(
        "/ping" to { _: IHTTPSession, _: Map<String, String> ->
            val service = BusA11yService.instance
            val geometry = service?.screenGeometry()
            json(JSONObject()
                .put("ver", Bus.VER)
                .put("a11y", service != null)
                .put("pkg", service?.foregroundPkg() ?: "")
                .put("rot", geometry?.rot ?: 0)
                .put("w", geometry?.w ?: 0)
                .put("h", geometry?.h ?: 0)
                .put("loaded", JSONArray(Onnx.loaded())).toString())
        },
        "/onnx/info" to { _, p ->
            json(Onnx.info(p["model"] ?: throw RuntimeException("need ?model=<abspath>")))
        },
        "/onnx/run" to { session, p ->
            val len = (session.headers["content-length"] ?: "0").toInt()
            val body = ByteArray(len)
            DataInputStream(session.inputStream).readFully(body)
            val out = Onnx.run(p["model"] ?: throw RuntimeException("need ?model=<abspath>"), body)
            newFixedLengthResponse(Response.Status.OK, "application/octet-stream",
                ByteArrayInputStream(out), out.size.toLong())
        },
        "/a11y/dump" to { _, p ->
            json(svc().dump(p["full"] == "1"))
        },
        "/a11y/snapshot" to { _, p ->
            json(svc().uiSnapshot(p["pkg"] ?: error("need expected package")).toString())
        },
        "/a11y/shot" to { _, p ->
            val bytes = svc().shot(p["q"]?.toInt())
            newFixedLengthResponse(Response.Status.OK,
                if (p["q"] != null) "image/jpeg" else "image/png",
                ByteArrayInputStream(bytes), bytes.size.toLong())
        },
        "/a11y/act" to { session, _ ->
            val len = (session.headers["content-length"] ?: "0").toInt()
            val body = ByteArray(len)
            DataInputStream(session.inputStream).readFully(body)
            json(svc().act(JSONObject(String(body, Charsets.UTF_8))))
        },
        "/adb/pair" to { session, _ ->
            val b = readJson(session)
            val msg = AdbController.pair(adbCtx(),
                b.optString("host", "127.0.0.1"), b.getInt("port"), b.getString("code"))
            json(JSONObject().put("ok", 1).put("msg", msg).toString())
        },
        "/adb/connect" to { session, _ ->
            val b = readJson(session)
            val msg = AdbController.connect(adbCtx(),
                b.optString("host", "127.0.0.1"), b.optInt("port", 0))   // port=0 ⇒ 自动发现(复用端口→5555→mDNS)
            json(JSONObject().put("ok", 1).put("msg", msg).toString())
        },
        "/adb/shell" to { session, _ ->
            val b = readJson(session)
            val out = AdbController.shell(adbCtx(),
                b.getString("cmd"), b.optLong("timeout_ms", 30_000L),
                b.optInt("max_bytes", AdbController.DEFAULT_MAX_BYTES))
            json(JSONObject().put("out", out).toString())
        },
        "/adb/shell_detached" to { session, _ ->
            val b = readJson(session)
            val tag = AdbController.shellDetached(adbCtx(), b.getString("tag"), b.getString("cmd"))
            json(JSONObject().put("ok", 1).put("tag", tag).toString())
        },
        "/adb/shell_close" to { session, _ ->
            val b = readJson(session)
            json(JSONObject().put("ok", 1)
                .put("closed", AdbController.closeDetached(b.getString("tag"))).toString())
        },
        "/adb/status" to { _, _ ->
            val s = AdbController.status(adbCtx())
            json(JSONObject()
                .put("connected", s.connected)
                .put("paired", s.paired)
                .put("error", s.error)
                .put("port", s.port).toString())
        },
        "/web/ensure" to { _, _ -> json(WebController.ensure(adbCtx())) },
        "/web/ensure_fg" to { _, _ -> json(AgentBrowser.ensure(adbCtx())) },   // 前台任务浏览器(可见+可截图+可CDP), webcdp role='fg' 默认路
        "/notifications" to { _, _ -> json(notifSvc().getNotifications()) },
        "/notifications/reply" to { session, _ ->
            val b = readJson(session)
            val ok = notifSvc().replyNotification(b.getString("key"), b.getString("text"))
            json(JSONObject().put("ok", ok).toString())
        },
        "/notifications/dismiss" to { session, _ ->
            val b = readJson(session)
            val ok = notifSvc().dismissNotification(b.getString("key"))
            json(JSONObject().put("ok", ok).toString())
        },
        "/notifications/dismiss_pkg" to { session, _ ->
            val b = readJson(session)
            val count = notifSvc().dismissByPackage(b.getString("pkg"))
            json(JSONObject().put("count", count).toString())
        },
        "/notifications/status" to { _, _ ->
            json(JSONObject().put("enabled", NotifService.instance != null).toString())
        },
        "/notif-trigger/start" to { session, _ ->
            notifTriggerJson {
                val b = readJson(session)
                NativeNotifTrigger.start(adbCtx(), b.getJSONArray("rules"))
            }
        },
        "/notif-trigger/status" to { _, _ ->
            notifTriggerJson { NativeNotifTrigger.status(adbCtx()) }
        },
        "/notif-trigger/rules" to { _, _ ->
            notifTriggerJson { NativeNotifTrigger.rules(adbCtx()) }
        },
        "/notif-trigger/rules/add" to { session, _ ->
            notifTriggerJson {
                val b = readJson(session)
                NativeNotifTrigger.addRule(adbCtx(), b.opt("rule"))
            }
        },
        "/notif-trigger/rules/set-enabled" to { session, _ ->
            notifTriggerJson {
                val b = readJson(session)
                NativeNotifTrigger.setRuleEnabled(adbCtx(), b.opt("id"), b.opt("enabled"))
            }
        },
        "/notif-trigger/rules/delete" to { session, _ ->
            notifTriggerJson {
                val b = readJson(session)
                NativeNotifTrigger.deleteRule(adbCtx(), b.opt("id"))
            }
        },
        "/notif-trigger/stop" to { _, _ ->
            notifTriggerJson { NativeNotifTrigger.stop(adbCtx()) }
        },
        "/alarm/set" to { session, _ ->
            val b = readJson(session)
            AlarmSched.set(adbCtx(), b.getString("id"),
                b.getLong("at"), b.optLong("every", 0L), b.getString("prompt"))
            json(JSONObject().put("ok", 1).toString())
        },
        "/alarm/del" to { session, _ ->
            val b = readJson(session)
            AlarmSched.del(adbCtx(), b.getString("id"))
            json(JSONObject().put("ok", 1).toString())
        },
        "/alarm/list" to { _, _ ->
            json(JSONObject().put("alarms", AlarmSched.list(adbCtx())).toString())
        },
        // --- GA 门控入网 (tsnet 嵌入; py 正典壳 = gacore/ganet.py, 凭据链在 py 侧) ---
        "/net/join" to { session, _ ->
            val b = readJson(session)
            json(GaNet.join(adbCtx(),
                b.getString("controlUrl"), b.optString("authKey", ""),
                b.optString("hostname", "ga-phone"),
                b.optInt("forwardPort", 0), b.optString("remoteAddr", "")))
        },
        "/net/forward" to { session, _ ->
            val b = readJson(session)
            json(GaNet.forward(b.getInt("forwardPort"), b.getString("remoteAddr")))
        },
        "/net/status" to { _, _ -> json(GaNet.status()) },
        "/net/dialtest" to { _, p ->
            json(JSONObject()
                .put("err", GaNet.dialTest(p["addr"] ?: "100.64.0.1:22")).toString())   // 排障: 经 tsnet 拨一次目标
        },
        "/net/down" to { _, _ ->
            GaNet.down()
            json(JSONObject().put("ok", 1).toString())
        },
        "/sense/loc" to { _, p ->
            senseJson { Sense.loc(adbCtx(), p["mode"] ?: "once", p["timeout_ms"]?.toLongOrNull() ?: 8000L) }
        },
        "/sense/near" to { _, p -> senseJson { Sense.near(adbCtx(), p["ms"]?.toLongOrNull() ?: 4000L) } },
        "/sense/cal" to { _, p ->
            senseJson {
                Sense.cal(adbCtx(), p["from"]?.toLongOrNull() ?: 0L, p["to"]?.toLongOrNull() ?: 0L,
                    p["limit"]?.toIntOrNull() ?: 50)
            }
        },
        "/sense/motion" to { _, _ -> senseJson { Sense.motion(adbCtx()) } },
        "/sense/session" to { session, _ -> senseJson { Sense.session(adbCtx(), senseBody(session)) } },
        "/sense/mic" to { session, _ -> senseJson { Sense.mic(adbCtx(), senseBody(session)) } },
        "/sense/perm" to { session, _ -> senseJson { Sense.perm(adbCtx(), senseBody(session)) } },
        "/sense/keepalive" to { session, _ -> senseJson { Sense.keepalive(adbCtx(), senseBody(session)) } },
    )

    override fun serve(session: IHTTPSession): Response {
        if (!auth.accepts(session.headers["authorization"])) {
            return newFixedLengthResponse(Response.Status.UNAUTHORIZED, "application/json", "{\"error\":\"unauthorized\"}")
        }
        return try {
            val p = session.parameters.mapValues { it.value[0] }
            val handler = routes[session.uri]
            if (handler != null) handler(session, p)
            else newFixedLengthResponse(Response.Status.NOT_FOUND, "text/plain", HELP)
        } catch (e: Exception) {
            android.util.Log.e("GA", "bus serve error", e)
            newFixedLengthResponse(Response.Status.INTERNAL_ERROR, "application/json",
                JSONObject().put("error", e.toString()).toString())
        }
    }

    private fun notifTriggerJson(action: () -> JSONObject): Response {
        return try {
            json(action().toString())
        } catch (e: Exception) {
            json(JSONObject()
                .put("ok", false)
                .put("running", false)
                .put("listener_enabled", NotifService.instance != null)
                .put("rule_count", 0)
                .put("error", e.message ?: e.toString())
                .toString())
        }
    }

    // 采集类端点永不把异常抛给上层: L1/L2/L3 只认「统一形状 + granted/caps/degraded_to」, 对 Android 版本/GMS/厂商 ROM 零感知。
    //  catch Throwable 而非 Exception: 厂商 ROM 缺方法/改签名会抛 Error(AbstractMethodError/NoSuchMethodError), 那正是最该降级的场景。
    private fun senseJson(action: () -> JSONObject): Response =
        json(try { action().toString() } catch (e: Throwable) {
            JSONObject().put("ok", 0).put("error", e.message ?: e.toString()).put("degraded_to", "error").toString()
        })

    // 无 body / body 非 JSON 一律当空对象: 落到 action 分支的 unknown_action 就地失败, 而不是 500(调用方要能分清"参数错"与"系统故障")
    private fun senseBody(session: IHTTPSession): JSONObject =
        runCatching { readJson(session) }.getOrDefault(JSONObject())

    private fun svc() = BusA11yService.instance
        ?: throw RuntimeException("accessibility service not enabled: 设置>无障碍>GA 开启")

    private fun notifSvc() = NotifService.instance
        ?: throw RuntimeException("notification listener not enabled: 设置>通知>通知使用权限>GA 允许")

    private fun adbCtx() = Bus.appCtx
        ?: throw RuntimeException("bus context 未就绪")

    private fun readJson(session: IHTTPSession): JSONObject {
        val len = (session.headers["content-length"] ?: "0").toInt()
        val body = ByteArray(len)
        DataInputStream(session.inputStream).readFully(body)
        return JSONObject(String(body, Charsets.UTF_8))
    }
}
