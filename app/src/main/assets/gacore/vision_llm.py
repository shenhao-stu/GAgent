"""vision_llm: 用**任务页当前选择的模型**做看图问答(多模态复用)。

为什么需要它: droid.ask_vision 原来只认 memory/vision_api.py。用户导入的模型本身
就是多模态的, 再维护一份单独的视觉配置既容易漏配, 也不会跟着任务页的模型切换走。
这里把当前 agent 的 llmclient.backend 当视觉后端: 同一个 provider / model / key /
proxy, 模型切换时自动跟随; 只需要在 code_run 执行线程里由 ga_android 注入。

看图的请求上下文必须干净: 主模型的 system/tools/思考档会污染视觉问答并拖慢
(模板实测思考档 45-48s vs 关闭 18s), 这里临时清空并在 finally 恢复。失败只影响
本次 ask_vision, 不改变主任务后续调用的配置。
"""
import base64
import contextlib
import io
import time

import cv2
import numpy as np

_ATTRS = ('system', 'tools', 'thinking_type', 'reasoning_effort', 'read_timeout', 'connect_timeout',
          'max_retries')
# MixinSession 的重试计数在另一个属性上(_retries), 且不在 _BROADCAST_ATTRS 里——只压成员的
# max_retries 压不到它。多供应商 fallback 组的视觉调用会因此仍按 _retries(默认 3) 重试。
_SHELL_ATTRS = ('_retries',)


def _prepare_image(image_input, max_pixels=1440000):
    if isinstance(image_input, np.ndarray):
        img = image_input
    elif isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None:
            raise ValueError('cannot read image: %s' % image_input)
    else:
        raise TypeError('image_input must be a path or BGR ndarray, got %s'
                        % type(image_input).__name__)
    h, w = img.shape[:2]
    if max_pixels and w * h > int(max_pixels):
        scale = (float(max_pixels) / (w * h)) ** 0.5
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError('JPEG encode failed')
    return base64.b64encode(buf.tobytes()).decode('ascii')


def _members(backend):
    """MixinSession 的成员各自持有 system/tools; 逐个清理, 不能只改聚合壳。"""
    sessions = getattr(backend, '_sessions', None)
    if isinstance(sessions, (list, tuple)) and sessions:
        return list(sessions)
    return [backend]


def _current(backend):
    sessions = getattr(backend, '_sessions', None)
    if isinstance(sessions, (list, tuple)) and sessions:
        try:
            idx = backend._pick() if hasattr(backend, '_pick') else 0
            return sessions[int(idx) % len(sessions)]
        except Exception:
            return sessions[0]
    return backend


def _is_claude(backend):
    return 'claude' in type(_current(backend)).__name__.lower()


def _message(backend, b64, prompt):
    if _is_claude(backend):
        return {'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': b64}},
            {'type': 'text', 'text': prompt},
        ]}
    return {'role': 'user', 'content': [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
    ]}


def _tighten_timeout(value, timeout):
    try:
        return min(float(value or timeout), float(timeout))
    except (TypeError, ValueError):
        return timeout


def ask_with_backend(backend, image_input, prompt, max_pixels=1440000, timeout=None):
    """Use the active task model (multimodal) to answer a question about an image.

    backend is the live agent backend; its provider/model/key/proxy are reused.
    Raises RuntimeError on an empty/error answer so droid.ask_vision's fuse can count it.
    """
    b64 = _prepare_image(image_input, max_pixels)
    msg = _message(backend, b64, prompt)
    targets = []
    for target in _members(backend):
        saved = {}
        for name in _ATTRS:
            try:
                saved[name] = getattr(target, name)
            except Exception:
                pass
        targets.append((target, saved))
    chunks = []
    # 聚合壳(MixinSession)自己也要压: backend.raw_ask 解析到 MixinSession._raw_ask, 它的循环上界是
    # self._retries(默认 3), 与成员的 max_retries 是两个属性, 且不在 _BROADCAST_ATTRS 里。
    shell_saved = {}
    for name in _SHELL_ATTRS:
        try:
            shell_saved[name] = getattr(backend, name)
        except Exception:
            pass
    try:
        for name in _SHELL_ATTRS:
            if name in shell_saved:
                try:
                    setattr(backend, name, 0)
                except Exception:
                    pass
        for target, saved in targets:
            if 'system' in saved:
                target.system = ''
            if 'tools' in saved:
                target.tools = None
            if 'thinking_type' in saved:
                target.thinking_type = 'disabled'
            if 'reasoning_effort' in saved:
                target.reasoning_effort = None
            # 视觉问答**不重试**: llmcore 的 _stream_with_retry 默认 max_retries=4, 每次带
            # read_timeout。视觉调用又被 droid.ask_vision 夹到 _VISION_TIMEOUT_S=30s, 于是一次
            # 超时最坏 5×30s + 退避 ≈ 160s, 而 code_run 默认只有 60s —— 真机 17:57 那次就是这样:
            # ask_vision 在 30s 超时后重试, 60.285s 被 code_run 强杀并留下僵尸线程, 下一个操作
            # 手机都被它卡住, 任务直接废掉。这里压成 0: 一次不成立即失败, 由 droid.ask_vision 的
            # 熔断计数与 SOP 的"超时即停"接管, 30s 内给出可读结论。
            if 'max_retries' in saved:
                target.max_retries = 0
            if timeout:
                if 'read_timeout' in saved:
                    target.read_timeout = _tighten_timeout(saved['read_timeout'], timeout)
                if 'connect_timeout' in saved:
                    target.connect_timeout = _tighten_timeout(saved['connect_timeout'], timeout)
        # 视觉请求不需要主工具的 system/tools; 提供商解析器可能 print 噪声, 不进入 code_run stdout
        #
        # 总时长硬上限: `read_timeout` 是 requests 的**单次读**超时(流式下=两个 chunk 之间
        # 最多静默多久), 不是总预算。思考型模型可以一个 token 都不吐地跑满 45s+ 而从不触发
        # 它——真机 2026-10-28 09:34 的 ask_point 就这样跑了 46.8s 还没回来(用户手动停止),
        # 而 code_run 默认只有 60s, 一个视觉调用就吃掉四分之三的预算。这里按墙钟兜底。
        deadline = time.monotonic() + timeout if timeout else None
        with contextlib.redirect_stdout(io.StringIO()):
            chunks = []
            for chunk in backend.raw_ask([msg]):
                chunks.append(str(chunk))
                if deadline is not None and time.monotonic() > deadline:
                    raise RuntimeError('视觉调用超过总时长上限 %ss(单次读超时管不住流式静默)' % timeout)
    finally:
        for target, saved in targets:
            for name, value in saved.items():
                try:
                    setattr(target, name, value)
                except Exception:
                    pass
        for name, value in shell_saved.items():
            try:
                setattr(backend, name, value)
            except Exception:
                pass
    text = ''.join(chunks).strip()
    if not text:
        raise RuntimeError('视觉模型未返回内容')
    if text.lstrip().startswith(('!!!Error:', '[Error:')):
        raise RuntimeError(text[:300])
    return text
