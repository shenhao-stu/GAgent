# -*- coding: utf-8 -*-
"""run_guard: code_run 僵尸线程协作取消护栏。

第一性: Chaquopy 内嵌 Python 线程无法被强杀(无 thread.kill/异步异常注入不可靠)。
code_run 超时/被停后只能放弃等待, 用户代码线程仍在后台跑; 若它在派发手机手势
(droid.tap/swipe/scroll → dispatchGesture)或 adb input, 会持续驱动整机, 直到 app
进程被杀 —— 这正是"操作浏览器后手机持续上滑、退出仍在、只有强杀才恢复"的真因。

护栏 = 在每个"操作手机的副作用入口"放一个协作检查点: 令牌一旦被置为取消,
僵尸线程下一次调用即抛 RunCancelled 自毁, 把失控半径压到 ≤1 次手势。

不变量:
- 令牌线程本地(threading.local): 每个 code_run 的 _run 线程 enter() 自己的令牌;
  监督线程持同一令牌对象引用, 超时/停止时 cancel() 置位, 僵尸线程读到即止。
- 只登记"当前被监督的线程"; 新一轮 code_run 是新线程新令牌, 旧令牌与之无关 → 零误伤。
- RunCancelled 继承 BaseException(非 Exception): 用户代码常见的 `except Exception`
  不会吞掉它, 令牌得以逐层上抛终结线程。
- check() 纯读 + 条件抛, 无副作用; 无令牌上下文(主 agent 线程 / PC 调试 / 非 code_run)
  永不抛(默认放行), 故对正常路径零影响。
"""
import threading
import time

_tls = threading.local()


class RunCancelled(BaseException):
    """本次 code_run 已超时/被终止, 拒绝继续操作手机。继承 BaseException 以躲开 except Exception。"""


class WatchdogExpired(BaseException):
    """本次工具调用已超过硬墙钟上限, 拒绝继续操作手机。继承 BaseException 以躲开 except Exception。"""


def enter(token, deadline=None):
    """_run 线程起始登记本线程的取消令牌(单元素可变容器 list[bool])与预算截止时刻。

    deadline = 本次 code_run 的 wall-clock 截止(itime.time()+timeout)。为什么要发布它:
    昂贵的一次性调用(视觉问答 15-46s)需要知道"这次脚本还剩多少预算", 才能既给足时间
    又不把整个 code_run 预算吃光(吃光会超时+留下僵尸线程)。缺省 None = 无预算上下文
    (主 agent 线程 / PC 调试), 调用方按自己的默认值走。"""
    _tls.token = token
    _tls.deadline = deadline


def leave():
    """线程结束清除登记(幂等)。"""
    _tls.token = None
    _tls.deadline = None


def remaining():
    """本线程所属 code_run 的剩余秒数; None = 不在 code_run 里(无预算上下文)。"""
    dl = getattr(_tls, 'deadline', None)
    return None if dl is None else max(0.0, dl - time.time())


def cancel(token):
    """监督线程置位取消 —— 对共享令牌对象本身写, 跨线程立即可见。"""
    token[0] = True


def enter_deadline(seconds):
    """登记本线程的看门狗截止时刻(time.monotonic()+seconds)。None/<=0 = 不设。"""
    _tls.watchdog = (time.monotonic() + float(seconds)) if seconds and float(seconds) > 0 else None


def clear_deadline():
    _tls.watchdog = None


def watchdog_left():
    """看门狗剩余秒数; None = 没设截止。"""
    dl = getattr(_tls, 'watchdog', None)
    return None if dl is None else max(0.0, dl - time.monotonic())


def cancelled():
    tok = getattr(_tls, "token", None)
    return bool(tok and tok[0])


def check():
    """副作用入口检查点: 令牌已取消抛 RunCancelled; 超过看门狗截止抛 WatchdogExpired。

    兼作看门狗检查点, 不新增调用点: droid 的每个读写入口早已调 check()
    (droid.py:180/429/435/990/1947/1957/1972/2062/2077/2090), 于是墙钟一超, 下一个
    设备操作即自裁 —— 治真机 213s/260s 那种"工具调用挂住 + 空 tool_result", 它的恢复
    只能中止整个任务并从原 prompt 重启, 此前进度全部作废。"""
    tok = getattr(_tls, "token", None)
    if tok and tok[0]:
        raise RunCancelled("code_run 已超时/被终止, 拒绝继续操作手机(僵尸线程护栏)")
    dl = getattr(_tls, 'watchdog', None)
    if dl is not None and time.monotonic() > dl:
        raise WatchdogExpired("工具调用超过墙钟上限, 已停止继续操作手机(看门狗)")


def install_thread_inheritance():
    """让用户代码 `threading.Thread(...)` 派生的子线程继承父线程的取消令牌 —— 否则僵尸"孙线程"的
    _tls.token 为空、check() 恒放行, 护栏"失控半径≤1次手势"的不变量只对单线程用户代码成立。
    做法: 子线程在**创建时**快照父线程当前令牌, run() 入口登记为自身线程本地令牌, 令牌沿线程族谱传播。
    幂等(重复调用只包一次); 进程内 GA 框架线程在无令牌上下文创建 → 快照为 None → 零影响。"""
    import threading
    if getattr(threading.Thread, "_ga_guarded", False):
        return
    _Base = threading.Thread

    class _GuardedThread(_Base):
        _ga_guarded = True

        def __init__(self, *a, **k):
            # 用捕获的原始基类显式初始化, 不用零参 super()。
            # 原因: 第三方库(如 paramiko.Transport)在补丁生效前定义 `class X(threading.Thread)` 捕获了原始基类,
            # 但其 __init__ 里调 `threading.Thread.__init__(self)` 会命中被替换后的 _GuardedThread.__init__,
            # 此时 self 并非 _GuardedThread 实例, 零参 super() 触发 "super(type, obj): obj must be an instance..." 崩溃。
            # _Base.__init__(self, ...) 不做实例类型校验, 对任何 Thread 子类都安全。
            _Base.__init__(self, *a, **k)
            self._ga_token = getattr(_tls, "token", None)   # 创建时刻父线程的令牌(可能为 None)

        def run(self):
            if getattr(self, "_ga_token", None) is not None:
                _tls.token = self._ga_token
            _Base.run(self)

    threading.Thread = _GuardedThread
