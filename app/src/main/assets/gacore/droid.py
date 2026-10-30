# -*- coding: utf-8 -*-
"""droid: GA Android 能力正典壳 (files/ga/droid.py) — agent 操作手机/本地模型的唯一入口
背后是 APK 内 HTTP 总线(127.0.0.1, 默认 18765), 不要绕过本模块拼 HTTP。
服务状态唯一判据 = droid.ping()。bus_port.txt 是内部实现且 code_run cwd=temp 相对路径看不到它,
禁止用文件存在性判断服务状态; ping 不通=总线组件未监听(重启 App 恢复), 与 agent/会话是否运行无关。
红线四则(完整规程=../memory/phone_use.md, 操作手机前必读):
  ①坐标优先来源=dump/ui_detect/ocr 文字框; 无文字图标先 `look()`(装了 Android UI 检测模型时它给
    `type='icon'` 的框, 真机 31ms), 找不到再 `droid.ask_point()`(固定问句+只认 0-1000+映射回整屏,
    数对原样当 gui_act 的 rel)。VLM(视觉大模型)只用于**静态**界面上的语义理解与定位。
    **canvas/自绘/动画画面上的 VLM 坐标一律禁用**(见 ①-b): 那种画面没有可信锚, VLM 的坐标是猜。
    ①-b: dump 空壳(canvas 游戏)时 look() 也只有文字; 若目标连文字都不是, 按 phone_use §0.1 第 6/7 条
    即停或 ask_user, 不要用 VLM 坐标操作动态画面。
  ②paste 后看返回: hit=True=已确认上屏; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级;
    ime_label 仅为元数据, 只有 ime_hint 可点击; hit=False 且无 uncertain 才按 hint 递进。
  ③一步一验: 一个操作→短暂等待→dump/shot 验新状态; 无变化立即停下诊断, 禁盲目重试、禁把多步决策写进一个大脚本。
  ④顶部(状态栏下~400px)点击防劫持: 重新 dump/shot 后立即 tap; tap 后前台变成非预期 App→立即 back 撤出。
用法:
    import droid
    droid.ping()                    # {ver, a11y, pkg:真实前台包名, rot:旋转0..3, w/h:物理屏宽高, loaded}; Agent 手势期间浮窗触摸穿透，结束后恢复用户交互
    els = droid.dump()              # 屏幕元素 [{t,d,x,y,click,edit,...}], full=True 含全部节点
    droid.find('好评优先')           # 按 t/d 子串找节点(exact=True 全等; clickable=True 只要可点), 每项带中心 x,y —— 别再手写列表推导
    droid.tap_text('好评优先')       # find→唯一命中→tap; 多命中抛 ValueError 列候选(用 exact/idx), 0 命中抛 LookupError(转 look())
    dets = droid.look()             # 视觉一步: shot+ui_detect, 每项带中心 x,y/label/cls; dump 为空(自绘/敏感)时用它, 不要 print 整个图像数组
    droid.look(roi='top')           # 只检测上 1/3 屏(排序条/搜索框在上面时): 耗时随面积降; roi 也可 'upper'|'middle'|'lower'|'bottom' 或 (x1,y1,x2,y2); 屏幕没变时自动返回缓存('cached':True)
    w, h = droid.screen()           # 当前朝向屏幕尺寸; 位置判断用比例(顶栏 <0.12h, 底栏 >0.9h), 绝不把绝对坐标写进记忆
    droid.tap(x, y); droid.swipe(x1,y1,x2,y2,dur=300)  # 长按=swipe同点dur>=800(已验:弹快捷菜单); swipe端点已自动夹进安全带避开系统手势区; 两者默认带前后截图 diff 后验(变化<0.05%→hint 点空/未滚成)
    droid.tap_rel(500, 500)         # 0-1000 归一化坐标(左上原点, x右y下): 仅当目标本身就是相对区域(棋盘中心/四角/比例位)且 look()/dump() 均无目标时的最后一级; 不是给认不准的按钮猜坐标
    droid.ask_point('放大镜', roi='title')  # 问"屏幕上某物在哪"→整屏 0-1000 数对(可直接当 gui_act 的 rel): look() 的 OCR 看不到无文字图标时的定位通道; 问句/单位/解析都定死, 别自己写 ask_vision 问坐标
    droid.scroll('up')              # 安全滚动(手指方向); 必须检查 scrolled/evidence/uncertain; uncertain=True=观察不可用/结论不确定, 不是已验证未滚动, 禁盲目重试
    droid.scroll_view('down')       # 安全滚动, 参数=浏览方向('down' 看下方内容/'up' 看上方); 必须检查 scrolled/evidence/uncertain; uncertain=True=观察不可用/结论不确定, 不是已验证未滚动, 禁盲目重试 (旧 scroll() 参数是手指方向, 与此相反)
    droid.back(); droid.home()
    droid.panel('right')            # 物理下拉控制中心(录屏/手电等磁贴; left/center=通知栏)。droid.quick_settings()/notifications()=AOSP 语义全局动作(部分 OEM 够不到控制中心→用 panel)
    droid.dismiss_shade()           # 用完快捷设置/通知栏必调: 确定性收起面板(Android16 上 home() 可能留下透明面板层吃掉后续所有 tap)
    droid.paste('文本')             # 剪贴板输入; hit=True=已确认上屏; hit=False, uncertain=True 时禁止重复输入或盲目降级
    droid.key('ENTER')              # 对聚焦输入框触发IME动作(搜索/发送/换行); droid.launch('包名') 启动app
    img = droid.shot()              # BGR ndarray; droid.shot('/sdcard/a.png') 存文件
    els = droid.ui_detect(img)      # Android专调YOLO(21类)+OCR [{bbox,type:'icon'|'text',label,cls,confidence}]; cls=控件语义(Icon/Image/EditText/Switch/TextButton/Toolbar/Bottom_Navigation/Card...), 无文字图标的label回退为cls
    res = droid.ocr(img)            # [(box4x2, text, score), ...]
    droid.sensitive_status()        # 微信 act="gui": 截图/识别/手势，无固定次数预算；不得读节点、节点输入或快捷回复
    droid.sensitive_unlock(pkg, actions=20, reason="...")  # 仅兼容旧 locked 策略；微信 GUI 无需调用
    droid.sensitive_env_report()    # 只读环境自检: root/LSPosed/VPN 等会被微信计分的信号 + 用户侧建议; 用户问"为什么被风控/怎么防封"时先给这个
    droid.sensitive_risk_event(pkg, kind='verify|kicked|captcha', note='…')  # 屏幕上认出实名核验/账号状态异常/安全验证时**必调**再终止任务: 该 App 进入 7 天零注入冷却(unlock 也拒)
输入三则: ①任何输入一律 paste(剪贴板), 没有逐键打字 API。最优路径=tap聚焦→paste(text)→读返回:
  hit=True=已确认上屏, 无需再 dump/shot 验; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级;
  ime_label 仅为元数据, 只有 ime_hint 可点击; hit=False 且无 uncertain 才按 hint 递进(细则=phone_use.md §3)。
  ②替换/清空: 长按输入框(swipe同点dur>=800)→弹全选菜单→全选, 然后 paste 覆盖即替换; 清空则全选后 tap 软键盘退格键。
  ③软键盘按键靠 shot+ui_detect 找: 符号键 OCR 常误标(退格⌫可能标成'X', 回车/搜索🔍可能标成'O'), 勿信标签;
    按位置找: 退格在字母区右缘, 回车/搜索/发送在键盘右下角(图标随场景变), 各厂商键盘布局不同, 以当帧检测为准。
ONNX: 任意模型 -> droid.ort_shim() 后 import onnxruntime 照常写, 推理在 APK 内 ORT 执行。
ADB(本机自连无线调试, 补 A11y 外 shell 能力): 用户手动开无线调试后 → droid.adb_pair(code,port)(仅首次) → droid.adb_connect()(无参, 端口自动发现) → droid.adb_shell('input tap 500 800' | 'am start ...' | 'dumpsys ...')。
AppFunction 原子能力(Android16+, 需 self-ADB 已连): droid.appfn_list() 枚举本机注册能力(各 OS 注册不同, 以实测返回为准, 不预设清单) → droid.appfn_call(包名, '类全名#方法', {参数}); 命中注册能力优先于 GUI(零轮次/无坐标漂移), 未注册回正常定位阶梯。
定时唤起 agent(非用户起床铃): droid.alarm_set(id, at_ms, every_ms=0, prompt) / alarm_list() / alarm_del(id)。
  仅当目标是「到点让 GA 后台跑一段任务/新会话」时用; 用户说「设个闹钟/几点叫我」→走系统时钟 App(GUI), 不要用本 API。
  at=下次 epoch ms; every=0 一次, >0 周期 ms; 到期 call_once(prompt) 新会话进抽屉。
  例: import time; droid.alarm_set('daily_brief', int(time.time()*1000)+3600_000, every=86400_000, prompt='汇总未读通知并简报')
"""
import json
import os
import re
import struct
import sys
import threading
import time
from collections import deque
import requests
import bus_auth
import run_guard   # 僵尸线程护栏: code_run 超时/被停后, 后台线程每次操作手机在 _act/adb_shell 被拒, 不再驱动整机
import run_metrics   # 只观测: 动作后验计时打点(SPEC Phase 0); 不参与任何门禁/几何判定
import phone_ledger   # 动作账本与三档防循环(SPEC W3): 纯函数模块; droid 落账+执行边界守卫, agent 侧(ga_android)读 hint
import geom          # 坐标换算唯一权威(0-1000 ↔ 像素) + 实测系统 UI 锚带; 纯函数无设备依赖
_LEDGER = phone_ledger.ACTIVE   # 进程级共享账本: 与 ga_android 每轮提示注入同一实例

# ---- operation trace(SPEC L1 录制源): 每次设备操作带紧凑观测快照, recipe_record 据此机械派生配方 ----
_TRACE = deque(maxlen=64)
_LAST_OBS = None                # 最近一次观测(dump/look 更新); 动作落账时附带, 供定位器推导
_OBS_STALE = True               # 上次观测之后有没有派发过动作: 动作会改屏幕, 让观测失效


def _compact_obs(obs, cap=120):
    """观测紧凑快照: 只留定位器推导所需字段(t/d/cls/b、label/bbox、screen、pkg)。"""
    if not obs:
        return None
    nodes = [{"t": n.get("t") or "", "d": n.get("d") or "", "cls": n.get("cls") or "",
              "b": n.get("b") or ""} for n in (obs.get("nodes") or [])[:cap]]
    dets = [{"label": d.get("label") or "", "cls": d.get("cls") or "", "bbox": d.get("bbox")}
            for d in (obs.get("detections") or [])[:cap]]
    return {"nodes": nodes, "detections": dets,
            "screen": obs.get("screen"), "pkg": obs.get("pkg")}


def _trace(kind, args=None, result=None, obs="auto"):
    _TRACE.append({"kind": kind, "args": args or {}, "result": result or {},
                   "obs": _LAST_OBS if obs == "auto" else obs, "ts": time.time()})


def reset_trace():
    """任务边界: 清空操作痕迹与末次观测。两者都是任务级状态——不清的话,
    上个任务(或上一次 recipe_run 自己)产生的 dump/tap 痕迹会混进本次 recipe_record,
    录出的配方步骤属于别的任务。"""
    global _LAST_OBS, _OBS_STALE
    _TRACE.clear()
    _LAST_OBS = None
    _OBS_STALE = True               # 新任务还没观测过, 第一次动作前必须补

_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(_DIR, "models", "ui_detect_v1")  # 管线py+onnx 捆绑目录
class _BusSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs['headers'] = {**kwargs.get('headers', {}), **bus_auth.headers(url)}
        kwargs['proxies'] = {'http': None, 'https': None}
        return super().request(method, url, **kwargs)

_SESSION = _BusSession()
_SESSION.trust_env = False


def _is_pc():
    return os.name == "nt" or not _DIR.startswith("/data/")


def _remote_model_path(model_path):
    """设备侧绝对路径原样透传; 只有 PC 调试才把仓库路径映射到 APK 默认私有目录。

    ⚠️ 设备侧前缀要同时认 /data/user/ 和 /data/data/: Android 上 /data/user/0 是指向
    /data/data 的符号链接, 而 detector_models.model_path() 对用户自装模型做了
    Path.resolve(), 会把 /data/user/0/... 解析成 /data/data/...。只认 /data/user/ 时,
    自装检测器会落进下面的"按 basename 重建"分支, 被拼成
    models/ui_detect_v1/models/<name> → Kotlin 侧报 model not found → look() 整体失败。
    真机 2026-10-28 实证: 装上 YOLO 后 droid.look 反而"执行失败", 视觉静默降级成纯 OCR。

    (本函数曾有两个定义, 前一个带 _is_pc() 守卫的被后一个完全遮蔽——死代码, 已删。)"""
    p = str(model_path).replace("\\", "/")
    if p.startswith(("/data/user/", "/data/data/")):
        return p                      # 设备侧绝对路径(App 内 ppocr_engine/detector_models 传的正是它):
                                     # 包名与子目录(user_models/ 等)都在路径里, 原样透传, 禁用 GA_PACKAGE 重建
                                     # (旧实现丢弃目录+默认包名重建 → debug 包全部 model not found, 本地视觉整链死掉)
    if not _is_pc():
        return p                      # 设备侧其余路径(相对/其它绝对)也原样透传, 由 Kotlin 侧按自己的上下文解析
    name = os.path.basename(p)
    if not name:
        raise ValueError("empty model path")
    return "/data/user/0/" + os.environ.get("GA_PACKAGE", "io.github.shenhaostu.gagent") + "/files/ga/models/ui_detect_v1/models/" + name


_PORT_DEFAULT = "18765"   # BusServer.kt PORT 常量; bus_port.txt 只是它的落盘提示, ping 才是服务真值

def _base():
    """总线地址。bus_port.txt(Kotlin 绑定成功后写)缺失 ≠ 服务未启动(绑定失败静默/文件被清):
    回退默认端口并 ping 验活(校验 ver 字段防撞他人服务); 验活失败给精准诊断, 杜绝「核心服务未启动」误判。"""
    try:
        with open(os.path.join(_DIR, "bus_port.txt")) as f:
            port = f.read().strip()
    except OSError:
        port = ""
    if port.isdigit():
        return "http://127.0.0.1:" + port
    else:   # 缺失/空串/损坏(非原子写截断窗口)统一走回退+验活
        base = "http://127.0.0.1:" + _PORT_DEFAULT
        try:
            j = _SESSION.get(base + "/ping", timeout=3).json()
            if isinstance(j, dict) and "ver" in j:
                return base
        except Exception:
            pass
        raise RuntimeError("APK 内设备总线未监听(bus_port.txt 缺失且默认端口 " + _PORT_DEFAULT + " ping 不通): "
                           "进程内 HTTP 组件绑定失败, 重启 App 即恢复。这与 agent/会话是否运行无关, "
                           "不存在『启动核心服务』按钮, 勿引导用户寻找。")


def _check(r):
    if r.headers.get("content-type", "").startswith("application/json"):
        j = r.json()
        if isinstance(j, dict) and "error" in j:
            raise RuntimeError(j["error"])
        return j
    return r.content


def _get(path, **params):
    run_guard.check()   # 只读入口(ping/dump/shot/onnx); 加检查点让僵尸线程的读屏循环也尽早自毁省资源(无副作用但止损)
    return _check(_SESSION.get(_base() + path, params=params, timeout=60))


def ping():
    return _get("/ping")

def _fg():
    try: return ping().get("pkg", "")
    except Exception: return ""

def _self_package():
    """GA 自身包名: 优先从模块路径(/data/user/0/<pkg>/files/ga)推导——debug/release 通吃。
    不再依赖无人设置的 GA_PACKAGE(旧默认值是正式包名, debug 包会把自身当前台, 引发 launch 后 ping 异常)。"""
    m = re.match(r"^/data/user/\d+/([^/]+)/files", _DIR.replace("\\", "/"))
    return m.group(1) if m else os.environ.get("GA_PACKAGE", "io.github.shenhaostu.gagent")

_SELF_PKG = _self_package()   # getWindows 已排除 GA 自身: 观察到它=抖动, 不是真前台(phone_use.md §1 "直接重查")

def _resolve_fg(pkg=""):
    """把一次前台观察解析成可信包名; 空串/GA 自身视为未解析 → 有界重查; 仍未解析返回 ""。
    只用便宜的 ping, 不读 a11y 树。"""
    for _ in range(2):
        if pkg and pkg != _SELF_PKG:
            return pkg
        time.sleep(0.15); pkg = _fg()
    return pkg if pkg and pkg != _SELF_PKG else ""

# Visual-only packages never expose UI trees. GUI tasks have no per-app action quota;
# cancellation and observed account/security challenges still stop execution.
SENSITIVE_APPS = {
    "com.tencent.mm": {"dump": "blank", "act": "gui", "nofloat": True},
}
SENSITIVE_PKGS = frozenset(SENSITIVE_APPS)   # 派生兼容量(勿手编辑): 供按包名判定处使用, 清单只在 SENSITIVE_APPS 维护

_STRICTEST = {"dump": "blank"}   # fail-closed: 前台未解析按最严策略——漏判=读树=封号, 误判仅多走一次视觉路径
                                 # (只锁 dump 不锁 act: 刚 launch 后前台常短暂未解析, 若也锁注入会把所有 App 的首次 tap 打断)

# --- 零注入门禁(act="locked") ---
_INJECT_OPS = frozenset({"tap", "swipe", "paste", "key", "panel", "quicksettings", "notifications", "clipboard"})
_UNLOCK_FILE = os.path.join(_DIR, "temp", ".sensitive_unlock.json")
_UNLOCK_TTL = 1800  # 有限任务窗口；新任务不得复用先前授权，预算不是规避服务方风控的保证

def _unlock_read():
    try:
        with open(_UNLOCK_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _unlock_write(state):
    try:
        os.makedirs(os.path.dirname(_UNLOCK_FILE), exist_ok=True)
        with open(_UNLOCK_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass

_RISK_FILE = os.path.join(_DIR, "temp", ".sensitive_risk.json")
_RISK_COOLDOWN_S = 7 * 86400   # 风控事件后的零注入冷却期(SOP §3.5「≥7 天」落代码)

def sensitive_risk_event(pkg, kind="verify", note=""):
    """记录一次风控事件(实名核验页 / 「账号状态异常」踢下线 / 安全验证)。记录后该 App 进入 7 天零注入冷却:
    sensitive_unlock 直接拒绝(即使用户同意也不放行——上一次同意的后果就是踢下线), 只能只读。
    agent 在屏幕上认出 §2.1 的风控信号时**必须**调本函数再终止任务; 用户重登不会清除冷却(重登本身也是计分项)。"""
    st = _risk_read()
    st[pkg] = {"kind": str(kind)[:32], "note": str(note)[:80], "ts": time.time()}
    try:
        os.makedirs(os.path.dirname(_RISK_FILE), exist_ok=True)
        with open(_RISK_FILE, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False)
    except Exception: pass
    _unlock_write({k: v for k, v in _unlock_read().items() if k != pkg})   # 同时作废现有解锁
    _track("droid_sensitive_risk", {"kind": str(kind)[:32]})
    return {"pkg": pkg, "cooldown_until": st[pkg]["ts"] + _RISK_COOLDOWN_S}

def _risk_read():
    try:
        with open(_RISK_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def _risk_cooldown_left(pkg):
    t = (_risk_read().get(pkg) or {}).get("ts", 0)
    return max(0.0, t + _RISK_COOLDOWN_S - time.time()) if t else 0.0

def sensitive_unlock(pkg, actions=None, reason=""):
    """为用户明确要求的当前 GUI 任务授予有限动作预算；上限由策略表定义，有效 30 分钟。
    用户的明确任务指令允许导航，不要求先人工停在目标页。一个任务只解锁一次，用完即止，不续杯。
    这不授权发送、提交订单或支付；这些动作仍遵守任务授权边界。返回 {pkg, actions, until}。
    未入册或未上锁的 App 调本函数是 no-op(返回 {}), 勿把它当通用开关。该 App 处于风控冷却期(sensitive_risk_event 后 7 天)时抛错。"""
    pol = SENSITIVE_APPS.get(pkg, {})
    if pol.get("act") != "locked":
        return {}
    left = _risk_cooldown_left(pkg)
    if left > 0:
        raise RuntimeError(f"{pkg} 处于风控冷却期(上次风控事件后 7 天零注入, 还剩 {int(left // 3600)} 小时): 不放行任何注入, 即使用户同意。"
                           f"只能 shot()+ocr 只读; 需要操作请用户本人手动完成。")
    cap = int(pol.get("budget", 3))
    n = cap if actions is None else max(1, min(int(actions), cap))
    st = _unlock_read()
    st[pkg] = {"left": n, "until": time.time() + _UNLOCK_TTL, "last_ts": 0.0, "reason": str(reason)[:80]}
    _unlock_write(st)
    _track("droid_sensitive_unlock", {"actions": n})   # 只记数量, 不记包名/理由
    return {"pkg": pkg, "actions": n, "until": st[pkg]["until"]}

def sensitive_env_report():
    """只读的设备环境风控自检(给用户看, 不做任何修改): 列出微信这类 App 会计分的环境信号——root 管理器/LSPosed 类模块管理器是否在装,
    VPN 是否在跑, 无线调试是否开着, GA 悬浮窗权限。结论只描述事实 + 建议(排除微信走代理/对微信隐藏 root 模块 等), 由用户决定。
    实现只用 pkgs()(启动器列表)与 ping(), 不读任何第三方 App 数据。GA 端的对策(零注入门禁/nofloat)已在代码里, 本函数补的是「用户侧看得见」。"""
    try: apps = {a.get("pkg", "") for a in pkgs()}
    except Exception: apps = set()
    ROOT_MGRS = {"com.rifsxd.ksunext": "KernelSU Next", "me.weishu.kernelsu": "KernelSU", "com.topjohnwu.magisk": "Magisk", "io.github.a13e300.ksuwebui": "KSU WebUI"}
    HOOK_MGRS = {"org.lsposed.manager": "LSPosed", "org.frknkrc44.hma_oss": "HMA(隐藏应用列表)", "com.close.hook.ads": "AdClose", "de.robv.android.xposed.installer": "Xposed"}
    VPN_APPS = {"com.follow.clash": "FlClash", "com.github.kr328.clash": "Clash", "com.v2ray.ang": "v2rayNG", "com.wireguard.android": "WireGuard", "org.getlantern.lantern": "Lantern", "com.saily.android": "Saily(eSIM)"}
    found = lambda m: [v for k, v in m.items() if k in apps]
    report = {"root_managers": found(ROOT_MGRS), "hook_managers": found(HOOK_MGRS), "vpn_apps": found(VPN_APPS),
              "locked_apps": sorted(p for p, pol in SENSITIVE_APPS.items() if pol.get("act") == "locked")}
    advice = []
    if report["root_managers"]: advice.append("root 管理器在装: 对微信开「卸载模块/不授权」, 并在管理器里把微信加入排除列表")
    if report["hook_managers"]: advice.append("LSPosed/Xposed 类在装: 作用域移除微信; 用 HMA 对微信隐藏管理器本身")
    if report["vpn_apps"]: advice.append("VPN/代理在装: 分应用代理把 com.tencent.mm 排除(直连, 出口=SIM 归属地)")
    advice.append("风控事件(实名核验/账号状态异常)后 ≥7 天不对该 App 做任何注入; 重登后 ≥72h 只读")
    report["advice"] = advice
    report["note"] = "以上仅列已装 App 名(启动器可见), 不读取其数据; GA 侧对策(零注入门禁/不叠悬浮窗)已在代码内生效"
    return report


def sensitive_status(pkg=None):
    """查看零注入门禁状态: {pkg: {left, until_s}}; pkg=None 列全部已入册 locked App。"""
    st = _unlock_read(); now = time.time(); out = {}
    for p, pol in SENSITIVE_APPS.items():
        if pol.get("act") != "locked" or (pkg and p != pkg): continue
        t = st.get(p) or {}
        live = t and t.get("until", 0) > now and t.get("left", 0) > 0
        out[p] = {"locked": True, "left": int(t.get("left", 0)) if live else 0,
                  "until_s": int(t.get("until", 0) - now) if live else 0, "budget": pol.get("budget"), "min_gap": pol.get("min_gap"),
                  "risk_cooldown_h": int(_risk_cooldown_left(p) // 3600)}
    return out

def _gate_injection(op, pkg=None):
    """注入动作唯一门禁: 目标 App(默认=当前前台; 通知回复等旁路传入目标包名)是 act="locked" 时, 无解锁/超时/预算耗尽一律
    抛错(不重试、不降级); 放行时扣预算、补足 min_gap 间隔。返回 (pkg, policy); 非锁定目标返回 ("", {})。
    覆盖面 = a11y 注入(_act) + 通知 RemoteInput 回复(reply_notification) + shell input 注入(adb_shell): 三条能"替用户对该 App 说话/按键"
    的路径共用一道门, 否则门禁只堵 a11y 就是在鼓励绕道。"""
    pkg = _resolve_fg(_fg()) if pkg is None else pkg
    pol = SENSITIVE_APPS.get(pkg, {}) if pkg else {}
    if pol.get("act") == "gui":
        if op in ("reply_notification", "key"):
            raise RuntimeError("纯 GUI 模式：请点击画面上的发送/搜索键，不调用节点或通知接口")
        if _risk_cooldown_left(pkg) > 0:
            raise RuntimeError("该 App 已记录账号/安全验证，请停止操作并由用户处理")
        return pkg, pol
    if pol.get("act") != "locked":
        return "", {}
    st = _unlock_read(); t = st.get(pkg) or {}
    now = time.time()
    if not t or t.get("until", 0) < now or t.get("left", 0) <= 0:
        why = "未解锁" if not t else ("解锁已过期" if t.get("until", 0) < now else "本次解锁预算已用完")
        _track("droid_sensitive_block", {"op": op})
        raise RuntimeError(
            f"{pkg} GUI任务预算不可用({why})，不能执行 {op}。只读请用 shot()+ocr。"
            f"若尚未授权且用户已明确要求当前任务，可调用 droid.sensitive_unlock('{pkg}', actions=20, reason='用户当前任务')，"
            f"上限 {pol.get('budget', 40)} 次/30分钟；已耗尽或过期则停止，不能续杯。每步截图确认新状态，"
            f"命中任何验证/实名/『账号状态异常』页立即终止整个任务并交人, 绝不填、绝不重试。")
    gap = float(pol.get("min_gap", 0) or 0)
    wait = gap - (now - float(t.get("last_ts", 0) or 0))
    if 0 < wait < gap:
        time.sleep(wait)
    t["left"] = int(t.get("left", 0)) - 1; t["last_ts"] = time.time(); st[pkg] = t
    _unlock_write(st)
    _track("droid_sensitive_act", {"op": op, "left": t["left"]})
    return pkg, pol

def _app_policy(pkg=None):
    """敏感 App 策略唯一漏斗(纯函数): dump()/paste 验证/scroll 全部由此取行为, 禁再内联复制判定。
    pkg=None → 内部解析当前前台; pkg==""(解析失败) → 最严策略; 未入册 App → {}(无限制)。"""
    if pkg is None:
        pkg = _resolve_fg(_fg())
    return SENSITIVE_APPS.get(pkg, {}) if pkg else _STRICTEST

def _sensitive_fg(pkg=None):
    """dump 门控薄封装(dump()/paste 验证/scroll 共用): 前台策略要求 dump 置空即 True(含未解析 fail-closed)。"""
    return _app_policy(pkg).get("dump") == "blank"

def _wait_fg(want="", sec=1.0):
    end = time.time() + sec; last = _fg()
    while time.time() < end and want and last != want:
        time.sleep(0.05); last = _fg()
    return last


def dump_state(full=False):
    """dump() 的结构化增量化版本: {nodes, degraded, pkg}。degraded 非空=本次树不可用及原因——
    路由器(L0)据此区分「策略置空(走视觉)/前台未解析(重查后再看)/真空树(真无可交互元素)」,
    这是 SPEC 路由器不变式 1(不选证据缺失通道)的前置; dump() 契约不变(仍返回 list)。"""
    # 敏感 App(SENSITIVE_APPS)会对读 a11y 树者返回**投毒/伪造控件树**并据此上报风控(gandroid-wechat-yolo 红线):
    # 策略 dump="blank" 时一律置空, 迫使上层走纯视觉 shot()+ui_detect/ocr, 绝不拿假节点行动。
    # 未解析前台(ping 抖动)按敏感处理(fail-closed): 漏判=读树=封号, 误判仅多走一次视觉路径, 代价不对称→宁可置空。
    pkg = _resolve_fg(_fg())
    if _sensitive_fg(pkg):
        _track("droid_dump_blank", {"pkg_class": "sensitive" if pkg else "unresolved"})   # 只报枚举不报包名: 区分敏感置空与 fail-closed 抖动
        reason = "sensitive_blank" if pkg else "unresolved_fg"
        return {"nodes": [], "degraded": {"reason": reason, "channel": "dump"}, "pkg": pkg}
    nodes = _get("/a11y/dump", **({"full": 1} if full else {}))
    # 返回 [] 且前台可信 = 真空壳树(SurfaceView 游戏/自绘页): 语义见 phone_use.md §1/§5, 上层直接转视觉, 勿当空 UI 反复重试
    degraded = {"reason": "tree_empty", "channel": "dump"} if not nodes else None
    # 注意: 这里**不**给节点补 rx/ry(0-1000)。补它要一次额外 ping, 而 dump 在每个 tap
    # 前都会走一遍; 而且没必要——x/y 本就是像素, 与 gui_act 的 point 同单位, 原样传即对。
    # 需要千分比的场合(look 结果 / gui_act 动作后的 obs)已经在那些出口补好了。
    return {"nodes": nodes, "degraded": degraded, "pkg": pkg}

def dump(full=False):
    """树观测(纯 list 契约, 历史语义不变): 敏感/未解析置空=[] 信号, 上层转视觉。需要原因码用 dump_state()。"""
    st = dump_state(full=full)
    global _LAST_OBS, _OBS_STALE
    nodes = st["nodes"]
    _LAST_OBS = {"nodes": nodes, "detections": [], "screen": None, "pkg": st.get("pkg")}
    _OBS_STALE = False
    _trace("dump", result={"count": len(nodes)})
    return nodes


def ensure_fresh_obs():
    """观测已因动作失效时才重新 dump; 否则原样返回现有观测。

    gui_act 需要"动作前"的观测来推导 recipe locator。原先每次 tap/swipe/longpress
    都无条件先 dump 一次, 但模型在 code_run 里刚 dump()/look() 过时那是纯浪费——
    真机 39 轮任务里约 20 次 gui_act 各多付一次 a11y 往返。动作经 _act() 派发后才
    标记失效, 所以"模型刚看过屏幕"不再重复 dump; 若那次 dump 拿到空树(敏感 App),
    下一轮照样会重新试, 不会把空观测当成有效缓存。"""
    global _OBS_STALE
    if not _OBS_STALE and _LAST_OBS is not None:
        return _LAST_OBS
    try:
        return dump()
    except Exception:
        return _LAST_OBS


def _record_path(kind):
    """任务级路径计数(挂 analytics_hook._STATE, 随 agent_task_end 扁平上报)。
    惰性 import + 全吞异常: PC 侧调试无 plugins 包也不报错。只报类别枚举, 不报包名/坐标。"""
    try:
        from plugins.analytics_hook import record_path
        record_path(kind)
    except Exception:
        pass


def _act(**body):
    run_guard.check()   # 操作手机(tap/swipe/paste/launch...)唯一入口 → 僵尸线程护栏检查点: 已取消则抛 RunCancelled 自毁
    op = body.get("op")
    if op in _INJECT_OPS:
        _gate_injection(op)                     # 零注入门禁(act="locked" 的敏感 App): 未解锁/超预算直接抛错, 放行则已扣预算+补足节奏下限
                                                # 不在这里改动作形态(不加抖动/不拟人化, phone_use §5): 防封靠"少做+先问+硬预算", 不靠伪装
    _record_path("launch" if op == "launch" else "a11y")   # 任务路径归属: 拉起 app vs 无障碍操作外部 app
    run_guard.check()   # 门禁可能等待；取消后不得再派发。
    ret = _check(_SESSION.post(_base() + "/a11y/act", json=body, timeout=30))
    global _OBS_STALE
    _OBS_STALE = True               # 动作已下发: 屏幕大概率变了, 之前的观测作废
    try: run_metrics.mark_action_dispatched()   # 只观测(SPEC Phase 0): 记"动作已下发"时刻, 供 run_metrics 把随后的稳态等待/截图/对比分摊为 verify_wait。手势已发出, 观测失败绝不能把它变成失败
    except Exception: pass
    return ret


def _track(event, props=None):
    """埋点入 agent 事件队列(temp/.agent_events.jsonl), Kotlin Analytics 排空时统一补身份+脱敏上报。
    只记枚举/数值, 绝不写屏幕内容/坐标以外信息; 任何失败静默——埋点不允许影响操作本身。"""
    try:
        d = os.path.join(_DIR, "temp")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, ".agent_events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "props": props or {}, "ts": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass


def _img_diff_str(before, after):
    import cv2, numpy as np
    if before is None or after is None or before.shape != after.shape: return "diff: n/a"
    d = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
    mask = d > 12; cnt = int(mask.sum()); pct = cnt * 100.0 / (int(mask.size) or 1)
    if not cnt: return "diff: 0.000%"
    ys, xs = np.where(mask); bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return "diff: %.3f%% bbox=%s" % (pct, bbox)


def _screen_geometry(info):
    geometry = {key: int(info[key]) for key in ('w', 'h', 'rot')}
    if geometry['w'] <= 0 or geometry['h'] <= 0 or geometry['rot'] not in range(4):
        raise ValueError('invalid screen geometry')
    return geometry


def _gesture_screen(info, points, expected=None):
    current = _screen_geometry(info)
    if expected is not None and _screen_geometry(expected) != current:
        raise RuntimeError('screen geometry changed; capture and locate the target again')
    for x, y in points:
        if not (0 <= x < current['w'] and 0 <= y < current['h']):
            raise ValueError('coordinate outside the current screen')
    return current


def capture(q=None):
    """Explicit image + screen observation; pass its screen to tap/swipe after locating a target."""
    before = _screen_geometry(ping())
    img = shot(q=q)
    after = _screen_geometry(ping())
    if before != after:
        raise RuntimeError('screen geometry changed during capture; capture again')
    if img is None or img.shape[:2] != (before['h'], before['w']):
        raise RuntimeError('screenshot geometry does not match the display')
    return {'image': img, 'screen': before}


# ---------------- 循环守卫(SPEC W3): 执行边界落账 + 恢复/拒绝 ----------------
def _new_record(kind, point=(), point2=(), value="", screen=()):
    return phone_ledger.ActionRecord(kind=kind, point=point, point2=point2, value=value, screen=screen)

def _no_effect(pct):
    """「无可观察变化」唯一判据(与既有 tap/swipe miss 提示同口径): 时钟跳字/JPEG 噪声都在带内。"""
    return pct <= phone_ledger.EXACT_PCT

def _finger_direction(p1, p2):
    """(起点, 终点) → 手指移动方向; 与 scroll() 的 direction 同口径(手指方向, 不是视图方向)。
    位移不足 1px 判 None——原地长按类手势没有方向可言。四个坐标缺任一即 None:
    本函数跑在 _settle 里, 抛异常会连带毁掉整条动作落账。"""
    if not p1 or not p2 or None in p1[:2] or None in p2[:2]:
        return None
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < 1 and abs(dy) < 1:
        return None
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _trace_args(rec):
    """落 trace 的动作参数。键必须与 recipe.trace_to_recipe 的读取键一一对应——
    错键会让录制字段恒为空(评审实证: scroll 方向全落默认值、paste 文本恒空串)。"""
    if rec.kind in ("tap", "longpress"):
        return {"x": rec.point[0], "y": rec.point[1]}
    if rec.kind == "swipe":
        args = {"x1": rec.point[0], "y1": rec.point[1], "x2": rec.point2[0], "y2": rec.point2[1]}
        d = _finger_direction(rec.point, rec.point2)
        if d: args["direction"] = d
        return args
    if rec.kind == "scroll":
        return {"direction": rec.value}          # scroll 的 value 就是手指方向
    if rec.kind in phone_ledger.INPUT_KINDS:
        return {"value": rec.value}
    return {}


def _settle(rec, **outcome):
    """动作结算落账。铁律: 只落已验证事实(verdict/diff_pct/exact_same/hit), 缺省字段的记录不计入判定。"""
    if rec is not None:
        rec.outcome = outcome
        _LEDGER.append(rec)
        result = {k: v for k, v in outcome.items() if k in ("diff_pct", "verdict", "fg", "hit")}
        if rec.kind in phone_ledger.INPUT_KINDS and rec.value:
            result["text"] = rec.value           # paste 的 expected 推导要原文, outcome 里没有
        _trace(rec.kind, args=_trace_args(rec), result=result)
    return rec

def _pre_dispatch(rec):
    """下发前守卫: 恢复级(系统改写动作)优先, 其次拒绝级; None=放行。只消费已结算记录, 不猜未落地结果。
    rec 是待发动作(无证据): 阶梯/拒绝把它算作第 N 次等价, 已结算部分仍需逐次一致的强证据。
    策略敏感前台(微信 visual-only/未解析 fail-closed)跳过恢复档: BACK/HOME/REFOCUS 是模型从未请求的
    自主导航/注入, 与该策略"少做+先问"的姿态相悖——只保留拒绝/ABORT(拒绝不注入任何事件)。"""
    records = _LEDGER.recent(16) + [rec]
    input_kind = rec.kind in phone_ledger.INPUT_KINDS
    if rec.kind in ("tap", "longpress"):
        recovery = phone_ledger.click_recovery(records, pending=rec, kind=rec.kind)
    elif input_kind:
        recovery = phone_ledger.type_recovery(records, pending=rec)
    else:
        recovery = None
    if recovery == "ABORT":
        return {"abort": True}    # 必须先于敏感前台判定: ABORT 的含义是"恢复手段已用尽",
                                  # 与注入无关。被 sensitive_fg 清掉后 reject_reason 又补不上
                                  # (强证据门槛不一致), 无效点击会继续打进敏感 App。
    if recovery and _sensitive_fg():
        recovery = None                   # 惰性判定: 只在恢复档真要吃触发时才付一次 ping
    if recovery:
        return {"recovery": recovery}
    if input_kind:
        return None                       # 输入类由专用阶梯全权接管(2 次即触发, 早于拒绝级的 5 次)
    reject = phone_ledger.reject_reason(records, pending=rec)
    return {"reject": reject} if reject else None

def _apply_guard(rec, guard, label):
    """守卫命中: 恢复=系统代为执行并如实结算(恢复后再截图算 diff——屏幕变了等价尾自断, 阶梯解除);
    拒绝=记 REJECTED 不下发; ABORT=恢复手段用尽, 记 aborted 不下发。全部有界, 无未知结果重试。"""
    if guard.get("abort"):
        _settle(rec, verdict="aborted", screenshot_exactly_same=True)
        return {"ok": 0, "aborted": True,
                "hint": "循环守卫: 同一动作连续无可观察变化且恢复手段已用尽, 本次未执行。请重新观察当前屏幕, 更换目标或策略, 或 ask_user 说明阻塞。"}
    if guard.get("recovery"):
        action = guard["recovery"]
        try:
            before = shot()
        except Exception:
            # 观察不可用: 既不执行恢复(不盲目注入 BACK/HOME), 也不假称已恢复;
            # 如实结算 uncertain, 让模型重新观察。
            _settle(rec, verdict="uncertain")
            return {"ok": 0, "uncertain": True,
                    "hint": "循环守卫: 无法取得当前截图, 本次动作与恢复均未执行。请重新观察当前屏幕再决定下一步。"}
        if action == "WAIT": time.sleep(1.0)
        elif action == "BACK": _act(op="back")
        elif action == "HOME": _act(op="home")
        time.sleep(0.3)
        try:
            pct = float(_img_diff_str(before, shot()).split("%", 1)[0].split()[-1])
        except Exception:
            pct = 100.0
        _settle(rec, verdict="recovered", recovery=action, diff_pct=pct, screenshot_exactly_same=_no_effect(pct))
        return {"ok": 1, "recovered": action, "diff": "%.3f%%" % pct,
                "hint": "循环守卫: 检测到连续等价的无效%s, 已代为执行 %s。请重新观察当前屏幕再决定下一步, 不要原样重发同一动作。" % (label, action)}
    _settle(rec, verdict="rejected", screenshot_exactly_same=True)
    return {"ok": 0, "rejected": guard["reject"],
            "hint": "循环守卫: 最近多步动作互为等价且前后截图逐次完全一致, 本次未下发。请比较前后截图, 更换目标或策略。"}


_LAST_TOUCH = {"x": None, "y": None, "ts": 0.0}
_PENDING_FRAME = {"img": None, "ts": 0.0, "pkg": ""}   # pkg=截这帧时的前台包名(跨 App 不许复用)

# Android 对同一窗口的 takeScreenshot 有最小间隔: 抢跑必回 code=3, shot() 只能 sleep(.35) 重截。
# 动作后取帧的最早时刻按这个常数排, 不靠猜。
_SHOT_MIN_GAP_S = 0.34


def _remember_touch(x, y):
    """记最近一次手势落点: 视觉型 App 的 GUI 粘贴要以输入框为锚点, 模型常常刚点过它。"""
    _LAST_TOUCH.update(x=int(x), y=int(y), ts=time.time())


def last_touch(max_age=120.0):
    """最近一次手势落点 (x, y); 过期或从没点过返回 None。"""
    if _LAST_TOUCH["x"] is None or time.time() - _LAST_TOUCH["ts"] > max_age:
        return None
    return (_LAST_TOUCH["x"], _LAST_TOUCH["y"])


def _stash_frame(img):
    """把动作后已经截好的帧交给 _compact_obs 复用: 一次动作只该截一次后验帧。"""
    _PENDING_FRAME.update(img=img, ts=time.time(), pkg=_fg())   # 打包时前台是谁, 这帧就是谁的画面


def take_pending_frame(max_age=2.0):
    """取走动作后暂存的帧(一次性)。过期返回 None —— 旧帧会喂给模型一份过期画面。"""
    img, ts = _PENDING_FRAME["img"], _PENDING_FRAME["ts"]
    pkg = _PENDING_FRAME.get("pkg") or ""
    _PENDING_FRAME["img"] = None
    if img is None or time.time() - ts > max_age:
        return None
    if pkg:                             # 只在有归属时才去问前台(省一次 ping)
        now = _fg()
        if now and now != pkg:          # 前台已经换了 App: 这帧不属于当前屏, 复用=错画面
            _track("droid_frame_cross_app", {"from": pkg[:40], "to": now[:40]})
            return None
    return img


def frame_jpeg_b64(img, max_side=1440, quality=70):
    """把帧压成"主模型看得动"的 JPEG base64: 长边 ≤ max_side, 质量默认 70。

    为每轮附图服务(见 agent_settings). 真机 1200x2670 原图 PNG ~160ms/几百 KB;
    缩到长边 1440 且 JPEG q70 后通常 ~50-80 KB, 模型侧约 1.4k image token。
    返回 (b64, (w, h)) —— 尺寸一并回传, 便于调用侧写进提示词(模型据此换算像素坐标)。"""
    import base64
    import cv2
    h, w = img.shape[:2]
    scale = min(1.0, float(max_side) / float(max(h, w) or 1))
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError('jpeg encode failed')
    return base64.b64encode(buf.tobytes()).decode('ascii'), (int(img.shape[1]), int(img.shape[0]))


def shot_frame_b64(max_side=1440, quality=70, reuse_pending=True):
    """取一帧给主模型: 优先复用动作后刚截的帧(2s 内), 否则现截一张。返回 (b64, (w, h))。"""
    img = take_pending_frame() if reuse_pending else None
    if img is None:
        img = shot()
    return frame_jpeg_b64(img, max_side=max_side, quality=quality)


def frame_digest(img=None, size=(36, 80)):
    """一帧画面的粗指纹(灰度缩略图)。用来判断"这一下真的换页面了吗"。

    为什么不能只看 diff: 2026-10-30 09:15 的三角洲会话里, 模型在"分享菜单打开/关闭"这两
    帧之间来回点, 每次 diff 都是同一个 85.850%(连 bbox 都一样) —— 从 diff 看每一步都"成功
    换了页面", 实际上一步都没往前走。指纹相同 = 真的还停在同一幅画上。
    img 缺省取 _PENDING_FRAME(动作后那一帧), 不额外截图、不消费它。"""
    import cv2, hashlib
    img = _PENDING_FRAME.get("img") if img is None else img
    if img is None:
        return ""
    try:
        t = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), size, interpolation=cv2.INTER_AREA)
        return hashlib.md5(t.tobytes()).hexdigest()[:10]
    except Exception:
        return ""

def _diff_pct(before, after):
    try:
        return float(_img_diff_str(before, after).split("%", 1)[0].split()[-1])
    except Exception:
        return 0.0


def _wait_change(before, max_s=1.0, poll=0.18, min_pct=0.5, sleep_first=True):
    """动作后等首帧变化(替代固定 sleep): 变了立即返回该帧, 没变才等满 max_s。

    为什么不是固定 sleep: 真机 75 次 gui_act 的 verify 段平均 3.5s, 其中固定 1s 是纯白等——
    动作 0.3s 就生效的页面也要陪跑到 1s。第一帧不早于 _SHOT_MIN_GAP_S, 否则必然撞 code=3。
    min_pct 取 0.5%: 光标闪烁/一次按压高亮只有零点几个百分点, 认成"变了"会让 diff 被低估成 miss;
    真正的换页/弹窗都在 1% 以上。
    sleep_first=False: 调用方已经等过 _SHOT_MIN_GAP_S(例如刚做过旋转检测), 直接取帧。
    返回 (img, pct); 截屏失败返回 (None, 0.0), 由调用方按 uncertain 处理。"""
    start = time.time()
    if sleep_first:
        time.sleep(max(0.0, min(_SHOT_MIN_GAP_S, float(max_s))))
    deadline = start + max(0.0, float(max_s))
    while True:
        try:
            cur = shot()
        except Exception:
            return None, 0.0
        pct = _diff_pct(before, cur)
        if pct >= min_pct or time.time() >= deadline:
            return cur, pct
        time.sleep(poll)


def tap(x, y, verify=True, wait=1.0, human=False, *, screen=None):
    """human=True only adds small motor-tolerance jitter; it is not an anti-abuse bypass.
    Sensitive apps must use state-driven waits and stop on security checks."""
    geometry = _gesture_screen(ping(), [(x, y)], screen)
    rec = _new_record("tap", point=(int(x), int(y)), screen=(geometry.get("w"), geometry.get("h")))
    guard = _pre_dispatch(rec)
    if guard is not None:
        return _apply_guard(rec, guard, "点击")
    before = shot() if verify else None
    ret = _act(op="tap", x=int(x), y=int(y), human=bool(human), expected_screen=geometry); ret.pop("ok", None)
    _remember_touch(x, y)
    if not verify: return ret
    time.sleep(min(_SHOT_MIN_GAP_S, float(wait)))   # 跨过截屏最小间隔, 顺便给旋转/动画留出时间
    post = _post_geom(geometry)
    if post and post['changed']:
        ret.update(verified=False, uncertain=True, orientation_changed=True, diff='n/a',
                   hint='屏幕方向/尺寸已变化 (%dx%d, rot=%d, %s)；这是小程序/游戏已启动的正常现象，动作已下发。'
                        '请用返回的 screen/rot 和新 obs 继续观察/操作，不要因坐标失效结束或 ask_user。'
                        % (post['screen'][0], post['screen'][1], post['rot'], post['orientation']),
                   fg=_fg(), screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    after, _ = _wait_change(before, max(0.0, float(wait) - _SHOT_MIN_GAP_S), sleep_first=False)
    diff = _img_diff_str(before, after); ret["diff"] = diff
    _stash_frame(after)          # 动作后帧留给 _compact_obs 复用, 不必再截一次(会撞 code=3 再等 .35s)
    if _shape_changed(before, after):
        post = _post_geom(geometry) or post      # 旋转可能发生在取帧之后: 补一次几何, 别把横屏说成竖屏
        ret.update(verified=False, uncertain=True, hint='屏幕尺寸变化；重新截图定位，不复用旧坐标。', fg=_fg())
        if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    try: pct = float(diff.split("%", 1)[0].split()[-1])
    except Exception: pct = 0.0
    if pct < 0.05:
        ret["hint"] = ("tap后屏幕变化很小；可能点到非热区，或前台有弹窗/浮层导致后层页面不响应。"
                   "先核对手上的坐标单位: point=像素(与 dump/look/obs 的 x/y 同单位), rel=0-1000"
                   "(与 obs/look 的 rx/ry 同单位)——两种只能给一种, 混用会偏出几百像素且不报错。"
                   "若目标是已聚焦的搜索框/输入框且输入法已弹出，diff 0 可能只是没有视觉变化："
                   "不要重复点框，直接输入/粘贴。"
                   "若目标是顶栏无文字图标（放大镜/+）：先 look(roi='title') 看有没有 type='icon' 的框"
                   "（x/y 是整屏像素，可直接当 point）；没有再 droid.ask_point(<目标描述>, roi='title') "
                   "拿 0-1000 数对原样传给 rel。不要猜 x/y。"
                   "请看截图/diff后再决定。")
        _track("droid_tap_miss", {"diff_pct": round(pct, 3)})   # 只在验证失败时上报(自限量): 手机操控版"中止率", 与 a11y_act_stats 的 tap 总数配对算命中率
    ret["fg"] = _fg()
    if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
    _settle(rec, verdict="settled", diff_pct=pct, screenshot_exactly_same=_no_effect(pct), fg=ret["fg"])
    return ret

def longpress(x, y, ms=800, verify=True, wait=1.0, *, screen=None):
    """长按: 唤出上下文菜单/消息多选/桌面图标编辑。同点 swipe(dur>=500) 即长按, 不新增总线 op。
    verify 与 tap 同款点空后验: 菜单没弹出=屏幕无变化=hint 要求重新观察, 不当成功。
    ms 夹在 [200,5000]: 过短退化成点击, 过长白等。"""
    ms = min(max(int(ms), 200), 5000)
    geometry = _gesture_screen(ping(), [(x, y)], screen)
    rec = _new_record("longpress", point=(int(x), int(y)), screen=(geometry.get("w"), geometry.get("h")))
    guard = _pre_dispatch(rec)
    if guard is not None:
        return _apply_guard(rec, guard, "长按")
    before = shot() if verify else None
    ret = _act(op="swipe", x1=int(x), y1=int(y), x2=int(x), y2=int(y), dur=ms, expected_screen=geometry); ret.pop("ok", None)
    _remember_touch(x, y)
    if not verify: return ret
    time.sleep(min(_SHOT_MIN_GAP_S, float(wait)))   # 跨过截屏最小间隔, 顺便给旋转/动画留出时间
    post = _post_geom(geometry)
    if post and post['changed']:
        ret.update(verified=False, uncertain=True, orientation_changed=True, diff='n/a',
                   hint='屏幕方向/尺寸已变化 (%dx%d, rot=%d, %s)；这是小程序/游戏已启动的正常现象，动作已下发。'
                        '请用返回的 screen/rot 和新 obs 继续观察/操作，不要因坐标失效结束或 ask_user。'
                        % (post['screen'][0], post['screen'][1], post['rot'], post['orientation']),
                   fg=_fg(), screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    after, _ = _wait_change(before, max(0.0, float(wait) - _SHOT_MIN_GAP_S), sleep_first=False)
    diff = _img_diff_str(before, after); ret["diff"] = diff
    _stash_frame(after)          # 动作后帧留给 _compact_obs 复用, 不必再截一次(会撞 code=3 再等 .35s)
    if _shape_changed(before, after):
        post = _post_geom(geometry) or post      # 旋转可能发生在取帧之后: 补一次几何, 别把横屏说成竖屏
        ret.update(verified=False, uncertain=True, hint='屏幕尺寸变化；重新截图定位，不复用旧坐标。', fg=_fg())
        if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    try: pct = float(diff.split("%", 1)[0].split()[-1])
    except Exception: pct = 0.0
    if pct < 0.05:
        ret["hint"] = "长按后屏幕变化很小；可能该元素没有长按菜单，或长按时长不足。请重新观察当前内容再决定下一步，勿原样重发。"
        _track("droid_longpress_miss", {"diff_pct": round(pct, 3)})   # 与 droid_tap_miss 同款自限量上报
    ret["fg"] = _fg()
    if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
    _settle(rec, verdict="settled", diff_pct=pct, screenshot_exactly_same=_no_effect(pct), fg=ret["fg"])
    return ret

def ui_snapshot(package):
    """单窗口的受保护快照；不支持此接口的旧 APK 必须回退，不能用 dump 冒充。"""
    if not package or package == _SELF_PKG or _fg() != package or package in SENSITIVE_APPS:
        raise RuntimeError("UI snapshot requires a known non-sensitive foreground package")
    snapshot = _get("/a11y/snapshot", pkg=package)
    if (not isinstance(snapshot, dict) or snapshot.get("pkg") != package or not snapshot.get("fingerprint")
            or snapshot.get("method") != "node_click" or snapshot.get("schema") != 1):
        raise RuntimeError("Guarded UI snapshot unavailable; update APK or use the planner")
    return snapshot


def _tap_observed(snapshot, index):
    if _fg() != snapshot["pkg"] or snapshot["pkg"] in SENSITIVE_APPS:
        return {"dispatched": False, "reason": "foreground_changed"}
    return _act(op="tap", expected_ui=snapshot["fingerprint"], expected_pkg=snapshot["pkg"],
                captured_ms=snapshot["captured_ms"], node_index=index)


def tap_target(target, *, package, timeout=8.0):
    """可选 Jev 单步导航定位。返回 fallback/uncertain/observed；完整规程见 memory/jev_phone_use.md。"""
    import jev_ui
    return jev_ui.tap_target(sys.modules[__name__], target, package, timeout)


def click_text(text, *, package, timeout=8.0):
    """精确文字唯一命中→同一受保护节点点击；无需 Jev 配置或联网。只用于导航。"""
    import jev_ui
    return jev_ui.tap_target(sys.modules[__name__], text, package, timeout, use_jev=False)


def swipe(x1, y1, x2, y2, dur=300, verify=True, wait=0.6, *, screen=None):
    """verify=True: 与 tap() 同款点空后验 —— 前后截图 diff, 滑动后屏幕几乎无变化≈没滚成/没拖动(或列表已在端点),
    返回 hint 要求重新观察而非原样重发; 屏幕形态变化(旋转/折叠)置 uncertain。长按(同点 dur>=800)同样受益: 菜单没弹出=无变化=hint。
    普通翻页滚动优先 scroll()(自带稳态证据+文本对比, 段内 swipe 已关此验证防重复截图); swipe 是按坐标精细滑/拖的底稿。"""
    geometry = _gesture_screen(ping(), [(x1, y1), (x2, y2)], screen)
    rec = _new_record("swipe", point=(int(x1), int(y1)), point2=(int(x2), int(y2)),
                      screen=(geometry.get("w"), geometry.get("h")))
    guard = _pre_dispatch(rec)
    if guard is not None:
        return _apply_guard(rec, guard, "滑动")
    before = shot() if verify else None
    ret = _act(op="swipe", x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2), dur=int(dur), expected_screen=geometry); ret.pop("ok", None)
    if not verify: return ret
    time.sleep(min(_SHOT_MIN_GAP_S, float(wait)))   # 跨过截屏最小间隔, 顺便给旋转/动画留出时间
    post = _post_geom(geometry)
    if post and post['changed']:
        ret.update(verified=False, uncertain=True, orientation_changed=True, diff='n/a',
                   hint='屏幕方向/尺寸已变化 (%dx%d, rot=%d, %s)；这是小程序/游戏已启动的正常现象，动作已下发。'
                        '请用返回的 screen/rot 和新 obs 继续观察/操作，不要因坐标失效结束或 ask_user。'
                        % (post['screen'][0], post['screen'][1], post['rot'], post['orientation']),
                   fg=_fg(), screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    after, _ = _wait_change(before, max(0.0, float(wait) - _SHOT_MIN_GAP_S), sleep_first=False)
    diff = _img_diff_str(before, after); ret["diff"] = diff
    _stash_frame(after)          # 动作后帧留给 _compact_obs 复用, 不必再截一次(会撞 code=3 再等 .35s)
    if _shape_changed(before, after):
        post = _post_geom(geometry) or post      # 旋转可能发生在取帧之后: 补一次几何, 别把横屏说成竖屏
        ret.update(verified=False, uncertain=True, hint='屏幕尺寸变化；重新截图定位，不复用旧坐标。', fg=_fg())
        if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
        _settle(rec, verdict="uncertain", diff_pct=100.0)
        return ret
    try: pct = float(diff.split("%", 1)[0].split()[-1])
    except Exception: pct = 0.0
    if pct < 0.05:
        ret["hint"] = "swipe后屏幕变化很小；可能没滚成/没拖动，或列表已在端点。请重新观察当前内容再决定下一步，勿原样重发同一手势。"
        _track("droid_swipe_miss", {"diff_pct": round(pct, 3)})   # 与 droid_tap_miss 同款自限量上报, 配对算手势命中率
    ret["fg"] = _fg()
    if post: ret.update(screen=post['screen'], rot=post['rot'], orientation=post['orientation'])
    _settle(rec, verdict="settled", diff_pct=pct, screenshot_exactly_same=_no_effect(pct), fg=ret["fg"])
    return ret


# ---------------- 定位便捷层(v2.33): 把 agent 每轮手写的「dump→列表推导→取中心」收成三个纯函数, 少写代码=少报错少浪费轮 ----------------
def find(text="", exact=False, clickable=None, edit=None, nodes=None):
    """按文本找节点: 在 dump()(或传入 nodes)里匹配 t(文本)/d(描述), 子串匹配, exact=True 全等; clickable/edit=True|False 过滤.
    返回节点列表, 每项含中心 x,y 可直接 tap. 敏感 App 前台 dump 为 [] → 返回 [](走 look())."""
    ns = dump() if nodes is None else nodes
    out = []
    for n in ns:
        t, d = n.get("t") or "", n.get("d") or ""
        if text and not ((text == t or text == d) if exact else (text in t or text in d)): continue
        if clickable is not None and bool(n.get("click")) != bool(clickable): continue
        if edit is not None and bool(n.get("edit")) != bool(edit): continue
        out.append(n)
    return out


def tap_text(text, exact=False, idx=None, clickable=None, **tap_kw):
    """find(text) → tap 命中节点中心. 唯一性断言(phone_use #9): 多个命中且未给 idx → 抛 ValueError 并列出候选, 绝不点"大概是它";
    0 命中 → 抛 LookupError(提示改 look() 视觉路径). 返回 tap() 的结果(含 diff/fg)."""
    hits = find(text, exact=exact, clickable=clickable)
    if not hits:
        raise LookupError(f"tap_text: 没有节点匹配 {text!r}; 先 print(droid.find(''))看全表, 或前台是自绘/敏感 App → droid.look()")
    if idx is None and len(hits) > 1:
        cands = "; ".join(f"[{i}] t={h.get('t')!r} d={h.get('d')!r} @({h.get('x')},{h.get('y')})" for i, h in enumerate(hits[:8]))
        raise ValueError(f"tap_text: {len(hits)} 个节点匹配 {text!r}: {cands} → 用 exact=True 或 idx=")
    h = hits[idx or 0]
    return tap(h["x"], h["y"], **tap_kw)


def tap_rel(rx, ry, **tap_kw):
    """0-1000 归一化坐标点击(左上原点, x 右 y 下, 各 0-1000): 按 ping 实测宽高换算成像素后走 tap()。
    定位阶梯最后一级 —— look() 无检测框、dump() 空壳(canvas 游戏/纯背景), 而目标**本身就是相对区域**
    (棋盘中心/屏幕四角/比例位)时用它表达位置; 它不是给识别不出的按钮猜坐标 —— 那种情况仍走 OCR 文字框 → ask_user(红线①)。
    换算只用当帧 screen() 不缓存旧尺寸; 越界仍在 tap 内过几何校验。例: 盘面中心 tap_rel(500, 500); 底栏最右 tap_rel(960, 970)。"""
    for name, v in (("rx", rx), ("ry", ry)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1000:
            raise ValueError("tap_rel(rx, ry): 两值各为 0-1000 的数(左上原点, x 右 y 下), %s=%r" % (name, v))
    w, h = screen()
    if w <= 0 or h <= 0:
        raise RuntimeError("tap_rel: 屏幕尺寸未知(ping w/h 非正); 先 ping() 确认总线与前台状态")
    # 换算走 geom(唯一权威): 与 gui_act 的 rel 字段同一条路径, 不再各写一份 round/夹取
    return tap(*geom.to_px(rx, ry, w, h), **tap_kw)


_ROI_NAMES = {"top": (0, 0, 1, 0.34), "upper": (0, 0, 1, 0.5), "middle": (0, 0.25, 1, 0.75),
              "lower": (0, 0.5, 1, 1), "bottom": (0, 0.66, 1, 1)}
# 通用比例带 + geom 实测的系统 UI 锚带(status/title/navbar)共用一份 0-1000 契约:
# look(roi='title') 与 ask_vision(..., roi='title') 裁的是同一块区域, 于是
# "OCR 在标题行没找到无文字图标 → 用 ask_vision 看同一块"能在同一区域上对照。
_ROI_NAMES.update({name: tuple(v / geom.NORM for v in geom.band_norm(name)) for name in geom.BANDS})


def _matching_labels(detections, label):
    return detections if not label else [d for d in detections if label in d["label"]]


def _clickable_count(nodes):
    """可点节点数。有可点目标就说明树是可用的。"""
    n = 0
    for x in nodes or []:
        try:
            if x.get('click'):
                n += 1
        except AttributeError:
            continue
    return n


def _text_count(nodes):
    """带文字(文本或 contentDescription)的节点数。有字就说明树至少可读。"""
    n = 0
    for x in nodes or []:
        try:
            if str(x.get('t') or '').strip() or str(x.get('d') or '').strip():
                n += 1
        except AttributeError:
            continue
    return n


def _classify(st):
    """dump_state() 的产物 → 'tree'|'blanked'|'canvas'|'unknown'。纯函数, 无设备依赖。

    为什么要它: YOLO 与 vision 的分流判据。有可用控件树时 YOLO+OCR 又快又准(31ms);
    没有时(游戏/SurfaceView/自绘/混淆) YOLO 的 21 个通用 Android 类既认不出语义, 框还会
    把模型带偏——那种画面定位只能问 VLM。判据不额外花钱: 就是一次 dump_state() 的产物。

    旧判据只认 degraded.reason=='tree_empty', 两个方向都错(真机实证):
    - 漏: 王者荣耀是 1 个不可点节点("Game view"), 不是 tree_empty → 判成 ui, YOLO 在游戏上跑;
    - 误: 海报页/骨架屏/WebView 首帧 → tree_empty → 判成 canvas, 该拿图标框的普通页被跳过 YOLO。
    共同根因: 判的是"树空不空", 而该判的是"有没有可用控件树"。

    低信息树 = 没有可点节点, 且(只有<=1 个节点 或 没有任何带字节点):
    - <=1 个不可点节点   → 王者荣耀/SurfaceView 的"Game view"形态
    - 多节点但全不带字   → 海报页/图片页: 点不了也读不了, 只能问 VLM
    反过来这两种都**不**算 canvas: 有可点节点(能操作), 或多个带字节点(能读)。"""
    if not st:
        return 'unknown'
    reason = (st.get('degraded') or {}).get('reason')
    if reason in ('sensitive_blank', 'unresolved_fg'):
        return 'blanked'
    if reason == 'tree_empty':
        return 'canvas'
    nodes = st.get('nodes') or []
    if _clickable_count(nodes) == 0 and (len(nodes) <= 1 or _text_count(nodes) == 0):
        return 'canvas'
    return 'tree'


def screen_kind():
    """当前画面类型: 'canvas'(自绘/游戏/SurfaceView) | 'blanked'(敏感 App 树被置空) | 'ui'(普通控件树)。

    _classify 的公开薄封装; 'unknown'(dump_state 抛异常) 归一成 'ui' 保持历史契约。
    新代码请直接用 _classify —— 'unknown' 与 'ui' 的通道选择不同(见 observe)。"""
    try:
        st = dump_state()
    except Exception:
        return 'ui'
    k = _classify(st)
    return 'ui' if k == 'unknown' else k


_OBS_CACHE = {"thumb": None, "roi": None, "pkg": None, "rot": None, "res": None}


def _detect_note():
    """最近一次 ui_detect 的降级/跳过原因; 正常时(或检测器不可 import 的 PC 侧)返回 None。

    两种原因归一成一个入口, 因为对 observe() 而言后果相同: yolo 通道没产出可用框。
    - LAST_YOLO_ERROR   检测器缺失/损坏 → 降级到其余通道
    - LAST_SKIP_REASON  框太密, 不是控件页 → 同样不把框喂给模型, 让它去问 see()"""
    try:
        from models.ui_detect_v1 import ui_detect_lite
        return (getattr(ui_detect_lite, 'LAST_YOLO_ERROR', None)
                or getattr(ui_detect_lite, 'LAST_SKIP_REASON', None))
    except Exception:
        return None


def _obs_item_from_node(n, x1, y1, W, H):
    """dump 节点 → 观测项。树给的是可点性/编辑态/精确边界, 这是 YOLO 给不了的。

    契约: t=显示文本(节点的 text), desc=contentDescription。两者都没有就都为空,
    由 _compact_obs 退到 cls。"""
    bx = n.get('b') or n.get('bbox')
    cx, cy = n.get('x'), n.get('y')
    if cx is None or cy is None:
        if not (isinstance(bx, (list, tuple)) and len(bx) >= 4):
            return None
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    cx, cy = int(cx) + x1, int(cy) + y1
    rx, ry = geom.to_norm(cx, cy, W, H)
    if isinstance(bx, (list, tuple)) and len(bx) >= 4:
        bbox = [int(bx[0]) + x1, int(bx[1]) + y1, int(bx[2]) + x1, int(bx[3]) + y1]
    else:
        bbox = [cx, cy, cx, cy]
    return {'src': 'tree', 't': str(n.get('t') or ''), 'desc': str(n.get('d') or ''),
            'cls': str(n.get('cls') or ''), 'x': cx, 'y': cy, 'rx': rx, 'ry': ry,
            'bbox': bbox, 'click': bool(n.get('click')), 'conf': None, 'type': ''}


def _obs_item_from_det(d, x1, y1, W, H):
    """YOLO/OCR 检测框 → 观测项。YOLO 给的是无文字图标的控件语义(21 类)。

    契约与树项一致: t=OCR 文字(无文字图标则为空), type='icon'|'text' 是控件形态。"""
    bx1, by1, bx2, by2 = d['bbox']
    cx, cy = int((bx1 + bx2) / 2) + x1, int((by1 + by2) / 2) + y1
    rx, ry = geom.to_norm(cx, cy, W, H)
    return {'src': 'yolo', 't': str(d.get('label') or ''), 'desc': '',
            'cls': str(d.get('cls') or ''), 'x': cx, 'y': cy, 'rx': rx, 'ry': ry,
            'bbox': [bx1 + x1, by1 + y1, bx2 + x1, by2 + y1], 'click': None,
            'conf': d.get('confidence'), 'type': str(d.get('type') or '')}


def observe(roi=None, conf=0.25, cache=True, img=None):
    """本地定位通道一步到位: 一次截图 + 一次分类 + 按类选通道。

    img 给出则不再截图(动作已经截过后验帧, 再截一次只会撞截屏最小间隔再多等 0.35s)。

    返回 {'kind', 'items', 'channels', 'notes', 'needs_vision', 'ms', 'cached'?}:
    - kind: _classify 的产物('tree'|'blanked'|'canvas'|'unknown')
    - items: [{src:'tree'|'yolo', t,desc,cls,type,x,y,rx,ry,bbox,click,conf}] —— t 是显示文本,
      x/y 像素可直接当 gui_act 的 point, rx/ry 是 0-1000 可直接当 rel
    - channels: 实际跑了哪些通道
    - notes: 降级/跳过原因(如 local_boxes_unavailable); 空列表=没降级
    - needs_vision: True = 本地定位通道为空, 要定位得问 see()

    通道选择(判据在 _classify, 不靠模型现推):
    - tree    : 控件树 + YOLO(YOLO 的 label 由 OCR 贴)
    - blanked : YOLO(树被策略置空但屏幕有字, 微信)
    - canvas  : 都不跑 —— 定位问 see(); 要"读画面"由调用方显式 droid.ocr()
    - unknown : 按 tree(YOLO 失败会降级, 没有风险)

    降级铁律: YOLO 侧任何失败只记 note, 绝不外抛。真机 2026-10-28 10:22 那次 22 分钟的
    任务就是败在"模型缺失 → look() 抛异常 → 整轮作废"上。"""
    t0 = time.time()
    import cv2
    img = shot() if img is None else img     # img 由调用方给: 动作后帧直接复用, 不重复截图(截屏有最小间隔)
    H, W = img.shape[:2]
    box = _roi_box(roi)
    if box is not None:
        roi = tuple(v / 1000.0 for v in box)     # 0-1000 契约 -> 比例, 下面的比例分支换算成像素
    elif isinstance(roi, str):
        if roi not in _ROI_NAMES:
            raise ValueError('observe: unknown roi %r, choose from: %s' % (roi, '/'.join(sorted(_ROI_NAMES))))
        roi = _ROI_NAMES[roi]
    if roi:
        x1, y1, x2, y2 = roi
        if max(x1, y1, x2, y2) <= 1.0:           # 比例 → 像素
            x1, y1, x2, y2 = x1 * W, y1 * H, x2 * W, y2 * H
        x1, y1, x2, y2 = int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2))
    else:
        x1, y1, x2, y2 = 0, 0, W, H
    crop = img[y1:y2, x1:x2]

    thumb = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (36, 80), interpolation=cv2.INTER_AREA)
    try:
        st = dump_state() or {}
        pkg = str(st.get('pkg') or '')
    except Exception:
        st, pkg = {}, ''
    try:
        p = ping(); rot = int(p.get('rot') or 0)
    except Exception:
        rot = 0
    c = _OBS_CACHE
    # 缓存键含 pkg 与 rot: 旧版只认缩略图+roi, 于是切个 App 或转个屏都可能命中上一帧的
    # 结果(SPEC §2.3 记着的缺陷), 而快路径恰恰要靠这个缓存。
    if cache and c["res"] is not None and c["roi"] == (x1, y1, x2, y2) \
            and c["pkg"] == pkg and c["rot"] == rot and c["thumb"] is not None:
        if float((cv2.absdiff(thumb, c["thumb"]) > 16).mean()) < 0.003:
            res = dict(c["res"]); res["cached"] = True
            return res

    kind = _classify(st)
    items, channels, notes = [], [], []
    if kind in ('tree', 'unknown'):
        channels.append('tree')
        for n in (st.get('nodes') or []):
            if isinstance(n, dict):
                it = _obs_item_from_node(n, x1, y1, W, H)
                if it is not None:
                    items.append(it)
    if kind in ('tree', 'blanked', 'unknown'):
        channels.append('yolo')
        dets = ui_detect(crop, conf=conf)
        for d in dets:
            items.append(_obs_item_from_det(d, x1, y1, W, H))
        note = _detect_note()
        if note:
            # 检测器挂了, 或框太密说明这不是控件页 —— 两种都不把框留给模型:
            # 前者它读了会白费, 后者它读了会去点游戏美术资源(真机 3 次 tap 摸索的来由)。
            notes.append('local_boxes_unusable: %s' % note)
            channels = [x for x in channels if x != 'yolo']
            items = [x for x in items if x['src'] != 'yolo']
    if kind == 'canvas' or not items:
        needs_vision = True
    else:
        needs_vision = False
    res = {'kind': kind, 'items': items, 'channels': channels, 'notes': notes,
           'needs_vision': needs_vision, 'ms': round((time.time() - t0) * 1000, 1)}
    c.update(thumb=thumb, roi=(x1, y1, x2, y2), pkg=pkg, rot=rot, res=res)
    global _LAST_OBS, _OBS_STALE
    _LAST_OBS = {"nodes": [], "detections": [i for i in items if i['src'] == 'yolo'],
                 "screen": (W, H), "pkg": pkg}
    _OBS_STALE = False
    _trace("observe", result={"kind": kind, "count": len(items)})
    return res


def look(conf=0.25, path=None, roi=None, cache=True, *, label=None):
    """视觉路径一步到位: observe() 后取 YOLO 项, 返回形状与历史一致。

    label: 可选 OCR 文字子串筛选，返回全部匹配项；多命中仍需消歧，不自动选择或点击。
    roi: 'top'|'upper'|'middle'|'lower'|'bottom' 或 (x1,y1,x2,y2)(像素, 或 0~1 的比例).
    cache: 屏幕与上一次 observe 几乎没变(缩略图差异 <0.3%) 且 roi/pkg/rot 相同 → 附 'cached': True.
    path 给出则同时把截图存文件(给用户看/复核).

    通道选择在 observe 的 _classify 里, 这里不再收 yolo 形参(留着一个不生效的开关比没有更糟)。
    新代码请用 observe(): 它额外带回控件树项、kind 与降级原因。"""
    if label is not None and not isinstance(label, str):
        raise TypeError('look label must be a string or None')
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        raise ValueError('look(conf=0.25, ...) 返回检测框，不接受问题；看图问答请用 see()') from None
    if not 0 <= conf <= 1:
        raise ValueError('look conf must be between 0 and 1')
    res = observe(roi=roi, conf=conf, cache=cache)
    out = []
    for i in res['items']:
        if i['src'] != 'yolo':
            continue
        out.append({'bbox': list(i['bbox']), 'type': i['type'], 'label': i['t'],
                    'cls': i['cls'], 'confidence': i['conf'], 'x': i['x'], 'y': i['y'],
                    'rx': i['rx'], 'ry': i['ry'], 'cached': res.get('cached', False)})
    if label:
        out = [d for d in out if label in (d.get('label') or '')]
    if path:
        import cv2
        cv2.imwrite(path, shot())
    return out


# ---- 视觉通道生命周期 ----
# 三件事各自独立, 曾互相打架(真机 2026-10-28: 选个不支持图片的模型 = 2 次 2.4s 快速失败
# = 120s 全瞎, 而熔断只在任务开始清零, 新任务替上个任务的模型选择受罚):
#   ① backend 从哪来  ② 这个模型能不能看图  ③ 传输失败几次算熔断
# ① 任务开始由 ga_android 登记到模块级 _ACTIVE_BACKEND。**不是 threading.local** ——
#    后者不跨线程继承, 用户代码自起子线程调 ask_vision 会莫名拿不到后端。
# ② 首次真实调用失败时按错误形态分类并缓存, 不预探(预探让每个新模型都多付一次往返)。
# ③ 熔断按 backend 身份, 切模型即重置。
_ACTIVE_BACKEND = None
_FUSE = {}                 # backend_id -> {'n': int, 'until': float}
_CAP = {}                  # backend_id -> 'ok'|'no_vision'
_VISION_FAIL_LIMIT = 2     # 连续传输失败此次数后熔断
_VISION_COOLDOWN_S = 120   # 熔断静默期: 期间直接拒, 不再反复烧超时
_VISION_TIMEOUT_S = 30     # 单次**读**超时(流式下=两个 chunk 之间最多静默多久): 抓"真挂住"
_NO_VISION_MARKS = ('image', 'vision', 'multimodal', 'multi-modal', '不支持图片',
                    '无法处理图片', 'image_url', 'base64')


def set_active_backend(backend):
    """ga_android 在任务开始/模型切换时登记当前任务的模型后端; None=清除。"""
    global _ACTIVE_BACKEND
    _ACTIVE_BACKEND = backend


def active_backend():
    return _ACTIVE_BACKEND


def _backend_id(backend):
    """backend 的稳定身份: provider/model/base 的拼接。切模型即变, 熔断与能力缓存随之失效。"""
    if backend is None:
        return None
    parts = []
    for name in ('model', 'name', 'api_base', 'base_url', 'provider'):
        try:
            v = getattr(backend, name, None)
            if isinstance(v, str) and v:
                parts.append(v)
        except Exception:
            pass
    if not parts:
        parts.append(type(backend).__name__)
    return '|'.join(parts)


def _fuse_state(backend):
    return _FUSE.setdefault(_backend_id(backend), {'n': 0, 'until': 0.0})


def reset_vision_fuse(backend=None):
    """清零视觉熔断。backend=None 全清(任务边界, 兼容旧调用); 给了只清那一个(切模型时)。"""
    if backend is None:
        _FUSE.clear(); _CAP.clear()
    else:
        _FUSE.pop(_backend_id(backend), None)
        _CAP.pop(_backend_id(backend), None)


def _looks_like_no_vision(msg):
    low = str(msg).lower()
    return any(m in low for m in _NO_VISION_MARKS)


def _vision_cap(backend):
    """该模型能不能看图: 'ok' | 'no_vision' | None(还没试过)。"""
    return _CAP.get(_backend_id(backend))


def _mark_cap(backend, value):
    _CAP[_backend_id(backend)] = value


def _roi_box(roi):
    """字符串形式的 4 元组 -> (x1, y1, x2, y2)(0-1000 归一化); 不是数字框就返回 None。

    真机 2026-10-30 15:41 实证: 模型按记忆里的 0-1000 契约把 roi 写成 "[800, 150, 950, 250]",
    而 observe()/_resolve_roi() 的名字校验只认 'title'/'top' 这类名字, 于是整轮观测作废:
    {"ok":false,"reason":"ocr_failed","error":"ValueError: unknown roi '[800, 150, 950, 250]'"}。
    模型这样传是对的, 该吃下; 这里不写正则(ops 环境会吃反斜杠), 只按括号/逗号切。"""
    if not isinstance(roi, str):
        return None
    s = roi.strip()
    if not s:
        return None
    body = s.strip('[]() ')
    if s[0] not in '[(' and body.count(',') != 3:
        return None
    parts = [p.strip() for p in body.split(',')]
    if len(parts) != 4:
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    x1, y1, x2, y2 = (max(0.0, min(1000.0, v)) for v in vals)
    if abs(x2 - x1) < 1 or abs(y2 - y1) < 1:
        # 夹完只剩零宽/零高(如 [2000,0,3000,500] 全在屏外): 当非法, 让调用方回退全屏,
        # 而不是静默裁一个空条去 OCR(会稳定返回 0 条, 看起来像"页面上什么都没有")。
        return None
    return (x1, y1, x2, y2)


def _resolve_roi(roi):
    """ROI 名 → 0-1000 矩形。'title'/'status'/'navbar' 走 geom 实测锚带(与 look() 同一份),
    'top'/'upper'/... 走通用比例带; 已是 4 元组就原样返回。"""
    box = _roi_box(roi)
    if box is not None:
        return tuple(int(round(v)) for v in box)      # 已经是 0-1000, 不用再换算
    if isinstance(roi, str):
        if roi not in _ROI_NAMES:
            raise ValueError('unknown roi %r, choose from: %s' % (roi, '/'.join(sorted(_ROI_NAMES))))
        return tuple(int(round(v * geom.NORM)) for v in _ROI_NAMES[roi])
    return roi


def _crop_roi(img, roi):
    """按 0-1000 归一化 ROI 裁剪 ndarray(与全系统坐标契约一致); 非 ndarray(路径)原样返回。
    roi 也接受锚带名('title' 等): 顶栏无文字图标是 ask_vision 的主要用途, 裁掉状态栏
    后 VLM 不可能把时间/电池算进来(提速只是顺带, 真正的大头是模型生成)。"""
    import numpy as np
    if not isinstance(img, np.ndarray) or not roi or len(roi) != 4:
        return img
    h, w = img.shape[:2]
    x1, x2 = sorted((max(0, min(1000, roi[0])), max(0, min(1000, roi[2]))))
    y1, y2 = sorted((max(0, min(1000, roi[1])), max(0, min(1000, roi[3]))))
    return img[int(y1 / 1000.0 * h):int(y2 / 1000.0 * h), int(x1 / 1000.0 * w):int(x2 / 1000.0 * w)]


def reset_vision_fuse(backend=None):
    """清零视觉熔断与能力缓存。backend=None 全清(任务边界调用, 兼容旧无参调用);
    给了只清那一个(模型切换时调用)。

    为什么任务边界要全清: 熔断曾只在此处复位, 而上个任务早期连撞两次失败(最常见成因:
    选中的模型根本不支持图片, 2.4s 就连错两次)会让新任务在整个游戏阶段——也就是唯一
    需要视觉 grounding 的阶段——连续 120s 拿不到任何观察。现在熔断按模型身份走,
    切模型自动失效, 这道全清只是兜底。"""
    if backend is None:
        _FUSE.clear(); _CAP.clear()
    else:
        _FUSE.pop(_backend_id(backend), None)
        _CAP.pop(_backend_id(backend), None)


def _vision_failed(backend):
    """传输类失败计数; 连败到上限即熔断。**能力类失败不走这里**(见 ask_vision)。"""
    st = _fuse_state(backend)
    st['n'] += 1
    if st['n'] >= _VISION_FAIL_LIMIT:
        st['until'] = time.time() + _VISION_COOLDOWN_S


def ask_vision(image_input, prompt="描述当前界面", roi=None, max_pixels=None, timeout=None, **options):
    """看图问答。ROI(0-1000)裁剪后只送局部——全屏 320 万像素 vs 局部 ~50 万, 单次调用
    耗时差 3-6 倍(真机实证 25-50s → 8-15s)。超时上限 + 连续失败熔断, 不再让 vision
    超时拖垮 a11y。

    roi 也接受锚带名: 'status'/'title'/'navbar'(geom 实测的系统 UI 带)与
    'top'/'upper'/'middle'/'lower'/'bottom'。顶栏无文字图标(放大镜/+)问位置时传
    roi='title': 主要收益是**把状态栏裁掉**(VLM 就不会把时间/电池算进去), 顺带图传变小。
    ⚠️ 别把它当加速手段——实测单次视觉调用 15-46s, 大头是模型生成不是图传。

    第一级工具是 see(); 本函数是它在 code_run 内的薄封装, SOP 只教 see()。"""
    roi = _resolve_roi(roi)
    run_guard.check()        # 僵尸线程检查点: code_run 超时/被停后, 视觉调用是最容易长时间挂住的
                             # 副作用(一次 15-46s), 不设卡则僵尸会继续拿旧后端打网络, 反复烧预算
    backend = active_backend()
    if backend is None:
        raise RuntimeError('当前任务没有可用模型后端, 视觉不可用: 不要重试 ask_vision/see —— '
                           '立即改用 droid.observe() 拿本地图标框、droid.ocr() 读屏, 或 ask_user。')
    if _vision_cap(backend) == 'no_vision':
        # 明确拒绝, 不计熔断不重试: 这是配置问题, 不是网络问题。用户切到纯文本模型时
        # 旧实现会让它 2.4s 连错两次 → 熔断 120s → 整个游戏阶段瞎掉。
        raise RuntimeError('当前任务选择的模型不支持图片(%s), 视觉通道已停用: 不要重试 '
                           'ask_vision/see —— 立即改用 droid.observe() 拿本地图标框、'
                           'droid.ocr() 读画面文字, 或 ask_user 请用户换个支持图片的模型。'
                           % (_backend_id(backend)[:80],))
    st = _fuse_state(backend)
    if st['n'] >= _VISION_FAIL_LIMIT and time.time() < st['until']:
        raise RuntimeError('该模型视觉连续失败已熔断 %ds: 不要重试 ask_vision/see —— 立即改用 '
                           'droid.observe()/droid.ocr() 读屏, 或 ask_user。换个模型会自动解除。'
                           % _VISION_COOLDOWN_S)
    try:
        from vision_llm import ask_with_backend
        kw = {"timeout": timeout or _VISION_TIMEOUT_S}
        if max_pixels:
            kw["max_pixels"] = max_pixels
        result = ask_with_backend(backend, _crop_roi(image_input, roi), prompt, **kw)
    except Exception as exc:
        if _looks_like_no_vision(exc):
            _mark_cap(backend, 'no_vision')
            raise RuntimeError('当前任务选择的模型不支持图片(%s): %s。不要重试 ask_vision/see '
                               '—— 立即改用 droid.observe()/droid.ocr() 读屏, 或 ask_user。'
                               % (_backend_id(backend)[:80], str(exc)[:120])) from None
        _vision_failed(backend)
        raise RuntimeError('视觉请求失败(%s): 不要重试 ask_vision/see —— 立即改用 droid.observe()/'
                           'droid.ocr() 读屏; 确需看图请在任务页选择支持图片的模型。'
                           % (str(exc)[:160],)) from None
    # 空响应 = 静默失败(真机实证): 某轮 ask_vision 返回空串, stdout 只剩 _prepare_image 的
    # 「缩放/Base64」两行 print, agent 把"没有回答"当成功, 又整轮重问同一问题(白付一轮模型 + ~17s)。
    # vision_llm.ask_with_backend 的契约是「空文本 raise」, 这里再兜一层: 空/纯空白一律抛错,
    # 不让无信号结果流过; 已以 "Error:" 开头的字符串保持原样回传(那是可见的失败)。
    if result is None or not str(result).strip():
        _vision_failed(backend)
        raise RuntimeError('视觉模型未返回回答内容(空响应): 不要重试 ask_vision/see —— 立即改用 '
                           'droid.observe()/droid.ocr() 读屏; 若确需看图, 检查当前任务选择的模型是否支持图片输入')
    if str(result).startswith("Error:"):
        _vision_failed(backend)              # 可见失败也计入熔断(原样回传, 由调用方按错处理)
    else:
        _mark_cap(backend, 'ok')
        _fuse_state(backend)['n'] = 0        # 成功即重置
    return result


# ask_point 的固定提问: 短、只问一件事、只许一种单位。让提问词不随任务漂移——
# 真机 17:48 那次模型自己写的问句是"…占屏幕宽和高的**百分比**，0-1000归一化坐标"，
# 百分数和千分比混在一句话里, VLM 回了一段自相矛盾的散文("靠右边距15%即85%位置",
# "左边缘约10%约90%位置"), 模型再自己乘 10 又猜了 y, 点到状态栏, 搜索页从未打开。
_ASK_POINT_PROMPT = (
    "Answer with ONLY two integers: x,y where the center of the target is, on a 0-1000 "
    "scale (0,0 = top-left of the image; 1000,1000 = bottom-right). "
    "Do not use percent, do not use pixels, do not explain. "
    "If the target is not visible, answer: none. Target: %s")


def _parse_point(text):
    """从视觉回答里取前两个整数当 0-1000 坐标; 带 %/percent 的回答一律拒(那是单位陷阱, 不是坐标)。

    取"前两个整数"而不是"第一个 x,y 模式": 模型的问句是固定的, 但 VLM 的回答格式不可控,
    "x=831, y=81" / "约 (831, 81)" / "831 和 81" 都要吃得下。范围校验兜住"把屏幕尺寸
    当时标回了"这类回答(1200x2670 → 越界 → 拒), 不猜。"""
    import re
    s = str(text)
    if '%' in s or 'percent' in s.lower():
        raise ValueError('视觉回答带了百分号(%s), 不是 0-1000 坐标; 请重问并明确"只回复两个整数 x,y, '
                         '0-1000"。原回答: %s' % ('%', s[:120]))
    nums = re.findall(r'-?\d+', s)
    if len(nums) < 2:
        raise ValueError('视觉回答里找不到两个整数坐标(%s); 请重问或改用 look()/ask_user' % s[:120])
    a, b = int(nums[0]), int(nums[1])
    if not (0 <= a <= geom.NORM and 0 <= b <= geom.NORM):
        raise ValueError('视觉回答的坐标 %r 不在 0-1000 内(可能回的是屏幕尺寸); 请重问' % ((a, b),))
    return a, b


def ask_point(question, roi=None, timeout=None):
    """问"屏幕上某个东西在哪", 拿回 **整屏 0-1000** 坐标对(可直接传给 gui_act 的 `rel`)。

    为什么要有这层: `look()` 的 OCR 看不到无文字图标(放大镜/+ /返回/菜单), canvas 页
    连文字都没有, 这两类目标的唯一定位通道就是看图问答。而裸 `ask_vision` 的答案是自由
    文本, 单位随口来——真机 17:48 因此点了状态栏、17:57 又整轮超时。这里把提问词、单位、
    解析一次定死: 固定问句 + 只认 0-1000 + 拒百分号, 失败就抛错让上层照 SOP 停手。

    roi 传 'title'/'status'/'navbar' 或 'top'/'upper'/...: 问顶栏图标位置时传 'title',
    裁到标题行比送整屏快数倍, VLM 也不会把状态栏算进来。

    ⚠️ 返回的是**整屏**坐标, 不是裁剪框坐标: ask_vision 在送图前就裁好了, VLM 只看到裁剪
    后的图, 它的 0-1000 必然是**裁剪框**的。这里必须把它映射回整屏, 否则整体偏移——
    实测 roi='title' 时放大镜会从 (996,215) 偏到 (995,1068), 点进聊天列表, 而 tap 的 diff
    很大、前台也没变, 模型会以为搜索页已经打开。"""
    box = _resolve_roi(roi) if roi else (0, 0, geom.NORM, geom.NORM)
    text = ask_vision(shot(), _ASK_POINT_PROMPT % question, roi=box, timeout=timeout)
    cx, cy = _parse_point(text)
    rx1, ry1, rx2, ry2 = box
    return (int(round(rx1 + cx / float(geom.NORM) * (rx2 - rx1))),
            int(round(ry1 + cy / float(geom.NORM) * (ry2 - ry1))))


def wait_stable(max_wait=3.0, poll=0.25, diff_pct=1.5):
    """动作后等页面稳定再进下一轮决策(替代固定 sleep)。

    真机实证: 固定 action_sleep=5 让 30 步白睡 150s; 而"立刻决策"在加载页上
    会点到未完成的界面。本方案: 相邻两帧 diff 持续 >diff_pct = 页面还在动,
    轮询到稳定或超时。静态页两次截图即返回(~0.3s), 加载页最多等 max_wait。
    返回 {stable, waited_s, uncertain}: 截图失败不阻塞, 记 uncertain 交上层判。
    """
    t0 = time.time()
    try:
        prev = shot()
    except Exception:
        return {'stable': True, 'waited_s': 0.0, 'uncertain': True}
    waited = 0.0
    while waited < max_wait:
        time.sleep(poll)
        waited = time.time() - t0
        try:
            cur = shot()
        except Exception:
            return {'stable': True, 'waited_s': waited, 'uncertain': True}
        try:
            pct = float(_img_diff_str(prev, cur).split('%', 1)[0].split()[-1])
        except Exception:
            return {'stable': True, 'waited_s': waited, 'uncertain': True}
        if pct <= diff_pct:
            return {'stable': True, 'waited_s': waited, 'uncertain': False}
        prev = cur
    return {'stable': False, 'waited_s': waited, 'uncertain': False}


def screen():
    """(w, h): 当前朝向的屏幕像素尺寸(来自 ping). 相对布局判断用: y < 0.12h 顶栏区, y > 0.9h 底栏区; 禁止把任何绝对坐标写进记忆.
    GA 自己的悬浮胶囊/回答面板在 shot() 里已按邻近像素抹平, 不会出现在 OCR/检测结果中; 点击该区域会穿透到下方 App."""
    p = ping()
    return int(p.get("w") or 0), int(p.get("h") or 0)
def _text_change_ratio(before, after):
    before = [x for x in (before or []) if x]
    after = [x for x in (after or []) if x]
    if len(before) < 4 or len(after) < 4:
        return None
    visible = set(after)
    return sum(1 for x in before if x not in visible) / float(len(before))
def _pixel_change_pct(before, after, roi):
    import cv2
    if before is None or after is None or before.shape != after.shape:
        return None
    x1, y1, x2, y2 = roi
    a, b = before[y1:y2, x1:x2], after[y1:y2, x1:x2]
    if not a.size or not b.size:
        return None
    diff = cv2.absdiff(
        cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(b, cv2.COLOR_BGR2GRAY),
    )
    return float((diff > 12).mean()) * 100.0
def _shape_changed(base, *others):
    """证据窗内截图宽高形态是否变化(旋转/折叠会改 shape); 缺帧(None)不参与判定。"""
    return base is not None and any(
        o is not None and o.shape != base.shape for o in others
    )
def _orientation(w, h):
    try: w, h = int(w), int(h)
    except (TypeError, ValueError): return ''
    return 'landscape' if w > h else ('portrait' if h > w else 'square')
def _post_geom(geometry):
    """动作后一次 ping 的几何快照: 打开游戏/小程序常竖→横, 先花一次 ping 检测,
    命中就不再做 after 截图/diff(那是旋转时最贵的一段), 直接把 screen/rot 交给模型。"""
    try:
        p = ping()
        w, h, rot = int(p.get('w') or 0), int(p.get('h') or 0), int(p.get('rot') or 0)
    except Exception:
        return None
    if not w or not h:
        return None
    base = (int(geometry.get('w') or 0), int(geometry.get('h') or 0), int(geometry.get('rot') or 0))
    return {'screen': (w, h), 'rot': rot, 'orientation': _orientation(w, h),
            'changed': (w, h, rot) != base}
def _scroll_verdict(text_ratio, first_pixel_pct, stable_pixel_pct):
    if text_ratio is not None and text_ratio > .30:
        return "text"
    if first_pixel_pct is not None and first_pixel_pct > 1.5:
        if stable_pixel_pct is not None and stable_pixel_pct > 1.5:
            return "pixel"
    return "none"
def _scroll_error(stage, exc):
    kind = "".join(
        ch for ch in type(exc).__name__ if ch.isalnum() or ch in "_-"
    )[:48] or "Exception"
    return ("%s:%s" % (stage, kind))[:80]
def _scroll_shot():
    """Optional JPEG evidence; shot() owns capture throttling for every caller."""
    try:
        return shot(q=45)
    except Exception:
        return None


_OPPOSITE_DIRECTIONS = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _scroll_feedback(direction, result):
    """Expose gesture intent without changing the observation verdict."""
    return dict(result, finger_direction=direction, view_direction=_OPPOSITE_DIRECTIONS[direction])


def scroll_view(direction="down", **options):
    """Browse toward content: 'down' sees lower items, 'up' sees earlier items.
    Uses scroll's geometry, timing, verification and options; legacy scroll keeps finger directions.
    """
    if not isinstance(direction, str) or direction not in _OPPOSITE_DIRECTIONS:
        raise ValueError("scroll_view direction must be up/down/left/right")
    return scroll(_OPPOSITE_DIRECTIONS[direction], **options)


def scroll(direction="up", frac=0.35, dur=600, times=1, verify=True, settle=0.5):
    """安全滚动: 从本次屏幕尺寸推出居中坐标; 派发时尺寸/旋转必须仍一致, 朝 direction 滚一屏的 frac。
    direction = 手指移动方向: 'up'(看下面内容) | 'down'(看上面) | 'left' | 'right'。
    返回 finger_direction 与相反的 view_direction；它们描述本次意图，不替代 scrolled/evidence 核验。
    默认短距离、低速度，保留相邻观察的内容重叠；需要快速遍历时显式传 frac/dur。
    verify=True: 内容区像素稳态复核 + dump 文本对比(真机实测: Flyme设置/WebView 同窗滚动后 a11y 树会滞后);
    调用方必须检查 scrolled/evidence/uncertain; uncertain=True 表示观察不可用/结论不确定,
    不是已验证未滚动, 不得据此盲目重试。
    ⚠️scroll 只吃方向/比例, 不是 swipe(x1,y1,x2,y2,dur)——曾被误当 swipe 调 scroll(900,1850,900,650,700)
    致 times=650 全屏狂滑失控。下方夹取幅度/时长/次数, 任何误用都退化为少量有界滚动(要精细滑用 droid.swipe)。
    循环守卫(SPEC W3): 派发前做等价检测——连续无效滚动(截图逐次一致)第 6 次起拒绝下发;
    一次调用落一条聚合账: scrolled=新证据(长列表扫描豁免, 断尾), 滑不动才计等价, uncertain=断尾。"""
    direction = _scroll_direction(direction)   # 非法方向必须在建账/守卫之前 fail-fast
    rec = _new_record("scroll", value=direction)
    guard = _pre_dispatch(rec)
    if guard is not None:
        return _apply_guard(rec, guard, "滚动")
    ret = _scroll_impl(direction, frac=frac, dur=dur, times=times, verify=verify, settle=settle)
    if "scrolled" not in ret:
        return ret                      # verify=False: 无证据不落账(铁律)
    if ret.get("uncertain"):
        _settle(rec, verdict="uncertain")
    elif ret.get("scrolled"):
        _settle(rec, verdict="settled", evidence_new=True, diff_pct=99.0)
    else:
        _settle(rec, verdict="settled", screenshot_exactly_same=True, diff_pct=0.0)   # 明确未滚动=可证明无效果
    return ret

def _scroll_direction(direction):
    """方向校验: 非法方向(误当 swipe 传坐标必命中) fail-fast, 不静默回退 'up' 再滚一堆。"""
    if direction not in ("up", "down", "left", "right"):
        raise ValueError("scroll 的 direction 必须是 'up'/'down'/'left'/'right'(看下方内容用 'up'), 收到 %r; "
                         "要按坐标精细滑请用 droid.swipe(x1,y1,x2,y2,dur)" % (direction,))
    return direction

def _scroll_impl(direction="up", frac=0.35, dur=600, times=1, verify=True, settle=0.5):
    """scroll 的实现体(签名/契约见 scroll docstring); 内部专用——直接调用会绕过守卫与落账。"""
    direction = _scroll_direction(direction)
    frac = min(max(float(frac), 0.05), 1.0)      # 一屏内的滚动比例; >1 或负值(误传坐标)夹回
    dur = min(max(int(dur), 50), 3000)           # 单次滑动时长(ms)
    settle = min(max(float(settle), 0.0), 3.0)   # 每次滚动后的沉降等待(s)
    times = min(max(int(times), 1), 10)          # 单次 scroll 最多发 10 段滑动(不变量: 操作原语自我限次防失控)
    errors = []
    try:
        p = ping()
        w = int(p.get("w"))
        h = int(p.get("h"))
    except Exception as exc:
        raise RuntimeError(
            "scroll geometry precondition failed: positive ping w/h required"
        ) from exc
    if w <= 0 or h <= 0:
        raise RuntimeError(
            "scroll geometry precondition failed: positive ping w/h required"
        )
    pkg_before = _resolve_fg(p.get("pkg") or "")
    sensitive = _sensitive_fg(pkg_before)   # 统一策略漏斗(_app_policy): 敏感或前台未解析(fail-closed)→只用像素证据, 不读 a11y 树
    cx, cy = w // 2, h // 2; sv = int(h * frac) // 2; sh_ = int(w * frac) // 2
    seg = {"up": (cx, cy + sv, cx, cy - sv), "down": (cx, cy - sv, cx, cy + sv),
           "left": (cx + sh_, cy, cx - sh_, cy), "right": (cx - sh_, cy, cx + sh_, cy)}.get(direction, (cx, cy + sv, cx, cy - sv))
    seg = tuple(min(max(v, 0), (w if i % 2 == 0 else h) - 1) for i, v in enumerate(seg))
    before_txt, before_img = None, None
    if verify:
        if not sensitive:
            try:
                before_txt = [
                    n.get("t") or n.get("d") or "" for n in dump()
                ]
            except Exception as exc:
                errors.append(_scroll_error("dump_before", exc))
        before_img = _scroll_shot()
        if before_img is None:
            errors.append("shot_before:Unavailable")

    action = {}
    for _ in range(times):
        action = swipe(*seg, dur=dur, verify=False, screen=p)   # scroll 自带稳态证据(前后 dump+JPEG); 段内 swipe 关掉自带后验, 否则 times 段=2×times 次多余截图
        # Native dispatch acknowledges acceptance before the gesture finishes.
        time.sleep(dur / 1000.0 + settle)
    if not verify:
        ret = dict(action or {})
        ret.update(performed=True, verified=False)
        return _scroll_feedback(direction, ret)

    after_txt, after_img = None, None
    if not sensitive:
        try:
            after_txt = [n.get("t") or n.get("d") or "" for n in dump()]
        except Exception as exc:
            errors.append(_scroll_error("dump_after", exc))
    after_img = _scroll_shot()
    if after_img is None:
        errors.append("shot_after:Unavailable")

    try:
        text_ratio = _text_change_ratio(before_txt, after_txt)
    except Exception as exc:
        errors.append(_scroll_error("text", exc))
        text_ratio = None
    first_pixel_pct, stable_pixel_pct, stable_img = None, None, None
    try:
        ih, iw = before_img.shape[:2]
        roi = (0, max(48, int(ih * .05)), iw,
               min(ih - 60, int(ih * .94)))
        first_pixel_pct = _pixel_change_pct(before_img, after_img, roi)
    except Exception as exc:
        errors.append(_scroll_error("pixel_first", exc))

    evidence = _scroll_verdict(text_ratio, first_pixel_pct, None)
    stable_unavailable = False
    if evidence == "none" and first_pixel_pct is not None and first_pixel_pct > 1.5:
        time.sleep(.4)
        stable_img = _scroll_shot()
        if stable_img is None:
            errors.append("shot_stable:Unavailable")
            stable_unavailable = True
        else:
            try:
                stable_pixel_pct = _pixel_change_pct(
                    before_img, stable_img, roi
                )
            except Exception as exc:
                errors.append(_scroll_error("pixel_stable", exc))
            if stable_pixel_pct is None:
                errors.append("pixel_stable:Unavailable")
                stable_unavailable = True
        evidence = _scroll_verdict(
            text_ratio, first_pixel_pct, stable_pixel_pct
        )

    try:
        final = ping() or {}
        pkg_after = final.get("pkg") or ""
    except Exception as exc:
        errors.append(_scroll_error("ping_final", exc))
        pkg_after = ""
    if not pkg_before:
        errors.append("pkg_before:Unavailable")
    if not pkg_after:
        errors.append("pkg_final:Unavailable")
    if not pkg_before or not pkg_after or pkg_before != pkg_after:
        before_name = pkg_before or "<unavailable>"
        after_name = pkg_after or "<unavailable>"
        if pkg_before and pkg_after:
            hint = (
                "滚动证据窗口内前台应用从 %s 变为 %s，无法把画面变化归因于滚动。"
                % (before_name, after_name)
            )
        else:
            hint = (
                "滚动前或最终前台应用观察失败，无法安全判断页面是否滚动。"
            )
        ret = {
            "scrolled": False,
            "pkg": pkg_after,
            "pkg_before": pkg_before,
            "pkg_after": pkg_after,
            "evidence": "none",
            "uncertain": True,
            "hint": hint,
        }
        if not pkg_before or not pkg_after:
            ret["error"] = "; ".join(dict.fromkeys(errors))[:160]
        return _scroll_feedback(direction, ret)

    if _shape_changed(before_img, after_img, stable_img):
        errors.append("evidence:ShapeChanged")
        return _scroll_feedback(direction, {
            "scrolled": False,
            "pkg": pkg_after,
            "evidence": "none",
            "uncertain": True,
            "error": "; ".join(dict.fromkeys(errors))[:160],
            "hint": "截图形态在证据窗内变化(旋转/折叠?)，无法判定是否滚动，请重新读取当前页面。",
        })
    if stable_unavailable:
        return _scroll_feedback(direction, {
            "scrolled": False,
            "pkg": pkg_after,
            "evidence": "none",
            "uncertain": True,
            "error": "; ".join(dict.fromkeys(errors))[:160],
            "hint": "滚动稳态截图观察失败，无法确认像素变化是滚动还是回弹。",
        })
    if text_ratio is None and first_pixel_pct is None:
        error = "; ".join(dict.fromkeys(errors))[:160]
        return _scroll_feedback(direction, {
            "scrolled": False,
            "pkg": pkg_after,
            "evidence": "none",
            "uncertain": True,
            "error": error or "observation:Unavailable",
            "hint": "滚动观察失败，无法判断页面是否滚动；请重新读取当前页面后再试。",
        })
    moved = evidence != "none"
    return _scroll_feedback(direction, {
        "scrolled": moved,
        "pkg": pkg_after,
        "evidence": evidence,
        "hint": None if moved else
                "内容区画面与可见文本均未稳定变化: 已到底/顶, 或该 App 对合成滚动不敏感。",
    })
def _boxes(nodes, key=None):
    """full dump 节点的 bbox [[l,t,r,b],...]; key 过滤(如 'edit' 只取可编辑框)。"""
    out = []
    for n in nodes:
        if n.get("b") and (key is None or n.get(key)):
            try: out.append([int(v) for v in str(n["b"]).split(",")])
            except Exception: pass
    return out
def _match(expected, observed):
    expected, observed = str(expected).strip(), str(observed).strip()
    if expected == observed:
        return True
    return min(len(expected), len(observed)) >= 4 and (
        expected in observed or observed in expected
    )
def _is_clipboard_label(text):
    normalized = "".join(str(text).split()).casefold()
    if normalized.endswith((":", "：")):
        normalized = normalized[:-1]
    return normalized in {"来自剪贴板", "fromclipboard"}
def _classify_paste_rows(text, rows, edits, screen_h):
    """Purely classify OCR rows as edit hits or IME clipboard evidence."""
    words, hit, hint, label = [], False, None, None
    clip_top = min(
        (min(p[1] for p in box) for box, s, _ in rows
         if _is_clipboard_label(s)
         and sum(p[1] for p in box) / len(box) > screen_h * .5),
        default=None,
    )
    for box, observed, score in rows:
        cx = sum(p[0] for p in box) / len(box)
        cy = sum(p[1] for p in box) / len(box)
        matched = _match(text, observed)
        item = {"box": box, "text": observed, "score": float(score), "hit": matched}
        words.append(item)
        is_label = (
            _is_clipboard_label(observed) and clip_top is not None
            and min(p[1] for p in box) >= clip_top - 2
        )
        if is_label:
            label = label or {**item, "hit": False}
        if not matched:
            continue
        if any(l - 8 <= cx <= r + 8 and t - 8 <= cy <= b + 8
               for l, t, r, b in edits):
            hit = True
        elif not is_label and clip_top is not None and cy >= clip_top:
            hint = hint or item
    out = {"ocr": words, "hit": hit}
    if hint:
        out["ime_hint"] = hint
    if label:
        out["ime_label"] = label
    return out
def _ocr_region(img, x1, y1, x2, y2):
    """OCR 图像子区域；padding/过滤由 PPOCR.region 统一处理，结果还原到整图坐标。"""
    h, w = img.shape[:2]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 12 or y2 - y1 < 12:
        return []
    rows = _ocr_engine().region(img[y1:y2, x1:x2])
    return [
        ([[int(px) + x1, int(py) + y1] for px, py in box], text, float(score))
        for box, text, score in rows
    ]
def _paste_error(stage, exc):
    """Return bounded, non-sensitive verification error metadata."""
    kind = "".join(
        ch for ch in type(exc).__name__ if ch.isalnum() or ch in "_-"
    )[:48] or "Exception"
    return ("%s:%s" % (stage, kind))[:80]
def _try_paste_verification(stage, operation, errors, fallback=None):
    try:
        return operation()
    except Exception as exc:
        errors.append(_paste_error(stage, exc))
        return fallback
def _paste_unavailable(ret, errors, hint=None):
    error = "; ".join(dict.fromkeys(errors))[:160] or "verification:Unavailable"
    ret.update(hit=False, uncertain=True, verify="unavailable", error=error)
    warning = "验证不可用，无法确认文本是否上屏；请核对当前帧输入框，或由用户接管。"
    ret["hint"] = (hint + " " + warning) if hint else warning
    return ret
def paste(text, verify=True, replace=False, point=None):
    """剪贴板注入后立即验证：单次 dump → 编辑框识别 → 必要时区域检测。
    replace=False(默认)=在光标处追加; replace=True=先全选框内旧文本再粘贴=覆盖(预填昵称/旧搜索词/改地址一律用它, 没有退格键可用),
    此时 dump 验证按「框内文本 == text」判 hit(追加模式是包含匹配)。框不支持选区时 a11y 侧抛错(不会静默变成追加)。
    hit=True=已确认上屏; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级。
    ime_label 仅为元数据; 只有 ime_hint 可点击。
    point=输入框中心像素(可选): 敏感 App 走 GUI 粘贴时用它当长按锚点; 不给则用最近一次手势落点。
    敏感 App 或前台未解析时只设置剪贴板 + 自动完成可见 GUI 粘贴(长按→点菜单/点键盘候选)并回读验证,
    仍不成才返回 needs_gui_paste=True; 绝不能把"剪贴板已设置"当成输入成功。
    循环守卫(SPEC W3): 连续等价无效输入第 2 次起 REFOCUS(请先重聚焦再重试)→RETRY(最后一次自动放行)→ABORT;
    落账: hit=新证据(断尾), uncertain=断尾, 明确未上屏=可证明无效果(进阶梯)。"""
    text = str(text)
    if not text:
        raise ValueError("paste text must not be empty")
    rec = _new_record("paste", value=text)
    guard = _pre_dispatch(rec)
    if guard is not None:
        action = guard.get("recovery")
        if action == "REFOCUS":
            _settle(rec, verdict="recovered", recovery="REFOCUS", screenshot_exactly_same=True)
            return {"ok": 1, "recovered": "REFOCUS", "hit": False,
                    "hint": "循环守卫: 连续等价的无效输入, 本次未发送。请先 tap 输入框重新聚焦再重试 paste; 若已聚焦, 核对字段是否已有等长文本或掩码。"}
        if action == "RETRY":
            # 最后一次自动放行: 先落一条 recovered 标记推进阶梯, 再走正常流程
            _settle(_new_record("paste", value=text), verdict="recovered", recovery="RETRY", screenshot_exactly_same=True)
        else:
            # 输入类只有 ABORT 一种"不下发"形态(拒绝级被 type ladder 完全覆盖)
            _settle(rec, verdict="aborted", screenshot_exactly_same=True)
            return {"ok": 0, "aborted": True, "hit": False,
                    "hint": "循环守卫: 同一输入连续无可观察变化且恢复手段已用尽, 本次未执行。请重新观察当前屏幕, 更换目标或策略, 或 ask_user 说明阻塞。"}
    ret = _paste_impl(text, verify=verify, replace=replace,
                      anchor=point if point is not None else last_touch())
    if "hit" not in ret:
        return ret                      # 未验证/未产出判定: 无证据不落账(铁律)
    if ret.get("hit"):
        _settle(rec, verdict="settled", evidence_new=True, diff_pct=99.0, hit=True)   # 已确认上屏=新证据(断尾)
    elif ret.get("uncertain"):
        _settle(rec, verdict="uncertain")                                           # 验证不可用: 断尾不进阶梯
    else:
        _settle(rec, verdict="settled", screenshot_exactly_same=True, diff_pct=0.0, hit=False)  # 明确未上屏=可证明无效果
    return ret

_PASTE_LABELS = {"粘贴", "粘貼", "paste"}


def _is_paste_label(text):
    """'粘贴' 菜单项判定: 去空白/尾冒号后全等, 不做子串(避免把 '粘贴板设置' 当菜单)。"""
    return "".join(str(text).split()).casefold().rstrip(":：") in _PASTE_LABELS


def _pick_paste_target(text, rows, screen_h, anchor=None):
    """从 OCR 行里挑出"真正能完成 GUI 粘贴"的那一下点击。纯函数, 无设备副作用。

    返回 (kind, box, label) 或 None:
      'menu' —— 长按浮出的「粘贴」菜单; 位置随输入法/App 变, 只按画面找, 不写死坐标。
                 给了锚点时只认锚点下方 600px 内的(菜单就浮在长按处下方), 取最近的;
      'chip' —— 输入法剪贴板候选(Android 10+ 键盘顶栏, 文本即剪贴板内容), 只在下半屏找,
                 避免把搜索结果里同样的文字当成候选。
    优先级: 已经开着的菜单 > 键盘候选(菜单在当帧可见, 不需要再长按一次)。"""
    if not rows:
        return None
    best = None
    for box, label, _score in rows:
        if not _is_paste_label(label):
            continue
        cy = sum(p[1] for p in box) / len(box)
        if anchor is not None:
            dy = cy - float(anchor[1])
            if dy < -40 or dy > 600:
                continue
            dist = abs(dy)
        else:
            dist = cy
        if best is None or dist < best[0]:
            best = (dist, "menu", box, label)
    if best is not None:
        return best[1:]
    band = float(screen_h) * 0.5
    chip = None
    for box, label, _score in rows:
        if _is_paste_label(label) or not _match(text, label):
            continue
        cy = sum(p[1] for p in box) / len(box)
        if cy < band:
            continue
        if chip is None or cy < chip[0]:
            chip = (cy, "chip", box, label)
    if chip is not None:
        return chip[1:]
    return None


def _gui_paste(text, anchor=None, replace=False):
    """视觉型 App 的唯一输入通道: 剪贴板 + 可见 GUI 粘贴, 一次调用做完并验证上屏。

    为什么必须原子: 敏感 App 禁 setText、禁读节点树, 旧实现只把文本塞进剪贴板就把
    "长按输入框→点粘贴"甩回给模型, 每输入一次多花 2 轮(真机 5 个任务里 4 个踩到, 约 19s/次)。
    这里把「一次 OCR 定位 + 一次手势 + 一次视觉确认」收进一次工具调用。
    红线不变: 只读屏幕像素、只发手势, 不碰节点树, 不注入文本。
    """
    _act(op="clipboard", text=text)
    steps = ["clipboard"]
    try:
        img = shot()
        h = int(img.shape[0])
        rows = _ocr_region(img, 0, 0, int(img.shape[1]), h)
    except Exception as exc:
        return _paste_needs_gui(text, steps, "读屏失败(%s)" % type(exc).__name__)
    target = _pick_paste_target(text, rows, h, anchor)
    if target is None and anchor is not None:
        # 当帧没有粘贴入口: 长按锚点唤出菜单再看一眼。用 _act 而不是 longpress(), 免得重复落账。
        try:
            _act(op="swipe", x1=int(anchor[0]), y1=int(anchor[1]),
                 x2=int(anchor[0]), y2=int(anchor[1]), dur=800)
            steps.append("longpress")
            time.sleep(0.45)
            img = shot()
            h = int(img.shape[0])
            rows = _ocr_region(img, 0, 0, int(img.shape[1]), h)
            target = _pick_paste_target(text, rows, h, anchor)
        except Exception:
            target = None
    if target is None:
        return _paste_needs_gui(
            text, steps,
            "未在屏幕上找到可点的『粘贴』菜单或键盘剪贴板候选")
    kind, box, label = target
    cx = int(sum(p[0] for p in box) / len(box))
    cy = int(sum(p[1] for p in box) / len(box))
    _act(op="tap", x=cx, y=cy)
    steps.append("tap:%s" % kind)
    time.sleep(0.6)
    try:
        img = shot()
        h = int(img.shape[0])
        top = anchor[1] + 160 if anchor is not None else int(h * 0.32)
        rows = _ocr_region(img, 0, max(0, int(anchor[1]) - 160) if anchor is not None else 0,
                           int(img.shape[1]), min(h, int(top)))
    except Exception:
        return {"hit": False, "uncertain": True, "verify": "gui_paste", "steps": steps,
                "hint": "已点击『%s』但读屏确认失败; 不要重复点击, 先观察当前画面。" % label}
    observed = next((s for _b, s, _sc in rows if _match(text, s)), "")
    if observed:
        out = {"hit": True, "verify": "gui_paste", "text": observed, "steps": steps,
               "paste_via": kind}
        if replace:
            out["replace_unverified"] = True
        return out
    return {"hit": False, "uncertain": True, "verify": "gui_paste", "steps": steps,
            "hint": ("已点『%s』但框内未看到文本(可能焦点不在输入框)。先 tap 输入框聚焦再重试, "
                     "或交用户处理; 文本仍在剪贴板, 不会丢。" % label)}


def _paste_needs_gui(text, steps, cause):
    """GUI 粘贴没做成时的统一出口: 契约与旧行为一致(hit=False/uncertain/needs_gui_paste)。"""
    hint = ("%s。文本仍在剪贴板: 用当前截图定位输入框中心, 长按输入框后点可见的粘贴菜单, "
            "或点键盘顶栏的剪贴板候选; 长按空白处会收起键盘。替换时先通过 GUI 清空。"
            "已试步骤: %s" % (cause, '/'.join(steps)))
    print("[GUI input] " + hint)
    return {"hit": False, "uncertain": True, "needs_gui_paste": True, "steps": steps, "hint": hint}


def _paste_impl(text, verify=True, replace=False, anchor=None):
    """paste 的实现体(契约见 paste docstring); 内部专用——直接调用会绕过守卫与落账。"""
    text = str(text)
    if not text:
        raise ValueError("paste text must not be empty")
    if _sensitive_fg():
        # 视觉型 App: 唯一合法的输入通道是"剪贴板 + 可见 GUI 粘贴", 且必须一次做完。
        return _gui_paste(text, anchor=anchor, replace=bool(replace))
    ret = _act(op="paste", text=text, replace=bool(replace)); ret.pop("ok", None)
    if not verify:
        return ret
    _squash = lambda s: "".join(str(s).split())                    # 输入框常做格式化回显(会议号「123 456 789」、卡号分组、NBSP): 比较时去掉全部空白
    matched = (lambda observed: _squash(observed) == _squash(text)) if replace else (lambda observed: _match(text, observed))

    errors = []
    error_count = len(errors)
    if _sensitive_fg():
        nodes = []                                       # 敏感 App/前台未解析(fail-closed): 跳过 a11y 树, 走 shot()+OCR 视觉验证
    else:
        nodes = _try_paste_verification(
            "dump", lambda: dump(full=True), errors, []
        ) or []
    dump_error = len(errors) > error_count
    for node in nodes:
        observed = node.get("t") or ""
        if node.get("edit") and matched(observed):
            ret.update(hit=True, verify="dump", text=observed)
            return ret
    if replace and any(n.get("edit") and (n.get("t") or "").strip() for n in nodes):   # 框里有字但 ≠ text: 替换没生效, 明确报 miss(不退 OCR 兜底, 否则包含匹配会把「ozerGA测试」判成命中)
        observed = next(n.get("t") for n in nodes if n.get("edit") and (n.get("t") or "").strip())
        ret.update(hit=False, uncertain=False, verify="dump", text=observed, hint="replace 未生效: 框内仍为 %r; 点框内 ✕ 清除后重试, 或交用户处理" % observed[:40])
        return ret

    def _capture():
        image = shot()
        height, width = image.shape[:2]
        if int(height) <= 0 or int(width) <= 0:
            raise ValueError("invalid image")
        return image, int(height), int(width)
    capture = _try_paste_verification("shot", _capture, errors)
    if capture is None:
        return _paste_unavailable(ret, errors)
    img, h, w = capture

    edits = _boxes(nodes, "edit")
    for l, t, r, b in edits:
        x1, y1 = max(0, l), max(0, t)
        x2, y2 = min(w, r), min(h, b)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        def _recognize():
            observed, score = ocr_text(crop)
            return observed, float(score)
        recognized = _try_paste_verification(
            "ocr_text", _recognize, errors
        )
        if recognized is None:
            continue
        observed, score = recognized
        if _match(text, observed):
            item = {
                "box": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                "text": observed,
                "score": score,
                "hit": True,
            }
            if not errors:
                ret.update(
                    hit=True, verify="recognize", text=observed, ocr=[item]
                )
                return ret

    edit_bottom = max((b[3] for b in edits), default=0)
    if edit_bottom >= h - 8:
        edit_bottom = 0
    if edits:
        band_top = edit_bottom or int(h * 0.5)
        rows = _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, band_top - 24, w, h),
            errors,
            [],
        ) or []
    else:
        band_top = int(h * 0.5)
        rows = _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, band_top - 24, w, h),
            errors,
            [],
        ) or []
        rows += _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, 0, w, band_top),
            errors,
            [],
        ) or []

    evidence = _try_paste_verification(
        "ocr_classify",
        lambda: _classify_paste_rows(text, rows, edits, h),
        errors,
        {"ocr": [], "hit": False},
    )
    ret.update(evidence, verify="ocr")
    if errors:
        ret["hit"] = False
        ret["uncertain"] = True
    elif not edits:
        ret["hit"] = False
        ret["uncertain"] = True

    if ret["hit"]:
        return ret
    if not edits:
        cause = (
            "a11y dump 读取失败，未定位到输入框"
            if dump_error else "未定位到输入框"
        )
        hint = (
            cause + "，当前帧无法确认文本是否上屏；请提供当前帧输入框位置后重试，"
            "或由用户接管。"
        )
        if ret.get("ime_hint"):
            hint += (
                " 若已确认输入框聚焦，可 tap ime_hint['box'] 的内容框中心，再重新验证。"
            )
        elif ret.get("ime_label"):
            hint += " 当前仅见剪贴板标签，不要把 ime_label 当作内容点击。"
    elif ret.get("ime_hint"):
        hint = (
            "未上屏，但已定位键盘剪贴板内容：tap ime_hint['box'] 中心后重新验证；"
            "不要点击 ime_label。"
        )
    elif ret.get("ime_label"):
        hint = (
            "未上屏，仅识别到键盘剪贴板标签，未定位到可点击的内容；"
            "不要把 ime_label 当作内容点击，请重新聚焦输入框后再 paste。"
        )
    else:
        hint = (
            "未上屏且未见剪贴板提示条: ①重新 tap 输入框聚焦(常可唤出提示条)后再 paste 看 ime_hint; "
            "②长按输入框粘贴(键盘/面板弹起时先收起让输入框裸露——文本在剪贴板不会丢; "
            "坐标取当帧输入框 bbox 中心, 禁按在键盘键位上); "
            "③纯 ASCII 逐键打字兜底(同帧定位全部键位后连续 tap)。递进细则见 phone_use.md §3。"
        )
    if errors:
        return _paste_unavailable(ret, errors, hint)
    ret["hint"] = hint
    return ret
def key(name="ENTER"):
    r = _act(op="key", name=name)  # IME动作键, 仅ENTER(=搜索/发送/换行, 视输入框而定)
    _trace("key", args={"name": name})
    return r
def launch(pkg, wait=1.0):
    # 免adb启动app。敏感 App(nofloat 策略)不起 GA 悬浮窗并收起已有悬浮窗: overlay 是 App 可观测的"自动化工具在场"信号(见 SENSITIVE_APPS 注释)
    nofloat = bool(SENSITIVE_APPS.get(pkg, {}).get("nofloat"))
    ret = _act(op="launch", pkg=pkg, nofloat=nofloat); ret["fg"] = _wait_fg(pkg, wait)
    # 只认"前台真的是目标包名": _wait_fg 超时返回的是**最后一次**前台(可能是桌面 com.miui.home),
    # 旧代码只判 fg 非空就把拉起当成功, 接着跳过 wait_stable 并用拉起前的帧算坐标。
    ret["fg_ok"] = bool(ret["fg"] and ret["fg"] == pkg)
    if not ret["fg_ok"]:
        ret["hint"] = ("拉起未确认: 前台是 %r, 不是目标包 %r。不要在这一屏上算坐标 —— 先 "
                       "gui_act action='wait' 或重新 launch, 再重新观察。" % (ret["fg"], pkg))
    try:
        p = ping()
        w, h, rot = int(p.get('w') or 0), int(p.get('h') or 0), int(p.get('rot') or 0)
        if w and h: ret.update(screen=(w, h), rot=rot, orientation=_orientation(w, h))
    except Exception:
        pass
    if nofloat:
        ret["policy"] = "sensitive: visual-only; overlay follows user preference" + (", act=locked(零注入, 见 droid.sensitive_status())" if SENSITIVE_APPS[pkg].get("act") == "locked" else "")
    # 拉起后必须重生一帧: launch 自己不产生后验帧, _PENDING_FRAME 里可能还躺着"拉起之前"那一屏,
    # 谁复用它谁就在照旧画面算坐标(真机 t2 launch 之后 obs 给的就是旧帧)。
    try:
        time.sleep(_SHOT_MIN_GAP_S)     # 跨过截屏最小间隔, 否则必撞 code=3 再等 .35s
        _stash_frame(shot())
        ret["frame_fresh"] = True
    except Exception:
        ret["frame_fresh"] = False      # 截不到就明确说没有, 让上层重新 shot(), 不装成有帧
    _trace("launch", args={"pkg": pkg}, result={"pkg": ret.get("fg") or pkg})
    return ret
# ---------------- App 入口原语: 固化"入口路径", 不固化业务页 ----------------
# 只固化入口路径(打开 App → 点搜索入口 → 输入关键词并回读), 业务页坐标仍必须当帧观测。
# 为什么这些可以写死: 它们是 App 自己标题栏的稳定锚点(用 0-1000 相对坐标, 与分辨率无关),
# 属于高频任务入口; 实测值来自 memory/phone_use.md §0.4 的真机记录。
# 这不撞 geom.py:15-19 的红线 —— 那条禁止的是"把 App 特有位置塞进通用几何层", 而这里是
# App 自己的入口表, 仍在 App 这一层; 通用接口缺陷仍然只能靠当帧观测兜。
APP_ENTRY = {
    # search_rel: 标题栏搜索入口中心的 0-1000 相对坐标(微信主页实测 996,215 @1200x2670 → 830,79)
    "com.tencent.mm": {"label": "微信", "search_rel": (830, 79)},
}


def entry_hint(pkg=""):
    """该 App 有没有固定入口路径(供 observe/提示用); 没有返回 {}。"""
    return dict(APP_ENTRY.get(pkg or (_fg() or ""), {}) or {})


def _search_rows(limit=6):
    """当帧搜索框下方的前几行(设备像素), 给 search_app 一步带回结果列表的位置。

    结果列表的布局随查询而变, 所以这里**不写死**任何位置: 每一行都是这一帧 OCR 出来的。
    OCR 会把一条结果切成 2~3 段(标题/来源/热度), 这里按纵向邻近合并成一"行"。
    失败一律返回 [] —— 拿不到行不该让已经成功的"关键词上屏"变成失败。
    """
    try:
        import numpy as np
        img = shot()
        H = int(np.asarray(img).shape[0])
        raw = []
        for box, text, score in ocr(img) or []:
            t = str(text or '').strip()
            if not t:
                continue
            pts = np.asarray(box, dtype='float32').reshape(-1, 2)   # 4 角点或 [x1,y1,x2,y2] 都吃
            cy = int((pts[:, 1].min() + pts[:, 1].max()) / 2)
            if not (int(H * 0.06) <= cy <= int(H * 0.92)):
                continue
            raw.append({'t': t[:40], 'x': int((pts[:, 0].min() + pts[:, 0].max()) / 2),
                        'y': cy, 'conf': round(float(score or 0), 2)})
        raw.sort(key=lambda r: r['y'])
        # 同一行会被 OCR 切成几段(标题/来源/热度), 段间纵向差在真机约 1.5%~2% 屏高;
        # 而相邻两条结果行至少差 10% 屏高(2026-10-29 实测 244/527/874px @2670), 取 2% 安全。
        rows, row_tol = [], max(12, int(H * 0.02))
        for r in raw:
            if rows and abs(r['y'] - rows[-1]['y']) <= row_tol:
                if len(rows[-1]['t']) < 60:
                    rows[-1]['t'] = (rows[-1]['t'] + ' ' + r['t'])[:60]
                continue
            rows.append(dict(r))
        return rows[:limit]
    except Exception:
        return []

def app_search(pkg="com.tencent.mm", query="", wait=2.0):
    """确定性"打开 App → 搜关键词": 一步替掉 模型 see(均值 20.8s)→tap→text 的 3~5 轮。

    每一步都有判据, 任一步不成立就带着原因停下(不做"看起来成功了"的静默降级):
      1) launch 后前台必须 == 目标包名(只判"非空"会把拉起失败当成功);
      2) 等首帧稳定(启动动画期间点下去会落到别的元素上);
      3) 点入口锚点, 用 diff 判它是否真的换了屏(没换=点空);
      4) paste 关键词并按 hit 回读确认真的上屏。
    不点搜索结果: 结果列表布局随查询而变, 那部分必须当帧观测。
    返回 {ok, pkg, query, steps:[每步判据], search_entry, fg, hint?}。"""
    pkg = str(pkg or "").strip()
    if not pkg:                         # 没指定才推断; 明确指定了未登记的包就直说没有(别偷换成微信)
        _cur = _fg()
        pkg = _cur if _cur in APP_ENTRY else (sorted(APP_ENTRY)[0] if len(APP_ENTRY) == 1 else "")
    query = str(query or "").strip()
    steps = []                                  # 每一步的判据都记下来, 失败时直接指出是哪一步
    out = {"ok": False, "pkg": pkg, "query": query, "steps": steps}
    if not query:
        out["hint"] = "search_app 需要 value(要搜的关键词)"
        return out
    entry = APP_ENTRY.get(pkg)
    if not entry:
        out["hint"] = ("没有该 App 的固定入口路径(已知: %s)。用 gui_act 的 tap/text 自己走一次; "
                       "走通后可 droid.recipe_record() 记成配方。" % ", ".join(sorted(APP_ENTRY)))
        return out
    lr = launch(pkg, wait=wait)                    # 1) 拉起 + 严格确认前台
    steps.append({"step": "launch", "fg": lr.get("fg"), "fg_ok": lr.get("fg_ok")})
    if not lr.get("fg_ok"):
        out["hint"] = ("拉起未确认(前台 %r ≠ %r): 先解决前台, 别在别的画面上点来点去。"
                       % (lr.get("fg"), pkg))
        return out
    try:
        p = ping() or {}
    except Exception:
        p = {}
    w, h = int(p.get("w") or 0), int(p.get("h") or 0)
    if not w or not h:
        out["hint"] = "拿不到屏幕尺寸, 无法把入口相对坐标换算成像素。"
        return out
    st = wait_stable(max_wait=max(1.0, float(wait)))        # 2) 等首页稳定
    steps.append({"step": "settle", "stable": st.get("stable"), "waited_s": st.get("waited_s")})
    rx, ry = entry["search_rel"]
    ex, ey = int(round(rx / 1000.0 * w)), int(round(ry / 1000.0 * h))   # 3) 点入口
    tr = tap(ex, ey)
    diff_s = str(tr.get("diff") or "")
    try:
        entry_pct = float(diff_s.split("%", 1)[0].split()[-1])
    except Exception:
        entry_pct = None
    steps.append({"step": "entry_tap", "point": [ex, ey], "diff": diff_s, "fg": tr.get("fg")})
    if entry_pct is not None and entry_pct < 1.0:
        out["hint"] = ("点了入口(%d,%d)但屏幕几乎没变(%.3f%%): 入口位置可能不适用于当前版本/页面, "
                       "改为看当帧画面(obs/see)再点, 不要重复 search_app。"
                       % (ex, ey, entry_pct))
        out["search_entry"] = {"point": [ex, ey], "rel": [rx, ry]}
        return out
    pr = paste(query, point=(ex, ey))                                # 4) 输入并回读
    steps.append({"step": "paste", "hit": pr.get("hit"), "uncertain": pr.get("uncertain"),
                  "needs_gui_paste": pr.get("needs_gui_paste")})
    out["search_entry"] = {"point": [ex, ey], "rel": [rx, ry]}
    out["fg"] = _fg()
    if pr.get("hit"):
        out["ok"] = True
        rows = _search_rows()
        if rows:
            out["results"] = rows
            out["hint"] = ("关键词已上屏。results 是这一帧 OCR 到的结果行(设备像素, 按 y 排序): "
                           "要哪一行就 gui_act action=tap point=[x,y], 或 target=<那一行的文字>; "
                           "别再点搜索框、别重复 paste、别把附图上的像素填进 point。")
        else:
            out["hint"] = ("关键词已上屏。别再点搜索框或重复 paste: 直接用 obs 或 "
                           "see(want='point') 定位第一条结果再 tap。")
    else:
        out["hint"] = pr.get("hint") or ("输入未确认上屏(needs_gui_paste): 按提示手动补一次粘贴, "
                                         "不要重复 search_app。")
    return out


def search_app(pkg="com.tencent.mm", query="", wait=2.0): return app_search(pkg=pkg, query=query, wait=wait)   # schema 的 action 名就是 search_app, 契约测试按名对账
def pkgs(filter=""): return _act(op="pkgs", filter=filter)["apps"]  # 列可启动app[{pkg,label}], filter模糊匹配包名/应用名如'美团'
_BACK_TEXTS = ("返回上一级", "返回", "关闭窗口", "关闭", "取消", "退出", "跳过", "×", "✕", "╳", "X", "←", "‹", "〈")


def _pct_from_diff(diff):
    """'diff: 83.904% bbox=[...]' → 83.904; 解析不了返回 None。"""
    try:
        return float(str(diff).split("%", 1)[0].split()[-1])
    except Exception:
        return None


def ui_back(verify=True, wait=1.0, tries=2, allow_system=True):
    """回退一层: **先点屏上的返回/关闭按钮**, 都点不到才按系统 back。

    为什么不能直接 back: 小程序/自绘 canvas/H5 页面会把系统返回键吃掉(或根本不响应),
    在那种页面上 back 等于没按。真机 2026-10-30 09:15 的三角洲会话就是这样: 目标入口在上一级
    页面, 模型(和之前的提示)只会按 back, 于是在弹窗层里瞎点 6 次。这类页面唯一的出口是屏幕上
    那个「返回 / 关闭 / ×」按钮。
    宁可多点一次按钮, 也不要在 canvas 页上把"没反应"当成"回不去"。

    返回 {ok, via: 'button'|'system', text, point, diff, tried}。"""
    img = shot()
    H, W = img.shape[:2]
    cands = []
    try:
        for box, text, score in ocr(img) or []:
            t = str(text or "").strip()
            if not t or len(t) > 10:
                continue                      # 长句是正文, 不是按钮
            if not any(k == t or k in t for k in _BACK_TEXTS):
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            cx, cy = int((min(xs) + max(xs)) / 2), int((min(ys) + max(ys)) / 2)
            # 标题行/顶部的返回键优先, 其次按从左到右(返回键几乎都在左上)
            cands.append((0 if cy < H * 0.3 else 1, cx, cy, t))
    except Exception:
        cands = []
    if not cands:
        # 无文字图标(← 这种没有 OCR 文本): 标题带里最左边那个 icon 就是返回键
        try:
            for it in look(roi="title") or []:
                x, y = int(it.get("x") or 0), int(it.get("y") or 0)
                if 0 < x < W * 0.3:
                    cands.append((0, x, y, str(it.get("label") or it.get("cls") or "icon")))
                    break
        except Exception:
            pass
    cands.sort()
    tried = []
    for _, x, y, t in cands[:max(1, int(tries))]:
        try:
            r = tap(x, y, verify=verify, wait=wait)
        except Exception:
            break
        pct = _pct_from_diff(r.get("diff"))
        tried.append({"text": t, "point": [x, y], "diff": r.get("diff")})
        if verify and _closed_ok(pct):
            return {"ok": True, "via": "button", "text": t, "point": [x, y],
                    "diff": r.get("diff"), "tried": tried}
    if not allow_system:
        return {"ok": False, "via": "none", "diff": None, "tried": tried,
                "hint": ("这是弹层: 没找到可点的返回/关闭控件, 也没替你按系统返回"
                         "(会把整个小程序退掉)。改用 gui_act {\"action\":\"close\"}, "
                         "或 target=<弹层上的文字>。")}
    r = back()
    pct = _pct_from_diff(r.get("diff"))
    return {"ok": bool(pct is not None and pct >= _DIFF_CLOSED_PCT), "via": "system",
            "diff": r.get("diff"), "tried": tried,
            "hint": ("" if tried else "屏上没有找到返回/关闭按钮"),
            }


_CLOSE_TEXTS = ("关闭窗口", "关闭", "取消", "我知道了", "知道了", "暂不", "以后再说")
# 单字符关闭符: **只认全等**。真机 15:30:02 的 close 里 OCR 出来一个 "TEXT", 旧判据用
# `any(k in t)` 匹配, 因为 _CLOSE_TEXTS 里有 "X", 于是 "TEXT" 被当成关闭按钮点到了 (193,418)。
_CLOSE_CHARS = ("×", "✕", "╳", "✖", "x")


def _is_close_text(t):
    """这段文字是不是「关闭/取消/×」这类按钮(单字符只认全等, 不做子串)。"""
    s_ = str(t or "").strip()
    if not s_:
        return False
    if s_.lower() in _CLOSE_CHARS:
        return True
    return any(k in s_ for k in _CLOSE_TEXTS)

# 「关掉这一层」的最小画面变化(百分数)。_pct_from_diff 返回的就是百分数(10.037 = 10.037%),
# 这里原本跟 0.2 比 —— 等于把 0.2% 的动画抖动当成关上了。真机 15:11:34 / 15:13:51 两次
# close 就是被弹窗里卡片轮播抖出来的 10% 判成成功, 模型以为关掉了, 接着点「制造推荐」
# 直接穿透到弹窗后面的「航天基地」卡片详情, 然后再也回不来。
_DIFF_CLOSED_PCT = 20.0


def _close_icon_ok(label):
    """图标兜底的准入: 只有「没文字」或「像关闭键」的检出项才当成那个叉。

    真机 15:11:34 的 close 把弹窗里「航天基地」这张卡当成了右上角叉 —— 它只是位置落在弹层
    bbox 的右上方, 一点就进航天基地详情。所以带中文内容的标签一律不进候选。
    """
    t = str(label or "").strip()
    if not t:
        return True
    if t in _CLOSE_TEXTS:
        return True
    for ch in t:
        if ord(ch) > 0x2E80:
            return False
    # 拉丁标签只放行短符('x'/'ok'): 真机 15:30:02 被误点的正是 OCR 读出来的正文 'TEXT',
    # 四个字母以上的拉丁词一律当正文, 不是那个叉。
    return len(t) <= 3


def _text_on_screen(text):
    """这一层的关键字还在不在屏上(重新截一帧 OCR), 用来核验「真的关掉了」。"""
    if not text:
        return False
    try:
        for _bx, t, _s in ocr(shot()) or []:
            if text in str(t or ""):
                return True
    except Exception:
        return False
    return False


def _closed_ok(pct, expect_text=None):
    """这一下算不算把层关掉: 画面变化够大, 且给了 expect_text 时它真的从屏上消失了。"""
    if pct is None:
        return True
    if pct < _DIFF_CLOSED_PCT:
        return False
    return not _text_on_screen(expect_text)


_CAPSULE_MIN_X = 0.72      # 小程序「总控胶囊」在标题带右侧, 只认最右 28% 的图标框


def miniapp_capsule():
    """认出微信小程序右上角「总控胶囊」里的两个键: 左=分享/更多, 右=关闭(退出小程序)。

    为什么单独一个原语: 用户 2026-10-30 明确 —— 小程序右上角并排两个键, 一个分享一个关闭,
    那是小程序的**总控**, 非必要不要点。代码以前只有"标题带"一个概念, 于是模型把随便一个角
    当成关闭点: 10:06 / 10:26 / 10:52 三次会话都这样点开了分享面板(每次 diff 85.85%).

    不写死任何像素: 只认 YOLO 在 title 带里给的图标框, 取最右的当关闭, 紧挨它左边
    (±2% 屏高, 同一行)的当分享/更多。YOLO 没给框就老实说不知道, 由调用方退到 see()。

    返回 {found, more, close, screen:[w,h], hint}。
    """
    W = H = 0
    try:
        p = ping()
        W, H = int(p.get("w") or 0), int(p.get("h") or 0)
    except Exception:
        pass
    if not (W and H):
        return {"found": False, "more": None, "close": None, "screen": [W, H],
                "hint": "拿不到屏幕尺寸, 认不出胶囊: 用 close 或 target= 走别的手"}
    band = getattr(geom, "BANDS", {}).get("title") or (0.0, 0.055, 1.0, 0.120)
    y_lo, y_hi = band[1] * H, band[3] * H
    try:
        items = look(roi="title") or []
    except Exception:
        items = []
    cands = set()
    for it in items:
        try:
            x, y = int(it["x"]), int(it["y"])
        except Exception:
            continue
        if x < W * _CAPSULE_MIN_X:
            continue
        if not (y_lo - 8 <= y <= y_hi + 8):
            continue
        cands.add((x, y))
    cands = sorted(cands)
    if not cands:
        return {"found": False, "more": None, "close": None, "screen": [W, H],
                "hint": ("这一帧没在标题带右侧认出图标框: 想按胶囊就用 see(want='point', "
                         "question='小程序右上角关闭键在哪', roi='title'); 关弹层用 close; "
                         "点页面上的字用 target=")}
    close_pt = [cands[-1][0], cands[-1][1]]
    more_pt = None
    if len(cands) >= 2:
        lx, ly = cands[-2]
        if abs(ly - close_pt[1]) <= max(40, int(H * 0.02)):
            more_pt = [lx, ly]
    return {"found": True, "more": more_pt, "close": close_pt, "screen": [W, H],
            "hint": ("胶囊 = 小程序总控: 左「分享/更多」右「关闭(退出小程序)」; 非必要不要点。"
                     "要离开整个小程序用 action=exit_miniapp, 关页内弹层用 action=close")}


def exit_miniapp(verify=True, wait=1.0):
    """点胶囊里的**关闭**键离开整个小程序(canvas 页系统返回键无效时的唯一出路)。

    只点最右那个键: 左边是分享/更多, 点了只会弹分享面板(真机 10:52 复现)。
    返回 {ok, via:'capsule_close'|'none', point, more, diff, hint}。
    """
    cap = miniapp_capsule()
    if not cap.get("found") or not cap.get("close"):
        return {"ok": False, "via": "none", "point": None, "more": cap.get("more"),
                "diff": None, "hint": cap.get("hint")}
    x, y = cap["close"]
    try:
        r = tap(x, y, verify=verify, wait=wait)
    except Exception as e:
        return {"ok": False, "via": "capsule_close", "point": [x, y], "more": cap.get("more"),
                "diff": None, "hint": "点胶囊关闭键失败: %s" % (e,)}
    pct = _pct_from_diff(r.get("diff"))
    ok = bool((pct is not None and pct >= _DIFF_CLOSED_PCT) or (pct is None and not verify))
    return {"ok": ok, "via": "capsule_close", "point": [x, y], "more": cap.get("more"),
            "diff": r.get("diff"),
            "hint": (None if ok else "点了胶囊关闭键但画面没变: 可能已退出小程序/或在别的层, "
                                     "先 observe 看清楚再动")}


def close_dialog(bbox=None, verify=True, wait=0.8, tries=3, expect_text=None, allow_back=None):
    """关掉屏幕上的弹层: **只在弹层自己的范围里**找关闭控件, 找不到再按系统返回。

    为什么单独一个原语: 真机 2026-10-30 10:06 的三角洲会话里, 「今日密码」是 canvas 里的一个
    小弹窗, 它自己的关闭控件在弹窗内部; 而小程序**页面标题栏右上角是「分享 / 更多」**。模型把
    (906,205) 当成关闭点了 —— 直接把分享面板点开, 之后 6 轮都在关分享、找返回。
    所以这里不猜坐标, 也不让模型猜:
      1. 全屏 OCR 只认「关闭窗口/关闭/取消/我知道了/×」这类按钮文字(长句不算);
      2. 有 bbox(最近一次画面变化的范围)时, 只在这块范围里选, 并按"离弹层右上角多近"排序;
         没有 bbox 时, 标题带(y < 10% 屏高)一律不碰, 那是分享/更多;
      3. 点一个核验一个: 画面变化 >= 20% **且** expect_text(这一层的关键字, 例如「今日密码」)
         已经从屏上消失, 才算关掉; 最多试 tries 个。
    真机 15:11:34 的教训: 弹窗里「航天基地」卡片的位置正好落在弹层 bbox 的右上方, 旧实现
    把它当图标叉点了下去(进了航天基地详情), 又因为卡片轮播抖了 10% 被当成关闭成功。
    返回 {ok, via: 'button'|'system', text, point, diff, tried, hint}。
    """
    if not verify:
        tries = 1
    if allow_back is None:
        # 给了 bbox 就说明"这是弹层", 不是整页: 弹层关不掉时按系统返回, 在自绘小程序里
        # 等于把整个小程序退掉 —— 真机 15:30:02 close 的兜底 back 直接把画面送回了桌面,
        # 模型下一句还按着"弹窗开着"的记忆继续点。所以只有没有 bbox 时才允许按系统返回。
        allow_back = not bbox
    img = shot()
    H, W = img.shape[:2]
    box = None
    if bbox:
        try:
            x1, y1, x2, y2 = [int(v) for v in list(bbox)[:4]]
            box = (x1, y1, x2, y2)
        except Exception:
            box = None
    cands = []
    try:
        for bx, text, score in ocr(img) or []:
            t = str(text or "").strip()
            if not t or len(t) > 10:
                continue                       # 长句是正文/说明, 不是按钮
            if not _is_close_text(t):
                continue
            xs = [p[0] for p in bx]
            ys = [p[1] for p in bx]
            cx, cy = int((min(xs) + max(xs)) / 2), int((min(ys) + max(ys)) / 2)
            if box:
                if not (box[0] - 20 <= cx <= box[2] + 20 and box[1] - 20 <= cy <= box[3] + 20):
                    continue                   # 弹层之外的「取消/关闭」不是这一层的
                rank = (0, -cx, cy)            # 弹层里靠右上角的先试
            else:
                if cy < H * 0.10:
                    continue                   # 标题带: 那是分享/更多, 不是页内按钮
                rank = (0 if cy < H * 0.35 else 1, cy, cx)
            cands.append((rank, cx, cy, t))
    except Exception:
        cands = []
    cands.sort(key=lambda c: c[0])
    tried = []
    for _, x, y, t in cands[:max(1, int(tries))]:
        try:
            r = tap(x, y, verify=verify, wait=wait)
        except Exception:
            break
        pct = _pct_from_diff(r.get("diff"))
        tried.append({"text": t, "point": [x, y], "diff": r.get("diff")})
        if verify and _closed_ok(pct, expect_text):
            return {"ok": True, "via": "button", "text": t, "point": [x, y],
                    "diff": r.get("diff"), "tried": tried}
    if box:
        # 图标型关闭控件: canvas 弹窗里的叉是画出来的, OCR 读不到文字 —— 真机 2026-10-30
        # 10:51:34 那次 action=close 返回 ok:false 正是这个原因(模型随后只好去猜标题栏角落,
        # 又点开分享面板)。这里只认"弹层范围右上方的图标框", 标题带(y<10%)依旧不碰。
        try:
            roi = (box[0] * 1000.0 / W, box[1] * 1000.0 / H,
                   box[2] * 1000.0 / W, box[3] * 1000.0 / H)
            icons = []
            for it in (look(roi=roi) or []):
                ix, iy = int(it["x"]), int(it["y"])
                if iy < H * 0.10:
                    continue
                if ix < box[0] + (box[2] - box[0]) * 0.55:
                    continue
                if iy > box[1] + (box[3] - box[1]) * 0.45:
                    continue
                _lab = str(it.get("label") or "")
                if not _close_icon_ok(_lab):
                    continue          # 弹窗正文/卡片名(如「航天基地」)不是叉, 别再点进详情
                icons.append((iy, ix, _lab))
            icons.sort()
            for iy, ix, lab in icons[:max(1, int(tries)) - len(tried)]:
                try:
                    r2 = tap(ix, iy, verify=verify, wait=wait)
                except Exception:
                    break
                pct2 = _pct_from_diff(r2.get("diff"))
                tried.append({"text": lab or "icon", "point": [ix, iy],
                              "diff": r2.get("diff"), "via": "icon"})
                if verify and _closed_ok(pct2, expect_text):
                    return {"ok": True, "via": "icon", "text": lab or "icon",
                            "point": [ix, iy], "diff": r2.get("diff"), "tried": tried}
        except Exception:
            pass
    if not allow_back:
        return {"ok": False, "via": "none", "diff": None, "tried": tried,
                "still_there": bool(expect_text and _text_on_screen(expect_text)),
                "hint": ("这一层没认出可点的关闭控件, 也没有替你按系统返回(在小程序/canvas 上按"
                         "返回会把整个小程序退掉)。改用 target=<弹层上的文字> 操作它, "
                         "或动作 exit_miniapp 离开整个小程序。")}
    r = back()
    pct = _pct_from_diff(r.get("diff"))
    return {"ok": bool(pct is not None and _closed_ok(pct, expect_text)), "via": "system",
            "diff": r.get("diff"), "tried": tried,
            "still_there": bool(expect_text and _text_on_screen(expect_text)),
            "hint": ("屏上没有认出「关闭窗口/取消/×」这类按钮, 系统返回也没关掉: 这一层可能要"
                     "先用 target=<弹层上的文字> 操作, 或者它根本不是弹层")}


def back():
    r = _act(op="back")
    _trace("back")
    return r
def home():
    r = _act(op="home")
    _trace("home")
    return r
def install_apk(path): return _act(op="install_apk", path=str(path))   # 装任意APK(APK工厂产物): 拉起系统安装器, 用户确认装机
def notifications(): return _act(op="notifications")    # 下拉通知栏(AOSP 语义全局动作)
def dismiss_shade(): return _act(op="dismiss_shade")    # 确定性收起通知栏/快捷设置(API31+ 全局动作; 低版本退化为 back)。用快捷设置(调亮度/开关)后必调:
                                                        # Pixel/Android16 上 home() 后面板会残留成透明层——ping().pkg 停在 com.android.systemui、dump 只剩状态栏、tap 全部无响应(diff 0%)
def quick_settings(): return _act(op="quicksettings")   # 展开快捷设置(AOSP 语义全局动作; 部分 OEM 只到通知栏够不到控制中心→改用 panel)
def panel(side="right"): return _act(op="panel", side=side)   # 物理下拉顶部面板: right=控制中心(录屏/手电/WiFi 磁贴)/left|center=通知栏(从屏幕最顶端下滑, 不受安全带夹制; 全局动作够不到控制中心时用它)


_BLACK_FRAME_GUARD = True          # FLAG_SECURE 窗口下 a11y takeScreenshot 不报错而返回纯黑位图 → 本漏斗把静默黑帧转为显式报错
_black_streak = {"pkg": "", "n": 0}

def _black_check(img):
    """同一前台包连续 2 帧纯黑(mean<8 且 std<6 且黑像素>97%) → 判防截屏窗口, 抛显式错误+降级指引
    (仿登录浏览器 secureForeground 先例)。单帧黑=视频黑场/过场, 不触发; 非黑即清零。"""
    g = img.mean(axis=2) if img.ndim == 3 else img
    if not (g.mean() < 8 and g.std() < 6 and (g < 16).mean() > 0.97):
        _black_streak["n"] = 0
        return
    pkg = _resolve_fg(_fg())
    if pkg != _black_streak["pkg"]:
        _black_streak["pkg"], _black_streak["n"] = pkg, 1
        return
    _black_streak["n"] = min(_black_streak["n"] + 1, 2)   # 达 2 后粘滞: 同窗口每帧黑都 raise, 防「报错/黑图」隔帧交替打穿漏斗; 只有非黑帧清零
    if _black_streak["n"] < 2:
        return
    _track("droid_shot_black", {"pkg_class": "unresolved" if not pkg else ("sensitive" if _sensitive_fg(pkg) else "normal")})
    hint = ("前台未解析(ping 抖动): 先 droid.ping() 认清前台包名, 再按其策略选降级路径。" if not pkg
            else "该 App 在 SENSITIVE_APPS 风控册内, a11y 树亦不可用: 引导用户手动完成此步。" if _sensitive_fg(pkg)
            else "该 App 的 a11y 树可用: 改用 droid.dump() 节点 bounds 导航(无视觉复核, 关键步骤先向用户确认)。")
    raise RuntimeError("前台 %s 窗口疑似 FLAG_SECURE 防截屏: 截图恒为纯黑, 视觉导航(shot/ui_detect/ocr)必失效, "
                       "勿再重截。%s" % (pkg or "(未解析)", hint))

def shot(path=None, q=None):
    """截屏。path给出→写文件返回path(默认PNG, q=1~100则JPEG); 否则返回BGR ndarray。
    画面只描述被操作的 App: GA 自身悬浮窗区域已按邻近像素抹平(物理屏上仍可见), 其状态文字不会污染 OCR/ui_detect。
    前台为防截屏窗口时(连续黑帧)抛 RuntimeError 而非返回黑图, 错误信息含降级路径。"""
    params = {"q": q} if q else {}
    try:
        data = _get("/a11y/shot", **params)
    except RuntimeError as exc:
        if str(exc).removeprefix("java.lang.RuntimeException: ") != "takeScreenshot failed code=3":
            raise
        # Android rejects rapid captures. Retry this read once, never reuse an old frame.
        time.sleep(.35)
        data = _get("/a11y/shot", **params)
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if _BLACK_FRAME_GUARD and img is not None:
        _black_check(img)
    if path:
        open(path, "wb").write(data)
        return path
    return img.view(_shot_img_cls())


_ShotImg = None                  # 惰性创建(见 _shot_img_cls): droid 不设模块级 import,
                                 # 这样 PC 侧没装 numpy/cv2 也能 import 本模块


def _shot_img_cls():
    """BGR 截屏的 ndarray 子类(首次调用时创建并缓存)。

    为什么用子类而不碰数据: 只要把 print()/repr() 从一串数字换成能指导下一步的提示,
    模型就不会再花一整轮去 print(shot()) 试探返回类型——真机实证它正是这么浪费的
    (回合小结原句: "droid.shot() 返回 numpy 数组。改用 numpy …")。phone_use.md §1
    也早就写明"print(shot()) 只会输出数字", 但模型照犯: 默认 repr 吐出一堆数字,
    看起来"像是有内容"。把回显变成提示, 这个浪费从源头消失, 不依赖模型记住规矩。

    只改显示, 不改数据: isinstance(x, np.ndarray) 仍为 True, cv2/numpy 运算、
    切片、dtype/shape 全部原样, 下游无需适配。"""
    global _ShotImg
    if _ShotImg is None:
        import numpy as np

        class _Shot(np.ndarray):
            def __repr__(self):
                if self.ndim >= 2:
                    h, w = int(self.shape[0]), int(self.shape[1])
                    ch = int(self.shape[2]) if self.ndim > 2 else 1
                else:
                    h = w = ch = 0
                return ('<screenshot %dx%dx%s BGR ndarray — print() cannot show an image; '
                        'pass it to ask_vision(img, question), droid.ocr(img) or droid.look()>'
                        % (w, h, ch))

            __str__ = __repr__

        _ShotImg = _Shot
    return _ShotImg


# ---------------- onnxruntime shim: 把 ort 调用转发给 APK 总线 ----------------

class _NodeArg:
    def __init__(self, d):
        self.name, self.shape, self.type = d["name"], d["shape"], d["dtype"]


class _RemoteSession:
    """镜像 ort.InferenceSession 最小面: get_inputs/get_outputs/run"""

    def __init__(self, model_path, sess_options=None, providers=None, **kw):
        self._path = _remote_model_path(model_path)
        j = _check(_SESSION.get(_base() + "/onnx/info", params={"model": self._path}, timeout=120))
        self._inputs = [_NodeArg(d) for d in j["inputs"]]
        self._outputs = [_NodeArg(d) for d in j["outputs"]]

    def get_inputs(self): return self._inputs
    def get_outputs(self): return self._outputs

    def run(self, output_names, input_feed):
        import numpy as np
        metas, blobs = [], []
        for name, v in input_feed.items():
            v = np.ascontiguousarray(v)
            metas.append({"name": name, "dtype": str(v.dtype), "shape": list(v.shape)})
            blobs.append(v.tobytes())
        m = json.dumps({"inputs": metas}).encode()
        body = struct.pack("<I", len(m)) + m + b"".join(blobs)
        buf = _check(_SESSION.post(_base() + "/onnx/run", params={"model": self._path},
                                   data=body, timeout=300))
        (mlen,) = struct.unpack_from("<I", buf, 0)
        outs_meta = json.loads(buf[4:4 + mlen].decode())["outputs"]
        off, byname, outs = 4 + mlen, {}, []
        for o in outs_meta:
            n = int(np.prod(o["shape"])) if o["shape"] else 1
            a = np.frombuffer(buf, dtype=np.dtype(o["dtype"]), count=n, offset=off).reshape(o["shape"])
            off += a.nbytes
            outs.append(a)
            byname[o["name"]] = a
        return [byname[n] for n in output_names] if output_names else outs


class _SessOptions:
    pass


def ort_shim():
    """注册假 onnxruntime 模块(转发到总线)。在 import 任何用 ort 的管线前调用。"""
    import types
    cur = sys.modules.get("onnxruntime")
    if cur is not None and getattr(cur, "_droid_shim", False):
        return
    ort = types.ModuleType("onnxruntime")
    ort._droid_shim = True
    ort.InferenceSession = _RemoteSession
    ort.SessionOptions = _SessOptions
    ort.get_available_providers = lambda: ["CPUExecutionProvider"]
    sys.modules["onnxruntime"] = ort


def _bundle():
    ort_shim()
    if BUNDLE not in sys.path:
        sys.path.insert(0, BUNDLE)


def ui_detect(img, conf=0.25):
    """img: BGR ndarray 或 路径 → [{'bbox':[x1,y1,x2,y2],'type':'icon'|'text','label','cls','confidence'}]
    检测器=Android专调YOLOv8n(21类语义)+PP-OCR空间匹配。cls给出控件语义(即便纯图标无文字),
    label=框内OCR文字; 无文字时图标/控件回退为cls语义名, 文字类回退None。

    是否跑 YOLO 由 observe() 按画面类型决定(_classify), 这里不再收 yolo 形参。
    YOLO 缺失/损坏时自动降级为只跑 OCR 并把原因记进 ui_detect_lite.LAST_YOLO_ERROR, 不外抛。
    YOLO 框太密(>OCR_MAX_BOXES)时跳过 OCR 并把原因记进 LAST_SKIP_REASON —— 那种画面不是
    控件页, 见 detect() 的 docstring。"""
    _bundle()
    import ui_detect_lite
    return ui_detect_lite.detect(img, conf=conf, ocr_max_boxes=ui_detect_lite.OCR_MAX_BOXES)


_ppocr = None


def _ocr_engine():
    global _ppocr
    _bundle()
    if _ppocr is None:
        from ppocr_engine import PPOCR
        _ppocr = PPOCR()
    return _ppocr


def _check_bgr(img, who):
    """入口类型自解释: 收窄到"看得出来的错", 不猜。

    真机实证: 模型写 `img = droid.shot(); crop = img.crop((0,150,1200,800));
    droid.ocr(crop)` —— crop 是 **PIL Image**(shot() 返回的是 ndarray, 没有 .crop),
    于是整轮抛异常; 下一轮才改成 numpy 切片。这类错误原本只会透出底层一句难懂的
    TypeError/AttributeError, 模型要自己试一轮才知道。这里把"该传什么、手上有的是
    什么、怎么改"一次说清。"""
    import numpy as np
    if isinstance(img, np.ndarray):
        return img
    kind = type(img).__name__
    hint = ''
    if kind == 'Image' or hasattr(img, 'crop') and not isinstance(img, np.ndarray):
        hint = ('; got a PIL Image — droid.shot() returns a numpy BGR ndarray, '
                'not a PIL Image: slice with img[y1:y2, x1:x2] instead of img.crop(...)')
    elif isinstance(img, str):
        hint = ('; got a path string — pass the image itself (droid.shot()), '
                'ocr()/ocr_text() do not read files')
    raise TypeError('%s needs a BGR ndarray (droid.shot() or a numpy slice of it), got %s%s'
                    % (who, kind, hint))


def ocr(img):
    """img: BGR ndarray → [(box 4x2 int, text, score), ...]"""
    _check_bgr(img, 'ocr()')          # 先检查: _ocr_engine() 内部会 _bundle() 摸设备,
    return _ocr_engine()(img)         # 写成 _ocr_engine()(_check_bgr(..)) 会先建引擎再检查


def ocr_text(img):
    """img: cropped BGR ndarray → (text, score), without text detection."""
    _check_bgr(img, 'ocr_text()')
    return _ocr_engine().recognize(img)


# ---------------- app 内自连无线 ADB (类 LADB, 纯 Kotlin libadb, 补 A11y 外 shell) ----------------
# 用户须先手动: 开发者选项 → 无线调试 → 打开。app 不能静默开, 全程手动授权。
# 配对只需一次(证书持久化, 6位码+配对端口来自系统弹窗); 之后 adb_connect() 无参即可(连接端口自动发现,
# 每次开关无线调试端口会变但无需手填)。本机 host 恒 127.0.0.1。

def adb_pair(code, port, host="127.0.0.1"):
    """SPAKE2 配对。code=「使用配对码配对设备」弹窗的6位码, port=该弹窗 IP:后的配对端口。
    ⚠️配对期间那个系统弹窗必须保持前台, 关掉即作废配对信息。成功后证书持久化, 后续不用再 pair。"""
    return _check(_SESSION.post(_base() + "/adb/pair",
                                json={"host": host, "port": int(port), "code": str(code)}, timeout=60))

def adb_connect(port=None, host="127.0.0.1"):
    """建立 ADB-over-TLS 传输。**无参即可**: 自动发现端口(复用上次成功端口 → 5555 → mDNS 通告的连接端口),
    故不用再手填/OCR「无线调试主页」那个每次都变的端口。仅当自动发现失败时才显式传 port。
    之后 adb_shell 断线会自愈重连, 一般不用手动重连。"""
    run_guard.check()   # 僵尸线程护栏: 已取消则不再改设备连接状态
    return _check(_SESSION.post(_base() + "/adb/connect",
                                json={"host": host, "port": int(port) if port else 0}, timeout=60))

def adb_shell(cmd, timeout_ms=30000, max_bytes=262144):
    """跑一条非交互 shell 命令, 收全部输出返回其 stdout(str)。未连接/断线会**自动重连**(先 adb_connect 一次更快)。
    补 A11y 够不到的能力: input tap/text, am start, pm list, dumpsys, wm size, screencap 等。
    ⚠️timeout_ms 必须 > 0(无 '0=无限' 语义); 勿传长驻命令(top / logcat -f / 无 -c 的持续输出) — 会超时, 用 adb_shell_detached。
    ⚠️别用 `| head`/`| head -n`(提前关管道, 命令端无 EOF 会拖到超时) — 要截断用 `head -c N` 或 `sed -n '1,Np'` 或重定向落文件后分段读。
    输出超 max_bytes(默认256KB)会**报错**(不静默截断, 防损坏), 按提示分页; 读大二进制(如截图 base64)显式调大 max_bytes。"""
    run_guard.check()   # adb input tap/swipe 也能驱动手机 → 僵尸线程护栏检查点: 已取消则抛 RunCancelled 自毁
    # shell 注入(input tap/swipe/text/keyevent, sendevent, monkey)对锁定 App 同样过零注入门禁: 这是 a11y 门禁最直接的绕道
    # (deviceId=-1 的 input 事件同样可辨), 前台是微信时一律拒, 不看命令是否"只是查看"——input/sendevent/monkey 本身就是注入。
    if re.match(r"\s*(input|sendevent|monkey)\b", str(cmd)):
        _gate_injection("adb_shell:" + str(cmd).split()[0])
    _record_path("adb")   # 任务路径归属: 无线 adb shell(只记类别, 不记命令内容)
    return _check(_SESSION.post(_base() + "/adb/shell",
                                json={"cmd": str(cmd), "timeout_ms": int(timeout_ms), "max_bytes": int(max_bytes)},
                                timeout=2 * timeout_ms / 1000 + 30))["out"]   # 覆盖 Kotlin 断线重连+重试的最坏时窗, 避免客户端先超时

def adb_shell_detached(tag, cmd):
    """起一条 held-stream 命令(流不关, 立即返回), 用于保活常驻子进程(如 VdHelper)。
    普通 adb_shell 读完 EOF 即关流, adbd 收割该 shell 的所有子进程(含 & 后台的); 唯有流保持开才存活。
    命令须自带 `1>_LOG 2>&1 3>&-`(重定向输出 + 切断 adbd 泄漏的 fd3 控制 socket, 否则常驻子进程持 fd3
    会令后续 adb_shell 读不到 EOF 超时)。回收: 因 3>&- 断 fd3, adb_shell_close 关流不收割进程, 须 kill pid。"""
    run_guard.check()   # 僵尸线程护栏: held-stream 会起常驻设备进程, 已取消则拒绝(防僵尸留后台驻留物)
    r = _SESSION.post(_base() + "/adb/shell_detached",
                      json={"tag": str(tag), "cmd": str(cmd)}, timeout=25)
    if r.status_code == 404:
        raise RuntimeError("GA APK 过旧: 无 /adb/shell_detached 端点, 请先升级 APK 再用虚拟屏"
                           "(部署顺序: APK 先于 python 资产热更新)")
    return _check(r)

def adb_shell_close(tag):
    """清该 tag 的 GA 侧 held 流引用(幂等)。注: 因 3>&- 断 fd3, 关流不 kill 进程, 真 kill 靠调用方 kill pid。
    旧 APK 无端点时返回 False。"""
    r = _SESSION.post(_base() + "/adb/shell_close", json={"tag": str(tag)}, timeout=25)
    return bool(_check(r).get("closed")) if r.status_code != 404 else False

def adb_status():
    """{connected:bool(libadb 派生真值,不再有假态), paired:bool(证书是否已持久化), error:上次错误, port:上次成功连接端口}"""
    return _get("/adb/status")


# ====== AppFunction 原子能力(Android16+ 的 cmd app_function 服务; 经 self-ADB shell 通道) ======
# EXECUTE_APP_FUNCTION 是 internal|role 权限: 第三方 App 直连被系统拒绝, shell(uid=2000)通道可用(实测结论)。
# 各 OS/ROM 注册的能力不同(商店/天气/相机/支付代理等), 本层只提供枚举+直调+JSON 解析, 不预设任何清单。

def _appfn_json(out, what):
    """cmd app_function 输出解析: 整体或首个 JSON 体(dict/list)原样返回(前后可能混警告行);
    解析不出则带原始片段报错 —— 解析失败与"空能力清单"必须可区分, 绝不伪造成空结果。"""
    text = str(out or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if m:
            try: return json.loads(m.group(0))
            except ValueError: pass
    raise RuntimeError("app_function %s 返回不是 JSON(前 200 字符): %r; 以实际输出为准处理, 勿盲目重试" % (what, text[:200]))


def appfn_list(user=None):
    """列出本机注册的 AppFunction 原子能力。前置: Android 16+ 且 adb_connect() 已连接(未连会先报 ADB 状态错误)。
    user 可选: 用户编号或 'current', 默认不带。返回 JSON(dict/list), 各字段以本机实测为准。
    纪律: 枚举结果**经实测验证后**才可写入记忆(start_long_term_update), 并注明该能力替代不了什么(如商店搜索替代不了 GUI 浏览比较)。"""
    cmd = "cmd app_function list-app-functions"
    if user is not None:
        u = str(user)
        if not re.fullmatch(r"[0-9]+|current", u):
            raise ValueError("appfn_list(user=): 只接受用户编号或 'current', 收到 %r" % u)
        cmd += " --user " + u
    return _appfn_json(adb_shell(cmd, timeout_ms=15000), "list-app-functions")


def appfn_call(package, function, parameters=None):
    """调用一个 AppFunction 原子能力。package=注册方完整包名; function=完整函数 ID '类全名#方法名'(# 在 shell 里是注释符, 已整体单引号包裹);
    parameters=dict, 序列化为 JSON(中文转 \\uXXXX 转义, 纯 ASCII 过 shell 通道, 不依赖编码协商)。
    例: droid.appfn_call('com.example.store', 'com.example.fn.StoreFunctions#searchApp', {'keyword': '日历'})
    返回 JSON; 失败(未连接/函数不存在/参数被拒)按原错误抛出, **不自动重试同一调用**。
    命中注册能力时优先本调用而非 GUI(零轮次/无坐标漂移); 未注册的 App 回正常定位阶梯, 不反复尝试。"""
    package, function = str(package), str(function)
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+", package):
        raise ValueError("appfn_call: package 须为完整包名(至少一段点分), 收到 %r" % package)
    if not re.fullmatch(r"[A-Za-z0-9_.$]+#[A-Za-z0-9_]+", function):
        raise ValueError("appfn_call: function 须为 '类全名#方法名'(含 #), 收到 %r" % function)
    if parameters is None: parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("appfn_call: parameters 须为 dict(JSON 对象), 收到 %s" % type(parameters).__name__)
    payload = json.dumps(parameters)   # ensure_ascii 默认 True: 中文转 \uXXXX, 纯 ASCII 过 shell 最稳
    shell_arg = lambda s: "'" + str(s).replace("'", "'\\''") + "'"   # POSIX 单引号安全包裹: JSON 双引号原样保留, 内嵌单引号转义
    cmd = "cmd app_function execute-app-function --package %s --function %s --parameters %s" % (
        shell_arg(package), shell_arg(function), shell_arg(payload))
    return _appfn_json(adb_shell(cmd, timeout_ms=30000), "execute-app-function")


# ====== 通知读取/回复/控制 ======
# 用户须先手动: 设置 → 通知 → 通知使用权限 → Generic Agent → 允许。
# 否则 is_notification_service_enabled() 返回 False, 其他函数返回空/错误。

def get_notifications():
    """获取当前所有系统通知列表。
    返回: [{"key": "0|com.tencent.mm|...", "pkg": "com.tencent.mm", "title": "...", 
            "text": "...", "time": 1234567890, "canReply": true}, ...]
    未授权通知监听权限时抛 RuntimeError(含授权路径提示), 先用 is_notification_service_enabled() 探测。"""
    return _get("/notifications")

def reply_notification(key, text):
    """回复通知 (仅对支持 RemoteInput 的通知有效，如微信/Telegram 等)。
    Args:
        key: 通知唯一标识 (从 get_notifications 返回的 "key" 字段, 形如 "0|com.tencent.mm|…", 第二段=包名)
        text: 回复内容
    Returns: 成功返回 "ok", 失败返回 "err:..."
    敏感 App(SENSITIVE_APPS act="locked", 如微信)的通知回复走同一道零注入门禁: 未 sensitive_unlock 直接抛错——
    通知栏直回等于替用户发消息, 与 a11y paste+发送是同一风控面(甚至更显眼: 非前台就在发), 不能成为绕门禁的旁路。"""
    run_guard.check()   # 回复通知属操作外界 → 僵尸线程护栏检查点
    parts = str(key).split("|")
    _gate_injection("reply_notification", pkg=parts[1] if len(parts) > 1 else "")
    resp = _check(_SESSION.post(_base() + "/notifications/reply",
                                json={"key": str(key), "text": str(text)}, timeout=30))
    if isinstance(resp, dict):
        return resp.get("ok", "err:bad_response")
    return resp

def dismiss_notification(key):
    """取消/清除单个通知。
    Args:
        key: 通知唯一标识
    Returns: 成功返回 "ok", 失败返回 "err:..."
    """
    run_guard.check()
    resp = _check(_SESSION.post(_base() + "/notifications/dismiss",
                                json={"key": str(key)}, timeout=30))
    if isinstance(resp, dict):
        return resp.get("ok", "err:bad_response")
    return resp

def dismiss_notifications_by_package(pkg):
    """清除指定应用的所有通知。
    Args:
        pkg: 应用包名 (如 "com.tencent.mm")
    Returns: 清除数量 (int)
    """
    run_guard.check()
    resp = _check(_SESSION.post(_base() + "/notifications/dismiss_pkg",
                                json={"pkg": str(pkg)}, timeout=30))
    # 返回可能是 {"count": N} 或直接字符串 "N"
    if isinstance(resp, dict):
        return resp.get("count", 0)
    return int(resp) if str(resp).isdigit() else 0

def is_notification_service_enabled():
    """检查通知监听服务是否已授权并连接。
    Returns: True/False
    """
    resp = _get("/notifications/status")
    # 返回可能是 {"enabled": true} 或直接字符串 "true"/"false"
    if isinstance(resp, dict):
        return bool(resp.get("enabled", False))
    return str(resp).lower() == "true"


def _notif_trigger_contract(resp):
    """Require the fixed native-trigger lifecycle response shape."""
    if not isinstance(resp, dict):
        raise RuntimeError("invalid native notification-trigger response")
    required = {"ok", "running", "listener_enabled", "rule_count", "error"}
    missing = required.difference(resp)
    if missing:
        raise RuntimeError("invalid native notification-trigger response: missing " + ", ".join(sorted(missing)))
    if not isinstance(resp["ok"], bool) or not isinstance(resp["running"], bool):
        raise RuntimeError("invalid native notification-trigger response: bad lifecycle flags")
    if (not isinstance(resp["listener_enabled"], bool)
            or not isinstance(resp["rule_count"], int)
            or isinstance(resp["rule_count"], bool)):
        raise RuntimeError("invalid native notification-trigger response: bad listener state")
    if not isinstance(resp["error"], str):
        raise RuntimeError("invalid native notification-trigger response: bad error")
    return resp


def _notif_trigger_rules_contract(resp):
    """Require lifecycle state plus the complete canonical stored rule list."""
    result = _notif_trigger_contract(resp)
    rules = result.get("rules")
    if not isinstance(rules, list) or len(rules) != result["rule_count"]:
        raise RuntimeError("invalid native notification-trigger response: bad rules")
    fields = {"id", "pkg", "keywords", "task", "enabled", "cooldown_ms"}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != fields:
            raise RuntimeError(
                "invalid native notification-trigger response: bad rule %d" % index)
        cooldown = rule["cooldown_ms"]
        if (not isinstance(rule["id"], str)
                or not isinstance(rule["pkg"], str)
                or not isinstance(rule["task"], str)
                or not isinstance(rule["enabled"], bool)
                or not isinstance(rule["keywords"], list)
                or any(not isinstance(keyword, str) for keyword in rule["keywords"])
                or not isinstance(cooldown, int)
                or isinstance(cooldown, bool)
                or cooldown < 0):
            raise RuntimeError(
                "invalid native notification-trigger response: bad rule %d" % index)
    return result


def _notif_trigger_response(response):
    try:
        result = _notif_trigger_contract(response.json())
    except ValueError as e:
        raise RuntimeError("invalid native notification-trigger response") from e
    return result


def _notif_trigger_request(response):
    result = _notif_trigger_response(response)
    if not result["ok"]:
        raise RuntimeError(result["error"] or "native notification trigger request failed")
    return result


def _notif_trigger_rules_request(response):
    try:
        result = _notif_trigger_rules_contract(response.json())
    except ValueError as e:
        raise RuntimeError("invalid native notification-trigger response") from e
    if not result["ok"]:
        raise RuntimeError(result["error"] or "native notification trigger request failed")
    return result


def notif_trigger_start(rules):
    """Persist and enable native notification-trigger rules.

    ``rules`` is a JSON list validated by Android. Rule notification fields are
    selectors only; each rule's fixed ``task`` is the sole task payload. A
    disconnected notification listener raises RuntimeError with the Android
    permission path instead of silently enabling a non-working trigger.

    Returns the fixed lifecycle object:
    ``{ok, running, listener_enabled, rule_count, error}``.
    """
    run_guard.check()
    return _notif_trigger_request(_SESSION.post(
        _base() + "/notif-trigger/start", json={"rules": rules}, timeout=30))


def notif_trigger_status():
    """Return ``{ok, running, listener_enabled, rule_count, error}``.

    Status remains readable when notification-listener permission is absent;
    ``listener_enabled`` and ``error`` make that state explicit.
    """
    return _notif_trigger_response(_SESSION.get(
        _base() + "/notif-trigger/status", timeout=60))


def notif_trigger_rules_get():
    """Return lifecycle state plus the complete persisted native rule list."""
    return _notif_trigger_rules_request(_SESSION.get(
        _base() + "/notif-trigger/rules", timeout=60))


def notif_trigger_rules_add(rule):
    """Validate and append one rule, returning the complete resulting list."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/add", json={"rule": rule}, timeout=30))


def notif_trigger_rule_set_enabled(id, enabled):
    """Enable or disable one stored rule without replacing the other rules."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/set-enabled",
        json={"id": id, "enabled": enabled}, timeout=30))


def notif_trigger_rule_delete(id):
    """Delete one stored rule and cancel only that rule's pending work."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/delete", json={"id": id}, timeout=30))


def notif_trigger_stop():
    """Disable native notification-trigger rules and cancel only its queued work.

    This is idempotent and returns ``{ok, running, listener_enabled,
    rule_count, error}``; it does not require a currently connected listener.
    """
    run_guard.check()
    return _notif_trigger_request(_SESSION.post(
        _base() + "/notif-trigger/stop", timeout=30))


def alarm_set(id, at, every=0, prompt=""):
    """注册到点唤起 agent 的任务(非系统起床铃)。id 唯一键(同 id 再 set=改期);
    at=下次 epoch ms; every=0 一次, >0 周期 ms; prompt=到期后台新会话指令(call_once)。
    用户要「几点叫我/设闹钟」请开系统时钟 App, 勿用本函数。
    返回 True/False。进程被杀仍可唤醒; 前台任务 running 时当次可能 busy 跳过。"""
    resp = _check(_SESSION.post(_base() + "/alarm/set",
                                json={"id": str(id), "at": int(at),
                                      "every": int(every), "prompt": str(prompt)},
                                timeout=30))
    return bool(resp.get("ok", 0)) if isinstance(resp, dict) else True

def alarm_del(id):
    """删除闹钟 id; 不存在也返回 True。"""
    resp = _check(_SESSION.post(_base() + "/alarm/del",
                                json={"id": str(id)}, timeout=30))
    return bool(resp.get("ok", 0)) if isinstance(resp, dict) else True

def alarm_list():
    """列出已注册闹钟: [{id, at, every, prompt}, ...]。"""
    resp = _get("/alarm/list")
    if isinstance(resp, dict):
        return resp.get("alarms", [])
    return resp or []


# ---------------- L1 recipe: 录制与回放入口（SPEC Phase 1） ----------------

def _recipe_store():
    import recipe
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "recipes")
    return recipe.RecipeStore(root)


def recipe_list():
    """可用配方清单(agent 开局发现用): [{recipe_id, app, package, scene, steps, fragile}]。unstable 不列出。"""
    store = _recipe_store()
    out = []
    # 内置入口配方先入列: 仓库里 memory/recipes/ 目录整个不存在, 只靠落盘配方时 recipe_list()
    # 恒空, 而 phone_use.md 早就让模型"去调它" —— 于是模型从来没拿到过任何配方。
    for _pkg, _e in sorted(APP_ENTRY.items()):
        out.append({"recipe_id": "app_search:" + _pkg, "app": _e.get("label", ""),
                    "package": _pkg, "scene": "app_search", "steps": 4, "fragile": False,
                    "builtin": True, "via": "gui_act action=search_app value=<关键词>"})
    try:
        _stored = store.list()
    except Exception:            # 目录缺失/损坏: 内置入口仍然可用, 不让"发现入口"整体失效
        _stored = []
    for r in _stored:
        if store.is_unstable(r.recipe_id):
            continue
        ah = r.app_hint or {}
        out.append({"recipe_id": r.recipe_id, "app": str(ah.get("value") or ""),
                    "package": str(ah.get("package") or ""), "scene": r.scene,
                    "steps": len(r.steps), "fragile": bool(r.fragile)})
    return out


def recipe_record(hint=None):
    """把本次任务的 operation trace 机械转成配方并落盘。零模型调用、可离线复现。"""
    import recipe
    r = recipe.trace_to_recipe(list(_TRACE), hint or {})
    _recipe_store().save(r)
    return r


def _norm_action_result(ret):
    """tap/swipe 的返回(diff 字符串/fg)归一成期望判定用的 {diff_pct, pkg}。
    真机实证的坑: tap() 返回的 diff 是 'diff: 43.5% bbox=...' 字符串、前台字段叫 fg,
    不归一会让期望判定永远读不到 diff_pct → 误升级 uncertain。"""
    out = {}
    d = ret.get("diff")
    if isinstance(d, str):
        try:
            out["diff_pct"] = float(d.split("%", 1)[0].split()[-1])
        except Exception:
            pass
    elif isinstance(ret.get("diff_pct"), (int, float)):
        out["diff_pct"] = ret["diff_pct"]
    if ret.get("fg"):
        out["pkg"] = ret["fg"]
    return out


def recipe_run(hint=None):
    """按提示回放配方(零模型调用)。无匹配/已 unstable 返回 None; 升级返回 ReplayResult 交上层走 L4。"""
    import recipe
    store = _recipe_store()
    r = store.match(hint or {})
    if r is None:
        return None

    def observe():
        p = ping() or {}
        nodes = dump() or []
        dets = []
        if not nodes:                      # 树不可用才走视觉(慢): 常见 S1 路径只 dump
            try:
                dets = look(cache=True) or []
            except Exception:
                dets = []
        return {"nodes": nodes, "detections": dets,
                "screen": (p.get("w"), p.get("h")), "pkg": p.get("pkg")}

    def act(action, resolved):
        k = action.get("kind")
        if k == "tap" and resolved.get("point"):
            return _norm_action_result(tap(*resolved["point"]))
        if k == "swipe":
            d = action.get("direction") or "up"
            ret = scroll(d) if d in ("up", "down", "left", "right") else scroll("up")
            return {"diff_pct": 8.0 if ret.get("scrolled") else 0.0, "pkg": ret.get("pkg")}   # scroll 的判定即其既有 verdict
        if k == "paste":
            return paste(action.get("value") or "")
        if k == "launch":
            ret = launch(action.get("pkg") or "")
            return {"pkg": ret.get("fg") or action.get("pkg")}   # launch 的 fg 即前台证据
        if k in ("back", "home"):
            before = shot()                       # back/home 无自带后验: 用既有 diff 验证器补(不新造判定)
            back() if k == "back" else home()
            time.sleep(0.3)
            return {"diff_pct": float(_img_diff_str(before, shot()).split("%", 1)[0].split()[-1])}
        return {}

    res = recipe.replay(r, observe, act)
    if res.status == "escalated":
        store.record_escalation(r.recipe_id)   # 不变量 4: 单任务两次升级 → unstable
    return res
