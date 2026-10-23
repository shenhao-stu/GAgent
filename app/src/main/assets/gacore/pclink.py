"""pclink — 手机端连接 PC hub 的可选静默功能(android_entry /pclink.* 分发到此).

原理: PC 端 hub.py(hub_p2p) 把 /api/ 以 HTTPExporter 挂在 P2P socket 上;
本模块作为对端, 直接在 socket 上收发 p2p-http.req/res 帧(不起本地 HTTP 服务,
省掉 aiohttp server), 把 hub API 变成同步可调的 handle('/pclink.api GET /api/peers').
配对码 → connect_code 自动把 room UUID 存 GA_DIR/pclink_rooms.json, 之后
后台 keeper 线程 connect_saved 自动重连, App 重启免配对.
本文件不存在或依赖缺失时 android_entry 静默降级, 不影响主流程.
"""
import asyncio
import base64
import json
import os
import threading
import time

import service_config

NAME = 'pc'                                       # rooms 文件里的本机命名槽位
GA_DIR = os.environ.get('GA_DIR') or os.path.dirname(os.path.abspath(__file__))
ROOMS = os.path.join(GA_DIR, 'pclink_rooms.json')



_lk = threading.Lock()
_loop = None          # 常驻后台事件循环(独立线程), 首次使用时惰性启动
_sock = None          # 当前 P2PSocket, 断线置 None 由 keeper 重连
_sock_config = None
_pending = {}         # req id -> Future(res frame)
_seq = [0]
_err = ['']           # 最近一次连接/收发错误(给前端展示)
_tmo = [0]            # 连续超时计数: 只用于判半开连接, 详见 _api
_wake = [None]        # keeper 的唤醒事件: 断线时 set, 免等 2s 轮转
_last_rx = [float('-inf')]
_resume_at = [float('-inf')]
_resume_busy = [False]


def _paired():
    try:
        import p2p_ws_client as p2p
        p2p.load_room(NAME, path=ROOMS)
        return True
    except Exception:
        return False


def _ensure_loop():
    global _loop
    with _lk:
        if _loop is None or not _loop.is_running():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name='pclink', daemon=True).start()
            asyncio.run_coroutine_threadsafe(_keeper(), loop)
            _loop = loop
        return _loop


async def _keeper():
    """断线自动重连: 已配对且无连接时 connect_saved, 指数退避封顶 15s(回前台不久等).
    断线由 _wake 事件立即唤醒; 退避带随机抖动, 避免服务器重启后千台同时冲."""
    import random
    import p2p_ws_client as p2p
    ev = _wake[0] = asyncio.Event()
    backoff = 3
    while True:
        ev.clear()
        delay = 2
        try:
            config = service_config.pclink_config()
            if _sock is not None and config != _sock_config:
                await _drop(_sock)
            if config and _sock is None and _paired():
                saved = p2p.load_room(NAME, path=ROOMS)
                if saved['signal_url'] != config['url']:
                    raise ValueError('Relay address changed; pair again before reconnecting')
                s = await p2p.connect_saved(NAME, path=ROOMS, access_key=config['token'])
                if service_config.pclink_config() != config:
                    await s.close()
                    continue
                _attach(s, config)
                backoff = 3
        except Exception as e:
            _err[0] = str(e)[:200]
            delay = backoff * random.uniform(0.5, 1.5)
            backoff = min(backoff * 2, 15)
        try:
            await asyncio.wait_for(ev.wait(), delay)   # 回前台可打断退避，仍只有 keeper 建连
            backoff = 3
        except asyncio.TimeoutError:
            pass


def _attach(s, config):
    global _sock, _sock_config
    _sock = s
    _sock_config = dict(config)
    _err[0] = ''
    _tmo[0] = 0        # 半开判定只对「同一条连接」的连续超时成立, 换新连接从零计
    _last_rx[0] = time.monotonic()  # 刚完成双端握手，无需再探活
    asyncio.ensure_future(_receiver(s))


async def _receiver(s):
    """独占消费 recv(): 只认 p2p-http.res, 按 id 回填 Future."""
    global _sock
    try:
        while True:
            data = await s.recv()
            try:
                m = json.loads(data)
            except Exception:
                continue
            if isinstance(m, dict) and m.get('type') == 'p2p-http.res':
                f = _pending.pop(str(m.get('id')), None)
                if f is not None and not f.done():
                    if _sock is s:
                        _last_rx[0] = time.monotonic()
                    f.set_result(m)
    except Exception as e:
        if _sock is s:
            _err[0] = str(e)[:200]
    finally:
        await _drop(s)


async def _drop(s):
    """旧连接的迟到回调不得清理新连接的请求或唤醒其退避。"""
    global _sock, _sock_config
    if _sock is s:
        _sock = None
        _sock_config = None
        for f in list(_pending.values()):
            if not f.done():
                f.cancel()
        _pending.clear()
        if _wake[0] is not None:
            _wake[0].set()
    try:
        await s.close()
    except Exception:
        pass


async def _api(method, target, body, timeout=22, *, count_timeout=True):
    """默认 22s: 必须罩住 hub 侧 ask 的 15s 上限 + P2P 往返, 手机比 PC 晚放弃才能等到结构化错误."""
    s = _sock
    if s is None:
        raise RuntimeError('not connected')
    if service_config.pclink_config() != _sock_config:
        raise RuntimeError('Relay disabled or configuration changed')
    _seq[0] += 1
    rid = 'ga%d' % _seq[0]
    fut = asyncio.get_running_loop().create_future()
    _pending[rid] = fut
    frame = {'v': 1, 'type': 'p2p-http.req', 'id': rid, 'method': method, 'target': target,
             'headers': [['content-type', 'application/json']],
             'body': base64.b64encode((body or '').encode('utf-8')).decode('ascii')}
    try:
        try:
            await s.send(json.dumps(frame, separators=(',', ':')))
        except Exception:
            await _drop(s)              # 发不出去 = 连接真坏, 立即弃线让 keeper 重连
            raise
        try:
            res = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            if count_timeout and _sock is s:
                _tmo[0] += 1            # 业务超时仍沿用连续两次判死；前台探活单独确认
                if _tmo[0] >= 2:
                    _tmo[0] = 0
                    await _drop(s)
            raise
    finally:
        _pending.pop(rid, None)
    if _sock is s:
        _tmo[0] = 0                     # 旧请求不能改变新连接的计数
    raw = base64.b64decode(res.get('body') or b'')
    return {'ok': 1, 'status': int(res.get('status') or 0), 'body': raw.decode('utf-8', 'replace')}


async def _resume():
    """前台是一次恢复信号，不是心跳：30s 冷却、单飞、最近有响应则免探活。"""
    now = time.monotonic()
    if _resume_busy[0] or now - _resume_at[0] < 30:
        return
    s = _sock
    if s is not None and now - _last_rx[0] < 8:
        return
    _resume_at[0] = now
    if s is None:
        if _wake[0] is not None:
            _wake[0].set()              # 只唤醒现有 keeper，失败仍按原退避重试
        return
    _resume_busy[0] = True
    seen = _last_rx[0]
    try:
        for _ in range(2):
            if _sock is not s or _last_rx[0] != seen:
                return
            try:
                # Exporter 对白名单外路径直接回 403；不调用 hub 业务，但中继仍有转发成本。
                # 外层期限覆盖 send，避免探活先在发送阶段额外等待。
                await asyncio.wait_for(
                    _api('GET', '/__ping', '', count_timeout=False), 4)
                return
            except asyncio.TimeoutError:
                pass
            except Exception:
                return                 # send 失败由 _api 弃线，不重复建立连接
        if _sock is s and _last_rx[0] == seen:
            await _drop(s)              # 两次探活失败，且期间没有任何有效业务响应
    finally:
        _resume_busy[0] = False


async def _pair(code):
    """兑换 9 位配对码并接管连接(替换旧连接); UUID 自动落盘 ROOMS."""
    import p2p_ws_client as p2p
    config = service_config.pclink_config()
    if not config:
        raise ValueError('Configure PC Link in Settings > Optional modules first')
    if _sock is not None:
        await _drop(_sock)
    s = await p2p.connect_code(config['url'], code, name=NAME, rooms_file=ROOMS, access_key=config['token'])
    if service_config.pclink_config() != config:
        await s.close()
        raise ValueError('Relay configuration changed during pairing')
    _attach(s, config)


async def _unpair():
    if _sock is not None:
        await _drop(_sock)
    try:
        with open(ROOMS, 'r', encoding='utf-8') as f:
            d = json.load(f)
        d.pop(NAME, None)
        with open(ROOMS, 'w', encoding='utf-8') as f:
            json.dump(d, f)
    except Exception:
        try:
            os.remove(ROOMS)
        except Exception:
            pass


def _call(coro, timeout):
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop()).result(timeout)


def handle(text):
    """同步入口(android_entry 后台 job 线程里调用). text 形如:
    /pclink.status | /pclink.pair 123456789 | /pclink.unpair
    /pclink.api GET /api/peers | /pclink.api POST /api/x/put {"text":"hi"}"""
    try:
        cmd = text[len('/pclink.'):].strip()
        if cmd in ('status', 'resume'):
            config = service_config.pclink_config()
            if config and _paired():
                _ensure_loop()                    # 冷启动时顺手踢 keeper 开始重连
                if cmd == 'resume':
                    asyncio.run_coroutine_threadsafe(_resume(), _loop)
                # status 只读本地状态，不因 UI 轮询持续发网络探活。
            return json.dumps({'ok': 1, 'configured': bool(config), 'paired': _paired(),
                               'connected': _sock is not None, 'err': _err[0],
                               'signal': config['url'] if config else ''})   # 回带当前信令入口: 配对失败时先看这里, 免去猜是不是配置没生效
        if cmd.startswith('pair '):
            _call(_pair(cmd[5:].strip()), 45)
            return json.dumps({'ok': 1, 'paired': True, 'connected': True})
        if cmd == 'unpair':
            _call(_unpair(), 15)
            return json.dumps({'ok': 1, 'paired': False, 'connected': False})
        if cmd.startswith('api '):
            p = cmd[4:].split(' ', 2)
            if len(p) < 2:
                return json.dumps({'ok': 0, 'error': 'usage: api METHOD /path [body]'})
            r = _call(_api(p[0].upper(), p[1], p[2] if len(p) > 2 else ''), 45)   # 45 > _api 默认 22: 外层只兜线程级意外
            if r['status'] < 400:
                return r['body']              # 成功直接透传 hub 的 JSON 响应体
            try:                              # hub 的 4xx 同样是结构化 JSON(offline/gone/busy/timeout/nosupport),
                d = json.loads(r['body'])     # 只回 http NNN 会让这些可行动语义在端侧蒸发
                d = d if isinstance(d, dict) else {}
            except Exception:
                d = {}                        # 非 JSON(如 Exporter 自身的 403 文本)按状态码兜底
            return json.dumps({'ok': 0, 'status': r['status'], 'code': d.get('code', ''),
                               'error': d.get('error') or 'http %s' % r['status']}, ensure_ascii=False)
        return json.dumps({'ok': 0, 'error': 'unknown pclink cmd'})
    except Exception as e:
        return json.dumps({'ok': 0, 'error': str(e)[:200] or type(e).__name__}, ensure_ascii=False)


def _signal():
    config = service_config.pclink_config()
    return config['url'] if config else ''
