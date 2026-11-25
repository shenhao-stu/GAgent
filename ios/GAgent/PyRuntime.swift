import Foundation

/// 嵌入式 CPython 运行时 (PEP 730)。与 Android Py.kt 同构: boot 一次, call 多路。
/// GIL 纪律: boot 线程 Py_InitializeFromConfig 后立即 PyEval_SaveThread 放锁;
/// 此后任意线程 call() 用 PyGILState_Ensure/Release 包住 —— 与 Chaquopy 多线程语义等价,
/// android_entry 本就承受 WebView 多后台线程并发调用, 无需额外串行队列。
/// Python 侧长阻塞(requests 等)会自动放 GIL, 并发 /ga/poll 不会被卡死。
final class PyRuntime {
    static let shared = PyRuntime()
    private let lock = NSLock()                              // 跨线程发布 ready/bootstrap 的内存栅栏(C3)
    private var _ready = false
    private var bootstrap: UnsafeMutablePointer<PyObject>?   // bootstrap_ios 模块(持久引用)
    private var _bootMsg = ""
    var ready: Bool { lock.lock(); defer { lock.unlock() }; return _ready }
    /// 引擎 boot 结果: boot 未完成="" (app.js 继续等); 完成后='ok'/'nokey'/'ERR:...'。
    /// ready() 桥直取此值(镜像 Android `fun ready()=bootMsg`, 不进 Python)。_bootMsg 初值"", 仅 boot 完成时落值,
    /// 故无条件返回即"进行中空串 / 完成后真值"——失败的 ERR: 也如实透出(否则永久转圈)。
    var bootMsg: String { lock.lock(); defer { lock.unlock() }; return _bootMsg }

    /// - pyHome: bundle 内 Python 资源根(含 lib/python3.13)
    /// - paths:  module_search_paths 全量(stdlib + lib-dynload + bundle/py + site-packages + gaDir)
    func boot(gaDir: String, pyHome: String, paths: [String]) -> String {
        // 解释器初始化在 C 侧(python_bridge.m): 规避 PyConfig_SetBytesString(&cfg,&cfg.home,..) 的 Swift 重叠独占访问。
        let rc = ga_py_init(pyHome, paths.joined(separator: "\n"))
        if rc != 0 { return publish(nil, "ERR:py_init(\(rc))") }

        guard let mod = PyImport_ImportModule("bootstrap_ios") else {   // guard-let 解包(regression: 曾把 Optional 传给 invoke)
            PyErr_Print(); PyEval_SaveThread(); return publish(nil, "ERR:import bootstrap_ios")
        }
        let r = invoke(mod, "init", [gaDir])
        let msg = Self.str(r) ?? "ERR:init"
        Py_XDECREF(r)
        let out = publish(msg.hasPrefix("ERR") ? nil : mod, msg)   // bootstrap 先落、ready 后发布(C3 有序)
        PyEval_SaveThread()                                    // 放 GIL, 移交多线程世界
        return out
    }

    /// bootstrap_ios.call(fn, *args) → str。任意线程可调(GIL 每调用 Ensure/Release)。
    func call(fn: String, args: [String]) -> String? {
        lock.lock(); let mod = bootstrap; lock.unlock()
        guard let mod else { return nil }
        let g = PyGILState_Ensure()
        defer { PyGILState_Release(g) }
        let callable = PyObject_GetAttrString(mod, "call")
        let r = callable.flatMap { c -> UnsafeMutablePointer<PyObject>? in
            let t = PyTuple_New(1 + args.count)
            PyTuple_SetItem(t, 0, PyUnicode_FromString(fn))    // SetItem 窃取引用, 无需 DECREF 元素
            for (i, a) in args.enumerated() { PyTuple_SetItem(t, i + 1, PyUnicode_FromString(a)) }
            let rr = PyObject_CallObject(c, t); Py_XDECREF(t); return rr
        }
        let out = Self.str(r)
        if r == nil { PyErr_Print() }
        Py_XDECREF(r); Py_XDECREF(callable)
        return out
    }

    /// GIL 已持有时调 bootstrap_ios 的顶层函数(boot 期 init 用)。
    private func invoke(_ mod: UnsafeMutablePointer<PyObject>, _ fn: String,
                        _ args: [String]) -> UnsafeMutablePointer<PyObject>? {
        guard let callable = PyObject_GetAttrString(mod, fn) else { return nil }
        defer { Py_XDECREF(callable) }
        let t = PyTuple_New(args.count)
        for (i, a) in args.enumerated() { PyTuple_SetItem(t, i, PyUnicode_FromString(a)) }
        let r = PyObject_CallObject(callable, t)
        Py_XDECREF(t)
        return r
    }

    private func publish(_ mod: UnsafeMutablePointer<PyObject>?, _ msg: String) -> String {
        lock.lock(); defer { lock.unlock() }
        bootstrap = mod; _bootMsg = msg; _ready = (mod != nil)
        return msg
    }

    private static func str(_ o: UnsafeMutablePointer<PyObject>?) -> String? {
        guard let o else { return nil }
        guard let u = PyObject_Str(o) else { return nil }
        defer { Py_XDECREF(u) }
        return PyUnicode_AsUTF8(u).map { String(cString: $0) }
    }
}
