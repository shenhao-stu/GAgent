"""Boot a clean signed payload with a writable data directory, exactly like PyRuntime."""
import sys
from pathlib import Path
from signed_runtime import HOST, CORE, DATA


def main():
    ga_dir = str(DATA)
    sys.path[:] = [p for p in sys.path if p not in {str(CORE), str(HOST)}]
    (DATA / "ga.py").write_text("raise RuntimeError('writable module executed')")
    sys.path.insert(0, ga_dir)  # Legacy installations must remove this import path on boot.
    import bootstrap_ios
    r = bootstrap_ios.init(ga_dir)
    assert r == "nokey", "init 返回异常: %r" % r
    assert ga_dir not in sys.path, "writable data remains on sys.path"
    import ios_entry, agentmain, ga
    from kernel_adapter.ios_host import IOSHandler
    assert Path(ios_entry.__file__).resolve().parent == HOST
    assert Path(agentmain.__file__).resolve().parent == CORE
    assert agentmain.GenericAgentHandler is IOSHandler
    assert Path(ga.script_dir).resolve() == DATA
    assert (DATA / "memory/global_mem_insight.txt").is_file()
    assert "kernel_adapter.executor" not in sys.modules
    assert bootstrap_ios.call("__getattribute__", "__dict__") == '{"error":"unknown_engine_fn"}'
    print("T1.1 boot ok, bundle-only core import →", r)

    # 命令路由冒烟: /kv 往返 + /config(纯本地, 不触网)
    assert bootstrap_ios.call("send", "/kv.set ga.t1probe hello") == "ok", "kv.set 失败"
    got = bootstrap_ios.call("send", "/kv.get ga.t1probe")
    assert got == "hello", "kv.get 回读不符: %r" % got
    print("T1.2 命令路由(/kv 往返)ok")

    cfg = bootstrap_ios.call("send", "/config")
    assert cfg.strip().startswith("{"), "/config 非 JSON: %r" % cfg[:80]
    print("T1.3 /config 出 JSON ok")

    # 多会话桥名映射目标必须真存在(B2): ios_bridge 把 sendC/pollC/abortC/pollAll → send2/poll2/abort2/poll_all
    import android_entry
    for real in ("send2", "poll2", "abort2", "poll_all"):
        assert hasattr(android_entry, real), "android_entry 缺 %s(B2 映射目标失效)" % real
    assert not hasattr(android_entry, "sendC"), "android_entry 竟有 sendC(说明无需映射? 复核 B2)"
    print("T1.4 多会话映射目标 send2/poll2/abort2/poll_all 均在 ok")

    # 自愈①: 清 ios_entry._INITED 后 call 自动重跑 init
    import ios_entry
    ios_entry._INITED = False
    assert bootstrap_ios.call("send", "/kv.get ga.t1probe") == "hello", "自愈(ios_entry 缺章)后 kv 丢"
    # 自愈②(C9): 仅 android_entry 被逐出 sys.modules 时也要复位(否则委托到从未 init 的新引擎)
    sys.modules.pop("android_entry", None)
    assert bootstrap_ios.call("send", "/kv.get ga.t1probe") == "hello", "自愈(android_entry 逐出)后 kv 丢"
    print("T1.5 双层缺章自愈(ios_entry + android_entry)ok")

    # code_run imports the user's helper modules; signed and standard modules always win.
    from importlib.machinery import PathFinder
    from agent_loop import exhaust
    memory = DATA / "memory"
    assert sys.path[-2:] == [str(memory), str(DATA / "pylib")], sys.path[-3:]
    assert sys.path.count(str(memory)) == 1, "self-heal duplicated the memory path"
    assert ga_dir not in sys.path, "writable data root remains on sys.path"
    (memory / "helper_probe.py").write_text("VALUE = 'from memory'\n")
    for name in ("json", "ios_policy", "ga"):
        (memory / (name + ".py")).write_text("raise RuntimeError('writable module replaced signed code')\n")
        origin = Path(PathFinder.find_spec(name, sys.path).origin).resolve()
        assert not origin.is_relative_to(DATA), "%s resolves to writable data: %s" % (name, origin)
    result = exhaust(ga.code_run("import helper_probe\nprint(helper_probe.VALUE, os.path.basename(os.getcwd()))"))
    assert result == {"status": "success", "stdout": "from memory temp\n", "exit_code": 0}, result
    assert "kernel_adapter.executor" not in sys.modules
    print("T1.6 code_run 可导入 memory 模块, 签名模块与标准库不被遮蔽 ok")

    print("PASS T1: gacore 在 CPython %s 下 boot + 命令路由 + 双层自愈 + 映射目标全通"
          % ".".join(map(str, sys.version_info[:3])))


if __name__ == "__main__":
    main()
