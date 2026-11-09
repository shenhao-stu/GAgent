"""fsbot_ctl — 飞书机器人端内统一启停(GAgent 版)。

对外只三个入口: start() / stop() / status()。start 首步跑 bootstrap.ensure()
(解压依赖+打 pyaes 补丁+注入 sys.path), 再在独立线程+独立事件循环里跑 fsapp.main()。
修好上游三大坑: 停止后可重启(换新 event loop) / 防重复启动(线程 ident 注册) / 有连接确认(轮询 bot.log)。

不变量:
- 线程注册 _BOT_THREAD_ID 精确匹配本模块启的线程, 僵尸线程被忽略(防"假运行")。
- 缺依赖/缺凭证 → 显式返回原因(不静默), fail 半径大处显错。
- 只读 GA_DIR/fsbot/, 零核心代码耦合。
"""
import asyncio
import os
import re
import sys
import threading
import time

FSBOT_DIR = os.path.dirname(os.path.abspath(__file__))
GA_ROOT = os.path.dirname(FSBOT_DIR)                    # .../ga (agentmain.py/ga_android.py 所在)
SP_DIR = os.path.join(FSBOT_DIR, "site-packages")
BOT_LOG = os.path.join(FSBOT_DIR, "bot.log")

_BOT_THREAD_ID = None
_ENV_READY = False


def _ensure_env():
    """依赖就位 + 路径注入(幂等)。失败(缺依赖包)显式抛错。"""
    global _ENV_READY
    from fsbot import bootstrap
    bootstrap.ensure(add_to_path=True)                 # 解压 site-packages + 打补丁 + sys.path += SP_DIR
    for p in (GA_ROOT, FSBOT_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    _ENV_READY = True


def _find_bot_thread():
    if _BOT_THREAD_ID is None:
        return None
    for t in threading.enumerate():
        if t.ident == _BOT_THREAD_ID and t.is_alive():
            return t
    return None


def _reset_for_restart():
    """停止后再启: 清 shutdown_flag + 若 event loop 已停则换新(否则 run_until_complete 无法复用)。"""
    try:
        from fsbot import fsapp
        if fsapp.shutdown_flag.is_set():
            fsapp.shutdown_flag.clear()
    except Exception:
        pass
    try:
        import lark_oapi.ws.client as ws_mod
        loop = getattr(ws_mod, "loop", None)
        if loop is not None and not loop.is_running():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            ws_mod.loop = new_loop
    except Exception:
        pass


_ERR_HINTS = [
    (r"缺少依赖包|缺.*lark_oapi", "依赖未就位(重装 GAgent 或重试启动)"),
    (r"请在 设置|App ID|App Secret", "未配置飞书 App ID / App Secret(设置→飞书机器人)"),
    (r"Failed to resolve|NameResolutionError", "DNS 解析失败(检查网络, 能否访问 open.feishu.cn)"),
    (r"Max retries exceeded|connect failed", "连接飞书服务器失败(网络不通?)"),
]


def _wait_for_connection(timeout):
    errors = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _find_bot_thread():
            return {"connected": False, "errors": errors + ["机器人线程已退出"]}
        try:
            content = open(BOT_LOG, encoding="utf-8").read()
            if re.search(r"connect.*wss?://", content):
                return {"connected": True, "errors": errors}
            for pat, hint in _ERR_HINTS:
                if re.search(pat, content) and f"[{hint}]" not in errors:
                    errors.append(f"[{hint}]")
        except (FileNotFoundError, OSError):
            pass
        time.sleep(0.5)
    return {"connected": False, "errors": errors}


def status():
    """当前状态(轻量, 不解压)。running/ready/deps_ready/configured/thread。"""
    from fsbot import bootstrap
    st = {"running": False, "ready": False}
    try:
        st.update(bootstrap.status())
    except Exception as e:
        st["bootstrap_error"] = str(e)[:120]
    bot = _find_bot_thread()
    st["running"] = bot is not None
    try:
        from fsbot import fsapp                          # 只有依赖就位才 import 得了; 未就位则 configured 未知
        app_id, secret, _allowed, _pub, path = fsapp._feishu_config()
        st["configured"] = bool(app_id and secret)
        st["config_path"] = path
    except Exception:
        st["configured"] = _lark_configured()
    st["ready"] = st["running"] and st.get("deps_ready", False)
    return st


def _lark_configured():
    """依赖未就位时也能判断凭证是否已填(直接读 channels/lark.json)。"""
    try:
        import json
        p = os.path.join(GA_ROOT, "channels", "lark.json")
        if not os.path.exists(p):
            return False
        d = json.load(open(p, encoding="utf-8"))
        return bool((d.get("app_id") or d.get("fs_app_id")) and (d.get("app_secret") or d.get("fs_app_secret")))
    except Exception:
        return False


def start(timeout=25):
    """启动飞书机器人。返回 {success, message}。"""
    if _find_bot_thread():
        return {"success": True, "message": "机器人已在运行中"}
    try:
        _ensure_env()
    except Exception as e:
        return {"success": False, "message": f"依赖就位失败: {e}"}
    if not _lark_configured():
        return {"success": False, "message": "未配置飞书 App ID / App Secret，请在 设置→飞书机器人 填写"}
    _reset_for_restart()

    def _run_bot():
        import logging
        os.makedirs(os.path.dirname(BOT_LOG), exist_ok=True)
        try:
            from lark_oapi.core import log as lark_log
            for h in list(lark_log.logger.handlers):
                if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
                    lark_log.logger.removeHandler(h)
            fh = logging.FileHandler(BOT_LOG, mode="a")
            fh.setFormatter(logging.Formatter("[Lark] [%(asctime)s] [%(levelname)s] %(message)s"))
            lark_log.logger.addHandler(fh)
            lark_log.logger.setLevel(logging.INFO)
        except Exception:
            fh = None
        try:
            import lark_oapi.ws.client as ws_mod
            thread_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(thread_loop)
            ws_mod.loop = thread_loop
            from fsbot import fsapp
            fsapp.main()
        except Exception as e:
            import traceback
            try:
                open(BOT_LOG, "a", encoding="utf-8").write(f"[lark-bot] FATAL: {e}\n{traceback.format_exc()}\n")
            except Exception:
                pass
        finally:
            if fh is not None:
                try:
                    from lark_oapi.core import log as lark_log
                    lark_log.logger.removeHandler(fh); fh.close()
                except Exception:
                    pass

    bot_thread = threading.Thread(target=_run_bot, daemon=False, name="lark-bot")
    bot_thread.start()
    global _BOT_THREAD_ID
    _BOT_THREAD_ID = bot_thread.ident

    conn = _wait_for_connection(timeout)
    if conn["connected"]:
        return {"success": True, "message": "飞书机器人已启动并连接成功"}
    if _find_bot_thread():
        msg = "机器人线程已启动，等待 WebSocket 连接"
        if conn["errors"]:
            msg += "；" + "；".join(conn["errors"])
        return {"success": True, "message": msg}
    reason = ""
    try:
        lines = open(BOT_LOG, encoding="utf-8").readlines()
        reason = (lines[-1].strip() if lines else "")
    except (FileNotFoundError, OSError):
        pass
    return {"success": False, "message": "机器人启动失败" + (f": {reason}" if reason else "")}


def stop(timeout=10):
    """停止飞书机器人。返回 {success, message}。"""
    global _BOT_THREAD_ID
    bot = _find_bot_thread()
    if not bot:
        return {"success": True, "message": "机器人未在运行"}
    try:
        from fsbot import fsapp
        fsapp.shutdown_flag.set()
    except Exception as e:
        return {"success": False, "message": f"停止失败(导入 fsapp 出错): {e}"}
    try:
        import lark_oapi.ws.client as ws_mod
        loop = getattr(ws_mod, "loop", None)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass
    bot.join(timeout)
    if bot.is_alive():
        try:
            import lark_oapi.ws.client as ws_mod
            loop = getattr(ws_mod, "loop", None)
            if loop and not loop.is_closed():
                loop.call_soon_threadsafe(loop.close)
        except Exception:
            pass
        bot.join(5)
        if bot.is_alive():
            return {"success": True, "message": "已发停止信号，线程仍在清理", "warning": True}
    _BOT_THREAD_ID = None
    return {"success": True, "message": "飞书机器人已正常停止"}
