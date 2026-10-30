# vision_api 模板（Android 端，可选的后备）。
# 默认情况下 droid.ask_vision 直接复用任务页当前选择的模型（多模态），不需要本文件；
# 只有需要独立视觉后端/端点、或任务没有可用模型时，才复制本文件 → memory/vision_api.py。
# 1. 复制本文件 → memory/vision_api.py
# 2. 只改头部"用户配置区": 扫描 mykey 里的配置名(⚠️只看变量名, 禁止输出 apikey 值),
#    填入 CLAUDE_CONFIG_KEY / OPENAI_CONFIG_KEY, 选 DEFAULT_BACKEND, 并小图实测
# 3. 用法: from vision_api import ask_vision
#    ask_vision(droid.shot(), '描述当前界面')   # 直接吃 BGR ndarray, 也可传文件路径
#    裁剪后再问更省 token: ask_vision(img[y1:y2, x1:x2], '这个按钮是什么状态?')
import base64, requests, sys, os

# ============ 用户配置区（从 template 拷贝后只需改这里）============
CLAUDE_CONFIG_KEY = ''                   # mykey 中 Claude 配置的变量名
OPENAI_CONFIG_KEY = ''                   # mykey 中 OpenAI 兼容配置的变量名
MODELSCOPE_API_KEY = ''                  # 直接填 ModelScope token
DEFAULT_BACKEND = 'claude'               # 默认后端: 'claude' / 'openai' / 'modelscope'
# =================================================================

# 看图问答默认关闭 Anthropic 协议的扩展推理: 识别界面/状态属于感知问题, 推理与回答又共用 max_tokens。
# 实测(同模型、同截图、同问题): 默认推理 45-48 s, 关闭后 18 s。需要服务商默认行为时调用传 thinking='auto'。
DEFAULT_THINKING = 'disabled'

MODELSCOPE_API_BASE = 'https://api-inference.modelscope.cn'
MODELSCOPE_MODEL = 'Qwen/Qwen3-VL-235B-A22B-Instruct'

_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in [os.path.join(_DIR, '..')]:
    if _p not in sys.path: sys.path.insert(0, _p)

def ask_vision(image_input, prompt="详细描述这张图片的内容", timeout=60, max_pixels=1440000, backend=DEFAULT_BACKEND, thinking=DEFAULT_THINKING):
    try:
        b64 = _prepare_image(image_input, max_pixels)
    except Exception as e:
        return f"Error: 图片处理失败 - {type(e).__name__}: {e}"
    try:
        if backend == 'claude':
            return _call_claude(b64, prompt, timeout, thinking=thinking)
        elif backend == 'openai':
            cfg = _cfg(OPENAI_CONFIG_KEY)
            return _call_openai_compat(
                b64, prompt, timeout,
                apibase=cfg['apibase'], apikey=cfg['apikey'], model=cfg['model'], proxy=cfg.get('proxy')
            )
        elif backend == 'modelscope':
            return _call_openai_compat(
                b64, prompt, timeout,
                apibase=MODELSCOPE_API_BASE, apikey=MODELSCOPE_API_KEY, model=MODELSCOPE_MODEL, proxy=None
            )
        else: return f"Error: 未知backend '{backend}'，可选: claude, openai, modelscope"
    except requests.exceptions.Timeout:
        return f"Error: 请求超时 (>{timeout}s)"
    except requests.exceptions.RequestException as e:
        return f"Error: API请求失败 - {type(e).__name__}: {e}"
    except (KeyError, ValueError) as e:
        return f"Error: 响应解析失败 - {e}"

# ===================== 以下为内部实现 =====================

def _prepare_image(image_input, max_pixels=1440000):
    """加载(路径或BGR ndarray)+缩放+JPEG base64编码。端侧无PIL, 用cv2。"""
    import cv2
    import numpy as np
    if isinstance(image_input, np.ndarray):
        img = image_input
    elif isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None: raise ValueError(f"无法读取图片: {image_input}")
    else:
        raise TypeError(f"image_input 必须是文件路径或BGR ndarray，实际: {type(image_input).__name__}")
    h, w = img.shape[:2]
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        print(f"  📐 缩放: {w}×{h} → {img.shape[1]}×{img.shape[0]}")
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok: raise ValueError("JPEG编码失败")
    b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
    print(f"  📦 Base64: {len(buf)/1024:.1f}KB")
    return b64

def _cfg(key):
    """从 llmcore 统一加载的 mykey(py模块或json dict) 取配置"""
    import llmcore
    mk = llmcore.mykeys
    return mk[key] if isinstance(mk, dict) else getattr(mk, key)

def _call_claude(b64, prompt, timeout, max_tokens=None, thinking=DEFAULT_THINKING):
    cfg = _cfg(CLAUDE_CONFIG_KEY)
    if max_tokens is None:
        max_tokens = cfg.get('max_tokens')
    if max_tokens is None:
        max_tokens = 8192
    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError('max_tokens must be a positive integer')
    proxy = cfg.get('proxy')
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    payload = {'model': cfg['model'], 'max_tokens': max_tokens, 'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': b64}},
                {'type': 'text', 'text': prompt}
            ]
        }]}
    by_config = cfg.get('thinking_type') == 'disabled'
    if by_config or thinking == 'disabled':
        payload['thinking'] = {'type': 'disabled'}
    def post():
        return requests.post(
            __import__('llmcore').auto_make_url(cfg['apibase'], 'messages'), json=payload,
            headers={'x-api-key': cfg['apikey'], 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            timeout=timeout, proxies=proxies
        )
    resp = post()
    if resp.status_code == 400 and 'thinking' in payload and not by_config:
        payload.pop('thinking')                  # 服务商不接受该参数: 只退回其默认行为一次, 不改用户配置
        resp = post()
    resp.raise_for_status()
    data = resp.json()
    if data.get('stop_reason') == 'max_tokens':
        raise ValueError(f'Vision response truncated (max_tokens={max_tokens}); increase provider max_tokens')
    text = '\n'.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
    if not text.strip(): raise ValueError('Vision response contains no text')
    return text

def _call_openai_compat(b64, prompt, timeout, *, apibase, apikey, model, proxy=None):
    proxies = {'https': proxy, 'http': proxy} if proxy else None
    resp = requests.post(
        __import__('llmcore').auto_make_url(apibase, 'chat/completions'),
        json={'model': model, 'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}
            ]
        }]},
        headers={'Authorization': f"Bearer {apikey}", 'Content-Type': 'application/json'},
        proxies=proxies, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']
