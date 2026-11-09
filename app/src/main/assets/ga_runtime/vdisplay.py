# -*- coding: utf-8 -*-
"""vdisplay: 虚拟屏模式 —— 把 Agent 操作流转到离屏虚拟屏, 主屏不被打扰。
依赖任务1(本机自连无线 ADB): 先 droid.adb_connect(port) 建立传输, 否则下列函数经 droid.adb_shell 直接报错
"未连接: 先 connect()"(不在此模块重复兜底, let-it-crash, 失败半径小: 单次调用失败不改任何本地状态)。
用法:
    import vdisplay
    vid = vdisplay.vd_start('com.tencent.mm')   # 建离屏虚拟屏(若已存活则复用)+ 把目标 app 拉到该屏前台, 返回 display id
    vdisplay.vd_tap(500, 800); vdisplay.vd_swipe(200, 1500, 200, 500); vdisplay.vd_text('hi'); vdisplay.vd_key()
    img_path = vdisplay.vd_shot('/tmp/a.png')   # 截该虚拟屏最新帧(helper ImageReader 落盘)
    vdisplay.vd_status()                        # {'vid':id|None, 'alive':bool}
    vdisplay.vd_stop()                          # 关持有流=确定性 kill VdHelper, VirtualDisplay 随之销毁

会话生命周期(必守):
    开始: 先 vd_status(); alive=True 说明上一会话遗留了活屏(可能没 vd_stop, 屏上停在任意页面)——
          直接 vd_shot() 看清现状再决定复用/重启, 勿假设屏上是主页。
    结束: 任务完成默认 vd_stop(), 否则遗留屏会把下一会话的 app resume 到旧页面, 诱发多轮误诊。
    边界: helper 由 app 侧长持的 ADB 流(held-stream)保活; 因命令用 3>&- 切断 fd3 脐带, closeDetached 关流
          已实测收割不了它(故 kill 靠 pid, 见 vd_stop)。GA app 进程死后 adbd 对该 transport 的行为未实测,
          但屏或死或活两种结局代码都能收敛(pkill 清孤儿 + status/proc 复用门)。回收靠 status 文件 PID;
          进程被极端内存压力杀掉则屏消失, 下次 vd_start 幂等重建拿新 id。

输入与导航(该屏无 A11y/无剪贴板 paste 通道):
    vd_text 仅 ASCII 可靠(input text 不吃中文); 中文搜索/页内跳转优先 app scheme 深链:
    droid.adb_shell("am start --display <vid> -a android.intent.action.VIEW -d '<scheme>://…'")
    (如小红书 xhsdiscover://search/result?keyword=%E4%B8%AD%E6%96%87, URL 编码中文, 一发直达搜索结果)。
    直接 am start -n 非导出 Activity 必 SecurityException; 深链失效(app 改版)再退坐标 vd_tap。

截图备选(vd_shot 无帧/超时不要盲试):
    dumpsys SurfaceFlinger --display-id 列出物理 SF id(逻辑 displayId≠SF id) →
    screencap -d <SFid> /sdcard/xx.png 后直接读文件, 勿 base64 走文本 bus(大帧实测超时)。

边界: FLAG_SECURE 窗口(部分支付/密码页)截出黑屏; 少数 App/ROM 拒绝渲染到非默认 display(am start 后
被系统落回默认屏, vd_start 已内置检测+撤回报错, 此时降级前台模式并告知用户)。
"""
import base64
import os
import re
import shlex
import time

import droid

_PKG = os.environ.get("GA_PACKAGE", "io.github.shenhaostu.gagent")                    # GA 自身包名: VdHelper 类随 GA apk 分发
_LOG = "/data/local/tmp/ga_vd.log"     # helper 进程 stdout/stderr 重定向落点
_SHOT = "/data/local/tmp/ga_vd_shot.png"  # VdHelper 消费 ImageReader 落盘的最新虚拟屏帧(screencap -d 在部分ROM对虚拟屏无效)
_META = "/data/local/tmp/ga_vd_shot.meta"  # VdHelper 每落一帧原子写 SEQ/UPTIME_MS(帧到达, CLOCK_MONOTONIC)/PID/W/H: 帧新鲜度与归属的真相源
_STATUS = "/data/local/tmp/ga_vd.status"  # VdHelper 建屏后原子写 "DISPLAY_ID=<id>\nPID=<pid>": 进程真相源, 解耦易失 stdout 日志; Python 重启/日志截断后按 pid 反查既有屏做幂等复用, liveness 用 /proc/<pid>(消除 pgrep cmdline 自匹配)

_vid = None   # 模块级缓存: 当前虚拟屏 display id, 未启动为 None
_size = None  # 当前虚拟屏 (w, h): 坐标边界校验用(虚拟屏≠主屏尺寸, 沿用主屏截图坐标是常见误操作)
_last_input = 0.0  # 最近一次 vd 输入完成的 time.monotonic(); 与 helper 的 UPTIME_MS 同钟, 用来判截帧是否晚于动作
_pkg = None   # 本会话最后上屏的目标 pkg: 仅供 vd_stop 跳前台护栏用(引擎重启后为 None→护栏跳过, 主修靠 helper 的 DESTROY_CONTENT_ON_REMOVAL flag)


def _apk_path():
    out = droid.adb_shell("pm path " + _PKG)
    for line in out.splitlines():
        if line.startswith("package:"):
            return line[len("package:"):].strip()
    raise RuntimeError("pm path " + _PKG + " 无输出, GA 未安装或 ADB 未授权: " + out)


def _resolve_activity(pkg):
    out = droid.adb_shell("cmd package resolve-activity --brief " + pkg)
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith(pkg + "/"):
            return line
    raise RuntimeError("resolve-activity 解析不到 " + pkg + " 默认 Activity: " + out)


def _need_vid():
    """_vid 空时回退 status 文件接管遗留活屏: 新会话/引擎重启后可直接 vd_shot 看现状再决定, 不必先 vd_start 拉起 app。"""
    global _vid, _size
    if _vid is None:
        info = _status_info()
        if info.get("DISPLAY_ID") is not None and _alive(info.get("PID")):
            _vid = info["DISPLAY_ID"]
            _size = _size_of(info)
    if _vid is None:
        raise RuntimeError("虚拟屏未启动: 先 vd_start()")
    return _vid


def _parse_kv(text):
    """纯函数: "K=123\n..." → {K: int}; 只收整数值, 半写/缺失的键自然缺席。"""
    return {k: int(v) for k, v in re.findall(r"^([A-Z_]+)=(\d+)\s*$", text or "", re.M)}


def _size_of(info):
    return (info["W"], info["H"]) if info.get("W") and info.get("H") else None


def _status_info():
    return _parse_kv(droid.adb_shell("cat " + _STATUS + " 2>/dev/null"))


def _status():
    """读 status 文件 → (vid|None, pid|None); 缺失/半写返回 (None,None)。"""
    info = _status_info()
    return info.get("DISPLAY_ID"), info.get("PID")


def _check_point(x, y, size):
    """纯函数: 坐标必须落在虚拟屏内。虚拟屏默认 1080x1920, 与主屏(如 1080x2340)不同;
    越界注入不会报错而是静默打空/打到边缘控件, 故在发送前显式拒绝并给出屏幕尺寸。"""
    if size is None:
        return
    w, h = size
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError("坐标 (%d,%d) 超出虚拟屏 %dx%d: 请用 vd_shot 截图上的坐标, 不要沿用主屏坐标" % (x, y, w, h))


def _frame_ready(meta, pid, last_input, now, settle):
    """纯函数: 帧是否可交付。帧须来自当前 helper(PID 一致, 否则是上一会话残留文件);
    帧到达早于最近一次输入时, 在 settle 窗口内继续等(动作的画面还没落盘), 超窗则认为画面未变化(静止), 照常交付。"""
    if not meta.get("SEQ") or meta.get("PID") != pid:
        return False
    return meta.get("UPTIME_MS", 0) >= last_input * 1000 or now - last_input >= settle


def _mark_input(out):
    global _last_input
    _last_input = time.monotonic()
    return out


def _alive(pid):
    """校验 pid 存活**且确为 VdHelper**: 单查 /proc/pid/cmdline(不存在→空, 别的进程复用该 pid→cmdline 不含 VdHelper)。
    防 PID 复用误判——否则 vd_start 复用分支会复用一个已死屏的 vid, 后续 input -d/am 全打空。"""
    return bool(pid) and "VdHelper" in droid.adb_shell("cat /proc/" + str(pid) + "/cmdline 2>/dev/null")


def vd_start(pkg, activity=None, w=1080, h=1920, dpi=320, timeout=10.0):
    """建离屏虚拟屏(存活按 status 文件复用, 幂等)+把 pkg 拉到该屏。返回 display id。
    返回 id 仅表示已请求在该屏启动，须用 vd_shot() 确认目标界面；不推断主屏包名或强停应用。"""
    global _vid, _pkg, _size
    info = _status_info()
    vid, pid = info.get("DISPLAY_ID"), info.get("PID")
    if vid is not None and info.get("W") and _alive(pid):
        _vid = vid
        _size = _size_of(info)
    else:
        apk = _apk_path()
        droid.adb_shell("pkill -f '[c]om.ljq.ga.VdHelper' 2>/dev/null; rm -f " + " ".join((_STATUS, _LOG, _SHOT, _META)) + "; true")   # 清孤儿 + 陈旧 status/log(否则轮询首轮读到旧 DISPLAY_ID 或旧 ERR: 误判)
        # held-stream + 3>&-(真机定案): helper 前台跑, 流由 app 侧长持(adb_shell_detached, tag="vd")。
        # 为何必须 held(不 close): 普通 adb_shell 读完 EOF 即 stream.close(), adbd 收割该 shell 的所有子进程
        #   (含 `&` 后台的)——实测 `setsid ... &` 经普通 adb_shell 起的 helper 被 close 秒收割; 唯有流保持开才存活。
        # 为何必须 3>&-: adbd 的 shell v1 裸流有个泄漏的 fd3 控制 socket(缺 O_CLOEXEC), app_process 会继承;
        #   helper 保活持有它 → adbd 认为该 shell 会话未结束 → 后续经同 transport 的 adb_shell 读不到 EOF 超时
        #   (旧 held 版无 3>&- 时 vd_tap/shot 全瘫)。exec app_process 前关 fd3(ART 尚未 open 自己 socket, 精准)。
        # 只关 fd3: mksh 里 `4>&-` 关未打开的 fd 会使整条重定向失败。
        # 回收: 因 3>&- 断 fd3, adb_shell_close 关流不收割 helper(脐带已断), 故 vd_stop 靠 kill pid(见下)。
        droid.adb_shell_detached("vd",
            "CLASSPATH=" + apk + " app_process / com.ljq.ga.VdHelper "
            + str(int(w)) + " " + str(int(h)) + " " + str(int(dpi))
            + " 0</dev/null 1>" + _LOG + " 2>&1 3>&-")
        end = time.time() + timeout
        while time.time() < end:
            vid, pid = _status()
            if vid is not None and _alive(pid):
                break
            if "ERR:" in droid.adb_shell("cat " + _LOG + " 2>/dev/null"):
                break
            time.sleep(0.5)
        if vid is None or not _alive(pid):
            raise RuntimeError("VdHelper 起虚拟屏失败/超时: " + (droid.adb_shell("cat " + _LOG).strip() or "(无输出)"))
        _vid = vid
        _size = _size_of(_status_info()) or (int(w), int(h))

    target = activity or _resolve_activity(pkg)
    if "/" not in target:
        target = pkg + "/" + target
    try:   # 任务路径归属: 离屏虚拟屏(只记类别, 不记 pkg); 惰性 import + 全吞异常, PC 侧无 plugins 包不报错
        from plugins.analytics_hook import record_path
        record_path("vdisplay")
    except Exception:
        pass
    _mark_input(droid.adb_shell("am start --display " + str(_vid) + " -n " + target))
    _pkg = pkg
    return _vid


_SHOT_EXT = "/sdcard/Android/data/" + _PKG + "/files/ga_vd_shot.png"  # app 自有外部目录: shell 可写, app 免权限直读


def _copy_frame():
    """一次 round trip 取 (meta, 帧字节)。meta 与 cp 同一条 shell: helper 先 rename PNG 再写 meta, 故 meta 不会领先于帧。
    主通道=cp 到 app 外部目录后直读(1MB+ 大帧 base64 走文本 bus 实测超时); rm 先清残留 + && echo 显式确认,
    否则 cp 失败时 adb_shell 只回错误文本不抛错, 会 open 到上一次的旧帧。base64 仅作回退。"""
    out = droid.adb_shell("cat %s 2>/dev/null; rm -f %s; cp %s %s && echo GA_CP_OK" % (_META, _SHOT_EXT, _SHOT, _SHOT_EXT))
    meta = _parse_kv(out)
    if "GA_CP_OK" in out:
        try:
            with open(_SHOT_EXT, "rb") as f:
                return meta, f.read()
        except OSError:
            pass
    # 截图 base64 常达 1-4MB, 远超 adb_shell 默认 256KB 上限(超限会报错防帧损坏), 故显式放开 max_bytes 到 16MB
    b64 = droid.adb_shell("base64 " + _SHOT, max_bytes=16 * 1024 * 1024)
    return meta, (base64.b64decode("".join(b64.split())) if b64.strip() else b"")


def vd_shot(path, wait=0.6, settle=1.5):
    """读 VdHelper 落盘的最新虚拟屏帧存到本地 path(screencap -d 对虚拟屏在部分 ROM 无效, 故 helper 消费 ImageReader 落 PNG)。
    helper 尾沿节流(≤400ms 内必落最新帧), 先等 wait 秒; 再按 meta 校验: 帧须属当前 helper(防读到上一会话残留/已死 helper 的旧帧),
    且晚于最近一次 vd 输入(否则在 settle 内重读; 超窗=动作未引起画面变化, 照常交付当前帧)。"""
    _need_vid()
    _, pid = _status()
    if not _alive(pid):
        raise RuntimeError("虚拟屏 helper 已退出(屏已销毁): 旧帧不代表当前画面, 先 vd_status()/vd_start() 重建")
    time.sleep(wait)
    while True:
        meta, data = _copy_frame()
        if not data or _frame_ready(meta, pid, _last_input, time.monotonic(), settle):
            break
        if meta.get("PID") != pid:
            raise RuntimeError("虚拟屏暂无属于当前 helper 的帧(可能是上一会话残留): 先做一次操作(vd_tap/vd_key)或稍候重试")
        time.sleep(0.2)
    if not data:
        raise RuntimeError("虚拟屏暂无帧: 画面静止未产生新帧或 helper 未就绪; 先做一次操作(vd_tap/vd_key)或稍候重试")
    with open(path, "wb") as f:
        f.write(data)
    return path


def vd_tap(x, y, dur=50):
    """用 swipe 同点(默认 50ms)模拟 tap, **不用 `input tap`**: held-stream 流保持开时, `input tap`
    (注入 MotionEvent DOWN 后有个同步等待)与 libadb 多路复用死锁 → 卡满 30s 超时(实测 MEIZU21);
    而 swipe(DOWN+MOVE+UP 序列)不触发该等待, 秒退且点击等效。长按传 dur>=800(见 vd_longpress)。"""
    v = _need_vid()
    _check_point(int(x), int(y), _size)
    return _mark_input(droid.adb_shell("input -d " + str(v) + " swipe " + str(int(x)) + " " + str(int(y))
                                       + " " + str(int(x)) + " " + str(int(y)) + " " + str(int(dur))))


def vd_longpress(x, y, dur=800):
    """长按 = swipe 同点长时长(默认 800ms)。"""
    return vd_tap(x, y, dur=dur)


def vd_swipe(x1, y1, x2, y2, dur=300):
    v = _need_vid()
    _check_point(int(x1), int(y1), _size)
    _check_point(int(x2), int(y2), _size)
    return _mark_input(droid.adb_shell(
        "input -d " + str(v) + " swipe "
        + str(int(x1)) + " " + str(int(y1)) + " " + str(int(x2)) + " " + str(int(y2)) + " " + str(int(dur))
    ))


def vd_text(text):
    """input -d text 直传剪贴板外的另一条输入通道(该虚拟屏无 A11y/paste 可用), shlex.quote 兜底空格/特殊字符。
    仅 ASCII: input text 对非 ASCII 静默丢字, 中文显式 raise 引导走 scheme 深链(见模块 docstring 输入与导航)。"""
    s = str(text)
    if any(ord(c) > 127 for c in s):
        raise RuntimeError("vd_text 仅支持 ASCII(input text 对中文静默丢字): 中文搜索/跳转请用 app scheme 深链 am start --display <vid> -a VIEW -d '<scheme>://...?keyword=<URL编码>'")
    return _mark_input(droid.adb_shell("input -d " + str(_need_vid()) + " text " + shlex.quote(s)))


def vd_key(name="KEYCODE_ENTER"):
    """input -d keyevent, name 需 Android keycode 全名(如 KEYCODE_ENTER/KEYCODE_BACK)或数字码。"""
    return _mark_input(droid.adb_shell("input -d " + str(_need_vid()) + " keyevent " + str(name)))


def vd_stop():
    """kill pid(校验 /proc/pid/cmdline 含 VdHelper 防 PID 复用误杀) + pkill 兜底 → helper 销毁, VirtualDisplay 随之消失。
    再 adb_shell_close 清 GA 侧 held 流引用(因 3>&- 断 fd3, 关流不 kill 进程, 故 kill pid 为主, close 仅清 map)。
    屏内容销毁依赖 VdHelper 的 DESTROY_CONTENT_ON_REMOVAL；不根据猜测的主屏包名强停应用。"""
    global _vid, _pkg, _size
    _, pid = _status()
    if pid:   # 单条 shell 内校验 cmdline 含 VdHelper 才 kill: 校验与 kill 原子, 消除两次 round-trip 的 PID 复用 TOCTOU
        droid.adb_shell("grep -q VdHelper /proc/" + str(pid) + "/cmdline 2>/dev/null && kill " + str(pid) + " 2>/dev/null; true")
    droid.adb_shell("pkill -f '[c]om.ljq.ga.VdHelper'; rm -f " + " ".join((_STATUS, _META)))
    droid.adb_shell_close("vd")
    _vid = None
    _size = None
    _pkg = None


def vd_status():
    info = _status_info()
    vid = _vid if _vid is not None else info.get("DISPLAY_ID")
    return {"vid": vid, "alive": _alive(info.get("PID")), "size": _size_of(info)}


def vd_probe():
    """后台模式三绿门控(诚实降级): {adb, input_d}. 均 True 才可开后台离屏; 否则降级前台 A11y(会打扰), 上层须告知用户。
    TRUSTED 屏创建能力在 vd_start 成功时即证明, 不在此重复探测。"""
    connected = bool(droid.adb_status().get("connected"))
    usage = droid.adb_shell("input") if connected else ""
    return {"adb": connected, "input_d": "-d DISPLAY_ID" in usage}
