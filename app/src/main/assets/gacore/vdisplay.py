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
_STATUS = "/data/local/tmp/ga_vd.status"  # VdHelper 建屏后原子写 "DISPLAY_ID=<id>\nPID=<pid>": 进程真相源, 解耦易失 stdout 日志; Python 重启/日志截断后按 pid 反查既有屏做幂等复用, liveness 用 /proc/<pid>(消除 pgrep cmdline 自匹配)

_vid = None   # 模块级缓存: 当前虚拟屏 display id, 未启动为 None
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
    global _vid
    if _vid is None:
        vid, pid = _status()
        if vid is not None and _alive(pid):
            _vid = vid
    if _vid is None:
        raise RuntimeError("虚拟屏未启动: 先 vd_start()")
    return _vid


def _status():
    """读 status 文件 → (vid|None, pid|None); 缺失/半写返回 (None,None)。"""
    out = droid.adb_shell("cat " + _STATUS + " 2>/dev/null")
    v = re.search(r"DISPLAY_ID=(\d+)", out); p = re.search(r"PID=(\d+)", out)
    return (int(v.group(1)) if v else None, int(p.group(1)) if p else None)


def _alive(pid):
    """校验 pid 存活**且确为 VdHelper**: 单查 /proc/pid/cmdline(不存在→空, 别的进程复用该 pid→cmdline 不含 VdHelper)。
    防 PID 复用误判——否则 vd_start 复用分支会复用一个已死屏的 vid, 后续 input -d/am 全打空。"""
    return bool(pid) and "VdHelper" in droid.adb_shell("cat /proc/" + str(pid) + "/cmdline 2>/dev/null")


def vd_start(pkg, activity=None, w=1080, h=1920, dpi=320, timeout=10.0):
    """建离屏虚拟屏(存活按 status 文件复用, 幂等)+把 pkg 拉到该屏。返回 display id。
    落屏后校验 pkg 未变默认屏前台(A11y 仅见默认屏): 变=被系统回退弹主屏=打扰, 立即 force-stop 并报错。"""
    global _vid, _pkg
    vid, pid = _status()
    if vid is not None and _alive(pid):
        _vid = vid
    else:
        apk = _apk_path()
        droid.adb_shell("pkill -f '[c]om.ljq.ga.VdHelper' 2>/dev/null; rm -f " + _STATUS + " " + _LOG + "; true")   # 清孤儿 + 陈旧 status/log(否则轮询首轮读到旧 DISPLAY_ID 或旧 ERR: 误判)
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

    target = activity or _resolve_activity(pkg)
    if "/" not in target:
        target = pkg + "/" + target
    try:   # 任务路径归属: 离屏虚拟屏(只记类别, 不记 pkg); 惰性 import + 全吞异常, PC 侧无 plugins 包不报错
        from plugins.analytics_hook import record_path
        record_path("vdisplay")
    except Exception:
        pass
    before = droid.ping().get("pkg", "")
    droid.adb_shell("am start --display " + str(_vid) + " -n " + target)
    if before != pkg and droid._wait_fg(pkg, 1.5) == pkg:
        droid.adb_shell("am force-stop " + pkg)
        raise RuntimeError(pkg + " 被系统落到默认屏(拒绝虚拟屏启动), 已撤回避免打扰前台; 该 App/ROM 不支持后台虚拟屏, 请降级前台模式")
    _pkg = pkg
    return _vid


_SHOT_EXT = "/sdcard/Android/data/" + _PKG + "/files/ga_vd_shot.png"  # app 自有外部目录: shell 可写, app 免权限直读


def vd_shot(path, wait=0.6):
    """读 VdHelper 落盘的最新虚拟屏帧存到本地 path(screencap -d 对虚拟屏在部分 ROM 无效, 故 helper 消费 ImageReader 落 PNG)。
    动作后画面变化会触发新帧(节流≤400ms), 故先等 wait 秒再读, 拿到贴近当前态的一帧。
    主通道=cp 到 app 外部目录后直读文件(1MB+ 大帧 base64 走文本 bus 实测超时); base64 仅作回退。"""
    _need_vid()
    time.sleep(wait)
    data = b""
    try:
        # rm 先清残留 + && echo 显式确认: cp 失败(源未写/目录被拒)时 adb_shell 只回错误文本不抛错,
        # 不确认会 open 到上一次调用的旧帧 → agent 拿陈旧截图误诊(比无帧更糟)
        out = droid.adb_shell("rm -f %s; cp %s %s && echo GA_CP_OK" % (_SHOT_EXT, _SHOT, _SHOT_EXT))
        if "GA_CP_OK" not in out:
            raise RuntimeError("cp failed: " + out.strip()[:200])
        with open(_SHOT_EXT, "rb") as f:
            data = f.read()
    except Exception:
        # 截图 base64 常达 1-4MB, 远超 adb_shell 默认 256KB 上限(超限会报错防帧损坏), 故显式放开 max_bytes 到 16MB
        b64 = droid.adb_shell("base64 " + _SHOT, max_bytes=16 * 1024 * 1024)
        data = base64.b64decode("".join(b64.split())) if b64.strip() else b""
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
    return droid.adb_shell("input -d " + str(v) + " swipe " + str(int(x)) + " " + str(int(y))
                           + " " + str(int(x)) + " " + str(int(y)) + " " + str(int(dur)))


def vd_longpress(x, y, dur=800):
    """长按 = swipe 同点长时长(默认 800ms)。"""
    return vd_tap(x, y, dur=dur)


def vd_swipe(x1, y1, x2, y2, dur=300):
    return droid.adb_shell(
        "input -d " + str(_need_vid()) + " swipe "
        + str(int(x1)) + " " + str(int(y1)) + " " + str(int(x2)) + " " + str(int(y2)) + " " + str(int(dur))
    )


def vd_text(text):
    """input -d text 直传剪贴板外的另一条输入通道(该虚拟屏无 A11y/paste 可用), shlex.quote 兜底空格/特殊字符。
    仅 ASCII: input text 对非 ASCII 静默丢字, 中文显式 raise 引导走 scheme 深链(见模块 docstring 输入与导航)。"""
    s = str(text)
    if any(ord(c) > 127 for c in s):
        raise RuntimeError("vd_text 仅支持 ASCII(input text 对中文静默丢字): 中文搜索/跳转请用 app scheme 深链 am start --display <vid> -a VIEW -d '<scheme>://...?keyword=<URL编码>'")
    return droid.adb_shell("input -d " + str(_need_vid()) + " text " + shlex.quote(s))


def vd_key(name="KEYCODE_ENTER"):
    """input -d keyevent, name 需 Android keycode 全名(如 KEYCODE_ENTER/KEYCODE_BACK)或数字码。"""
    return droid.adb_shell("input -d " + str(_need_vid()) + " keyevent " + str(name))


def vd_stop():
    """kill pid(校验 /proc/pid/cmdline 含 VdHelper 防 PID 复用误杀) + pkill 兜底 → helper 销毁, VirtualDisplay 随之消失。
    再 adb_shell_close 清 GA 侧 held 流引用(因 3>&- 断 fd3, 关流不 kill 进程, 故 kill pid 为主, close 仅清 map)。
    跳前台护栏: 屏销毁时内容就地销毁靠 VdHelper 的 DESTROY_CONTENT_ON_REMOVAL flag(缺它时 AOSP 把屏上
    task 整条搬回主屏置顶=跳前台, MEIZU21 取证定案); 个别 ROM 若不吃该 flag, 此处检测"销毁后被采集 pkg
    冒到主屏前台且销毁前不在前台"并 force-stop 撤回(前后对比防误杀用户自己正开着的同 app)。"""
    global _vid, _pkg
    before = droid._fg() if _pkg else ""
    _, pid = _status()
    if pid:   # 单条 shell 内校验 cmdline 含 VdHelper 才 kill: 校验与 kill 原子, 消除两次 round-trip 的 PID 复用 TOCTOU
        droid.adb_shell("grep -q VdHelper /proc/" + str(pid) + "/cmdline 2>/dev/null && kill " + str(pid) + " 2>/dev/null; true")
    droid.adb_shell("pkill -f '[c]om.ljq.ga.VdHelper'; rm -f " + _STATUS)
    droid.adb_shell_close("vd")
    # 护栏(常态不触发, flag 起效时屏内容就地销毁): 仅当采集 pkg 销毁前不在前台、销毁后瞬时冒到前台才撤回。
    # reparent 是瞬时的, 一次 sleep+比对足够, 不长轮询(避免健康路径白等); 撤回用 force-stop(语义强且此场景恰当)。
    if _pkg and before != _pkg:
        time.sleep(0.5)
        if droid._fg() == _pkg:
            droid.adb_shell("am force-stop " + _pkg)
    _vid = None
    _pkg = None


def vd_status():
    vid, pid = _status()
    return {"vid": _vid if _vid is not None else vid, "alive": _alive(pid)}


def vd_probe():
    """后台模式三绿门控(诚实降级): {adb, input_d}. 均 True 才可开后台离屏; 否则降级前台 A11y(会打扰), 上层须告知用户。
    TRUSTED 屏创建能力在 vd_start 成功时即证明, 不在此重复探测。"""
    connected = bool(droid.adb_status().get("connected"))
    usage = droid.adb_shell("input") if connected else ""
    return {"adb": connected, "input_d": "-d DISPLAY_ID" in usage}
