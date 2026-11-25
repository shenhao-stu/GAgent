// CPython 解释器初始化(C 侧, 见 python_bridge.h 注释)。只做 Py_InitializeFromConfig, 不碰模块。
#include "python_bridge.h"
#include <string.h>
#include <stdlib.h>
#include <pthread.h>
#include <dispatch/dispatch.h>

extern char *ga_board_call(const char *input);
extern int ga_shell_run(const char *command, const char *directory, int output_fd, const char **error);
extern void ga_shell_cancel(void);

static PyObject *board_call(PyObject *self, PyObject *args) {
    const char *input;
    if (!PyArg_ParseTuple(args, "s:call", &input)) return NULL;
    char *reply;
    Py_BEGIN_ALLOW_THREADS
    reply = ga_board_call(input);
    Py_END_ALLOW_THREADS
    if (!reply) return PyErr_NoMemory();
    PyObject *result = PyUnicode_FromString(reply);
    free(reply);
    return result;
}

static PyMethodDef board_methods[] = {
    {"call", board_call, METH_VARARGS, "Run a fixed iPhone board action using JSON."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef board_module = {
    PyModuleDef_HEAD_INIT, "_gaboard", NULL, -1, board_methods
};
static PyObject *PyInit_gaboard(void) { return PyModule_Create(&board_module); }

// _ganative: what code_run scripts cannot do in Python alone (the signed `ios` module is its only caller).
// Runs a Python callable on the main thread and waits for it: UIKit objects reached through
// rubicon-objc must be used there. The GIL is released while waiting and re-taken on the main thread.
static PyObject *native_on_main(PyObject *self, PyObject *callable) {
    if (!PyCallable_Check(callable)) {
        PyErr_SetString(PyExc_TypeError, "on_main expects a callable");
        return NULL;
    }
    if (pthread_main_np()) return PyObject_CallNoArgs(callable);
    __block PyObject *result = NULL;
    __block PyObject *error = NULL;
    Py_BEGIN_ALLOW_THREADS
    dispatch_sync(dispatch_get_main_queue(), ^{
        PyGILState_STATE state = PyGILState_Ensure();
        result = PyObject_CallNoArgs(callable);
        if (!result) error = PyErr_GetRaisedException();
        PyGILState_Release(state);
    });
    Py_END_ALLOW_THREADS
    if (error) {
        PyErr_SetRaisedException(error);
        return NULL;
    }
    return result;
}

// Runs one command line in the built-in shell and returns its exit status. Output goes to the
// given file descriptor. The process working directory is left changed.
static PyObject *native_shell_run(PyObject *self, PyObject *args) {
    const char *command;
    const char *directory;
    int output_fd;
    if (!PyArg_ParseTuple(args, "ssi:shell_run", &command, &directory, &output_fd)) return NULL;
    const char *error = NULL;
    int status;
    Py_BEGIN_ALLOW_THREADS
    status = ga_shell_run(command, directory, output_fd, &error);
    Py_END_ALLOW_THREADS
    if (error) {
        PyErr_SetString(PyExc_RuntimeError, error);
        return NULL;
    }
    return PyLong_FromLong(status);
}

static PyObject *native_shell_cancel(PyObject *self, PyObject *unused) {
    ga_shell_cancel();
    Py_RETURN_NONE;
}

static PyMethodDef native_methods[] = {
    {"on_main", native_on_main, METH_O, "Call a Python callable on the main thread and return its result."},
    {"shell_run", native_shell_run, METH_VARARGS, "Run a command line in the built-in shell; returns its exit status."},
    {"shell_cancel", native_shell_cancel, METH_NOARGS, "Ask the running shell command to stop."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef native_module = {
    PyModuleDef_HEAD_INIT, "_ganative", NULL, -1, native_methods
};
static PyObject *PyInit_ganative(void) { return PyModule_Create(&native_module); }

int ga_py_init(const char *home, const char *paths_nl) {
    if (PyImport_AppendInittab("_gaboard", PyInit_gaboard) < 0) return 5;
    if (PyImport_AppendInittab("_ganative", PyInit_ganative) < 0) return 5;
    PyStatus status;

    PyPreConfig pre;
    PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1;
    status = Py_PreInitialize(&pre);
    if (PyStatus_Exception(status)) return 1;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.write_bytecode = 0;                        // bundle 只读, 别写 .pyc

    status = PyConfig_SetBytesString(&config, &config.home, home);
    if (PyStatus_Exception(status)) { PyConfig_Clear(&config); return 2; }

    // isolated 不读 env, 故 module_search_paths 显式给全(set=1 关掉自动推导 ⇒ stdlib/lib-dynload 也须在内)。
    char *buf = strdup(paths_nl ? paths_nl : "");
    if (buf) {
        char *save = NULL;
        for (char *tok = strtok_r(buf, "\n", &save); tok; tok = strtok_r(NULL, "\n", &save)) {
            if (*tok == '\0') continue;
            wchar_t *w = Py_DecodeLocale(tok, NULL);
            if (!w) continue;
            status = PyWideStringList_Append(&config.module_search_paths, w);
            PyMem_RawFree(w);
            if (PyStatus_Exception(status)) { free(buf); PyConfig_Clear(&config); return 3; }
        }
        free(buf);
    }
    config.module_search_paths_set = 1;

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) return 4;
    return 0;                                         // GIL 持有态返回
}
