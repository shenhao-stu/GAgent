"""pclink — 手机端连接 PC hub 的可选静默功能(android_entry /pclink.* 分发到此).

原理: PC 端 hub.py(hub_p2p) 把 /api/ 以 HTTPExporter 挂在 P2P socket 上;
本模块作为对端, 直接在 socket 上收发 p2p-http.req/res 帧(不起本地 HTTP 服务,
省掉 aiohttp server), 把 hub API 变成同步可调的 handle('/pclink.api GET /api/peers').
配对码 → connect_code 自动把 room UUID 存 GA_DIR/pclink_rooms.json, 之后
后台 keeper 线程 connect_saved 自动重连, App 重启免配对.
本文件不存在或依赖缺失时 android_entry 静默降级, 不影响主流程.

agent 用法(code_run 里 import pclink; 返回 JSON 字符串, 未配对/未连上时 ok=0 带 error):
  pclink.handle('/pclink.status')                         # 是否已连上 PC hub
  pclink.handle('/pclink.api GET /api/peers')             # PC 上在线的 GA 及是否在跑
  pclink.handle('/pclink.api POST /api/{name}/put {"text":"任务"}')   # 给空闲 GA 派任务(只说意图)
  pclink.handle('/pclink.api GET /api/{name}/messages')   # 读对话/进度, 轮询到完成
    # 注意: messages 的 step 只有 {j, title(摘要), n(全文长度)}, 不是全文; 取全文:
    #   GET /api/{name}/seg/{i}/{j}?off=N  -> {content, off, n}, content 为 off 起的全文;
    #   i/j 用 messages 里的序号(负数从末尾数); 生成中可传上次 n 只拉增量; 被清则 code:gone
  POST /api/{name}/intervene|keyinfo {"text":..}  运行中插话 | POST /api/{name}/abort 中止
  GET /api/{name}/llms | POST /api/{name}/llm {"no":N}  查看/切换模型
多 hub: 同一 UUID 下升级过的 hub 都进大厅, 本机以 cust: 成员自动连上全部 hub,
  会话名为 name@hub; GET /api/hubs 列在线 hub; POST /api/sessions {"hub":..} 选机。
  组里没有 hub(对端未升级)时退回旧 1 对 1, 用法不变。
单次请求约 22s 超时: 长任务 put 后轮询 messages, 不要阻塞等.
"""
import asyncio
import base64
import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import TimeoutError as FutureTimeoutError

import service_config

NAME = 'pc'                                       # rooms 文件里的本机命名槽位
GA_DIR = os.environ.get('GA_DIR') or os.path.dirname(os.path.abspath(__file__))
ROOMS = os.path.join(GA_DIR, 'pclink_rooms.json')


def _config():
    config = service_config.pclink_config()
    if not config:
        raise RuntimeError('PC Link is disabled; configure it in Optional modules first')
    return config


def _signal():
    return _config()['url']


_lk = threading.Lock()
_loop = None          # 常驻后台事件循环(独立线程), 首次使用时惰性启动
_sock_config = None
_sock = None          # 当前 P2PSocket, 断线置 None 由 keeper 重连
_connection_task = None  # 配对、重连、解除共用一个在飞操作，替换前先完成旧连接清理
_closing = set()       # receiver / API 弃线也必须先释放房间，才能重连
_pending = {}         # req id -> Future(res frame)
_seq = [0]
_err = ['']           # 最近一次连接/收发错误(给前端展示)
_tmo = [0]            # 连续超时计数: 只用于判半开连接, 详见 _api
_wake = [None]        # keeper 的唤醒事件: 断线时 set, 免等 2s 轮转
_last_rx = [float('-inf')]
_resume_at = [float('-inf')]
_resume_busy = [False]
_group_lock = asyncio.Lock()
_group = [None, None, None]  # (room, Group 任务, HubUnion)


def _hubs():
    return _group[2].live() if _group[2] else set()   # 含宽限期内重连中的 hub: 不回退旧 1 对 1, 不报断线


async def _sync_group(config):
    async with _group_lock:
        return await _replace_group(config)


async def _replace_group(config):
    """已配对就以 cust: 成员进同一 UUID 的大厅, 自动连所有 hub:; 换房/解除时重建。返回是否新起。"""
    import p2p_ws_client as p2p
    try:
        saved = p2p.load_room(NAME, path=ROOMS)
    except Exception:
        saved = None
    room = saved and saved.get('room') if config else None
    if room and saved.get('signal_url') != config['url']:
        room = None
    identity = (room, config['url'], config['token']) if room else None
    if identity == _group[0]:
        return False
    previous = _group[1]
    _group[:] = [None, None, None]
    if previous:
        previous.cancel()
        await _finish_cleanup(asyncio.gather(previous, return_exceptions=True))
    if config is not None and service_config.pclink_config() != config:
        return False
    _group[0] = identity
    if room:
        union = p2p.HubUnion()

        async def ignore(socket, peer):  # hub 只主叫 hub:, 不会呼叫 customer
            pass
        group = p2p.Group(saved['signal_url'], room, 'cust:android-' + uuid.uuid4().hex[:8],
                          ignore, union.use, auto=('hub:',), access_key=config['token'])
        _group[1:] = [asyncio.ensure_future(group.run()), union]
    return bool(room)


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
            if await _sync_group(config):
                for _ in range(15):
                    if _hubs(): break
                    await asyncio.sleep(0.1)
            if _hubs():
                if _sock is not None and _connection_task is None:
                    await _drop(_sock)
            elif config and _sock is None and _connection_task is None and not _closing and _paired():
                saved = p2p.load_room(NAME, path=ROOMS)
                if saved['signal_url'] != config['url']:
                    raise ValueError('Relay address changed; pair again before reconnecting')
                await _change_connection(lambda: p2p.connect_saved(NAME, path=ROOMS, access_key=config['token']), config)
                backoff = 3
        except Exception as exc:
            _err[0] = str(exc)[:200]
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
            if _sock is s and isinstance(m, dict) and m.get('type') == 'p2p-http.res':
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
    global _sock
    if _sock is s:
        _sock = None
        for f in list(_pending.values()):
            if not f.done():
                f.cancel()
        _pending.clear()
    closing = asyncio.create_task(s.close())
    _closing.add(closing)
    try:
        await _finish_cleanup(closing)
    except Exception:
        pass
    finally:
        _closing.discard(closing)
        if _sock is None and _wake[0] is not None:
            _wake[0].set()


async def _finish_cleanup(task):
    """取消可以换掉连接所有者，不能中断旧连接退出房间。"""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        raise asyncio.CancelledError
    return task.result()


async def _api(method, target, body, timeout=22, *, count_timeout=True):
    """默认 22s: 必须罩住 hub 侧 ask 的 15s 上限 + P2P 往返, 手机比 PC 晚放弃才能等到结构化错误."""
    config = _config()
    if _group[0] and _group[0][1:] != (config['url'], config['token']):
        raise RuntimeError('PC Link configuration changed; reconnect first')
    if _sock is not None and _sock_config != config:
        raise RuntimeError('PC Link configuration changed; reconnect first')
    if _hubs():
        status, data = await asyncio.wait_for(
            _group[2].request(method, target, (body or '').encode('utf-8')), timeout)
        return {'ok': 1, 'status': status, 'body': data.decode('utf-8', 'replace')}
    s = _sock
    if s is None:
        raise RuntimeError('not connected')
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
    """断线立即唤醒；只有健康探活受 30s 冷却、单飞和最近响应限制。"""
    s = _sock
    if s is None:
        if _wake[0] is not None:
            _wake[0].set()              # 只唤醒现有 keeper，不创建并发拨号
        return
    now = time.monotonic()
    if _resume_busy[0] or now - _resume_at[0] < 30 or now - _last_rx[0] < 8:
        return
    _resume_at[0] = now
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


async def _change_connection(operation, config=None):
    """只有当前操作可以接管 socket；旧握手须退出房间后才能开始新握手。"""
    global _connection_task
    previous = _connection_task

    async def change():
        if previous is not None:
            previous.cancel()
            await _finish_cleanup(asyncio.gather(previous, return_exceptions=True))
        if _sock is not None:
            await _drop(_sock)
        if _closing:
            await _finish_cleanup(asyncio.gather(*_closing, return_exceptions=True))
        sock = await operation()
        if (_connection_task is not asyncio.current_task()
                or config is not None and service_config.pclink_config() != config):
            if sock is not None:
                await _drop(sock)
            raise ConnectionError('connection replaced')
        if sock is not None:
            _attach(sock, config)

    task = _connection_task = asyncio.create_task(change())
    try:
        await task
    except asyncio.CancelledError:
        if _connection_task is not task:
            raise ConnectionError('connection replaced') from None
        raise
    finally:
        if _connection_task is task:
            _connection_task = None


async def _pair(code):
    """兑换 9 位配对码并接管连接(替换旧连接); UUID 自动落盘 ROOMS."""
    import p2p_ws_client as p2p
    config = _config()
    await _change_connection(lambda: p2p.connect_code(
        config['url'], code, name=NAME, rooms_file=ROOMS, access_key=config['token']), config)
    await _sync_group(config)


async def _unpair():
    await _change_connection(_forget_room)
    await _sync_group(None)


async def _forget_room():
    try:
        with open(ROOMS, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except FileNotFoundError:
        return
    d.pop(NAME, None)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(ROOMS), prefix='.pclink-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.replace(temporary, ROOMS)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    _err[0] = ''


def _call(coro, timeout):
    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    try:
        return future.result(timeout)
    except FutureTimeoutError:
        future.cancel()
        raise


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
                               'connected': _sock is not None or bool(_hubs()),
                               'hubs': sorted(_hubs()), 'err': _err[0],
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
