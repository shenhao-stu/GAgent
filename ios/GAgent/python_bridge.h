// Swift ↔ CPython C API 桥接头 (XcodeGen: SWIFT_OBJC_BRIDGING_HEADER)。
// Python.xcframework 由 ios/deps/get_python.sh 取回(BeeWare Python-Apple-support 3.13)。
#ifndef GA_PYTHON_BRIDGE_H
#define GA_PYTHON_BRIDGE_H
#include <Python.h>

// 解释器初始化在 C 侧做(python_bridge.m): PyConfig_SetBytesString 要同时收 &config 与 &config.home,
// 在 Swift 里构成对同一 struct 的重叠独占访问(编译期 exclusivity 报错); 且 PyConfig 一族在 C 里更自然。
// home = PYTHONHOME; paths_nl = 以 '\n' 连接的 module_search_paths(set=1, 显式给全)。返回 0=成功, 非0=失败码。
// 调用后 GIL 处于持有态(调用方随后 import bootstrap_ios、init、再 PyEval_SaveThread 放锁)。
int ga_py_init(const char *home, const char *paths_nl);

#endif
