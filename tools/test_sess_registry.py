#!/usr/bin/env python3
import os, sys, glob, json, time, queue, shutil, tempfile, threading, types

GA = tempfile.mkdtemp(prefix='ga_sessreg_')
os.environ['GA_DIR'] = GA
# 强制 zh: 本 harness 的断言写死中文文案(T14 cmd_error / T29 abort 等)。
# setdefault 会被父进程 GA_LANG=en 穿透, 导致 _L 回英文、假红。
os.environ['GA_LANG'] = 'zh'
os.makedirs(os.path.join(GA, 'temp', 'model_responses'), exist_ok=True)
open(os.path.join(GA, 'mykey.py'), 'w').write('keys=[]\n')

GACORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app', 'src', 'main', 'assets', 'gacore')
sys.path.insert(0, os.path.abspath(GACORE))
import android_entry as ae

FAILURES = []


def check(cond, msg):
    if not cond: FAILURES.append(msg)
    return bool(cond)


class FakeBackend:
    def __init__(self):
        self.history = []
        self.model = 'fake-model'
        self.name = 'fake'


class FakeClient:
    def __init__(self):
        self.backend = FakeBackend()
        self.log_path = None


class FakeHandler:
    def __init__(self, parent, key_info='KI', passed=2):
        self.parent = parent
        self.working = {'key_info': key_info, 'passed_sessions': passed}
        self.code_stop_signal = []
        self.history_info = []


class FakeAgent:
    ALL = []

    def __init__(self):
        self.lock = threading.Lock()
        self.task_queue = queue.Queue()
        self.is_running = False
        self.stop_sig = False
        self.llm_no = 0
        self.llmclient = FakeClient()
        self.llmclients = [self.llmclient]
        self.history = []
        self.handler = None
        self.task_dir = None
        self.log_path = os.path.join(GA, 'temp', 'model_responses', 'model_responses_seed.txt')
        self.received = []
        self.hang = False
        self.never_stop = False
        self.stopped = False
        FakeAgent.ALL.append(self)

    def put_task(self, query, source='user', images=None):
        dq = queue.Queue()
        self.task_queue.put({'query': query, 'source': source, 'images': images or [], 'output': dq})
        return dq

    def abort(self):
        if not self.is_running: return
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
        if not self.never_stop: self.is_running = False

    def run(self):
        while True:
            task = self.task_queue.get()
            if isinstance(task, str):
                self.stopped = True
                return
            q, dq = task['query'], task['output']
            self.received.append(q)
            if q.startswith('/llm') or q.startswith('/session.'):
                bad = 'BAD' in q
                dq.put({'done': ('未找到 LLM: BAD' if bad else '✅ ok'), 'source': 'system', 'turn': 0, 'outputs': []})
                continue
            self.is_running = True
            self.stop_sig = False
            self.history.append('[USER]: ' + q)
            self.llmclient.backend.history.append({'role': 'user', 'content': q})
            if self.hang:
                while not self.stop_sig: time.sleep(0.01)
                self.is_running = False
                dq.put({'done': '(aborted)', 'source': 'user', 'turn': 1, 'outputs': ['o1']})
                continue
            dq.put({'next': 'o1', 'source': 'user', 'turn': 1, 'outputs': ['o1']})
            self.llmclient.backend.history.append({'role': 'assistant', 'content': 'r:' + q})
            self.is_running = False
            dq.put({'done': 'final:' + q, 'source': 'user', 'turn': 1, 'outputs': ['o1']})


_fake_mod = types.ModuleType('agentmain')
_fake_mod.GenericAgent = FakeAgent
sys.modules['agentmain'] = _fake_mod


def wait_until(pred, t=4.0):
    end = time.time() + t
    while time.time() < end:
        if pred(): return True
        time.sleep(0.01)
    return pred()


def sessions_dir():
    return os.path.join(GA, 'temp', 'model_responses', 'sessions')


def sessions_files():
    return sorted(glob.glob(os.path.join(sessions_dir(), 'session_*.json')))


def chat_json():
    return os.path.join(GA, 'chat.json')


def reset():
    time.sleep(0.15)
    ae._reset_convos()
    with ae._hist_lock:
        ae._hist[:] = []
    with ae._preset_lock:
        ae._PRESET_CMDS.clear()
    try: os.remove(chat_json())
    except OSError: pass
    shutil.rmtree(sessions_dir(), ignore_errors=True)
    FakeAgent.ALL[:] = []


def bh_of(s):
    return ae._sess_agent(s).llmclient.backend.history


def agent_of(cid):
    return ae._sess_agent(ae._REG[cid])


def enter(cid):
    r = ae._switch_convo(cid)
    ae._focus(True)
    return r


def reaches(obj, target, depth=6, seen=None):
    if seen is None: seen = set()
    if obj is target: return True
    if depth <= 0 or id(obj) in seen: return False
    seen.add(id(obj))
    if isinstance(obj, dict):
        return any(reaches(v, target, depth - 1, seen) for v in list(obj.keys()) + list(obj.values()))
    if isinstance(obj, (list, tuple, set, frozenset)):
        return any(reaches(v, target, depth - 1, seen) for v in obj)
    d = getattr(obj, '__dict__', None)
    if isinstance(d, dict): return reaches(d, target, depth - 1, seen)
    return False


def t01_switch_return_values():
    reset()
    check(ae._switch_convo('') == 'same', 'T01 空 cid 应回 same')
    r = ae._switch_convo('s1')
    check(r == 'pending', 'T01 冷启(注册表空)应回 pending, 实回 ' + repr(r))
    ae.send('hi')
    check(wait_until(lambda: not ae._REG[ae._focus_cid].state['running']), 'T01 首发未完成')
    check(ae._switch_convo('s1') == 'same', 'T01 同 cid 应回 same')
    check(ae._switch_convo('s2') == 'ok', 'T01 正常切换应回 ok')

    s2 = ae._REG['s2']
    a2 = ae._sess_agent(s2)
    with ae._lock: s2.state['running'] = True
    a2.is_running = True
    a2.never_stop = False
    check(ae._switch_convo('s3') == 'ok', 'T01/FIX-7 焦点在跑但能 quiesce 时必须回 ok(不再是 busy)')

    ae._switch_convo('s2')
    with ae._lock: s2.state['running'] = True
    a2.is_running = True
    a2.never_stop = True
    orig = ae._quiesce_agent
    ae._quiesce_agent = lambda a, timeout=0.2: orig(a, timeout)
    try:
        check(ae._switch_convo('s4') == 'busy', 'T01/FIX-7 quiesce 失败时才回 busy')
    finally:
        ae._quiesce_agent = orig
    a2.never_stop = False
    a2.is_running = False
    with ae._lock: s2.state['running'] = False


def t02_no_bleed_and_identity():
    reset()
    enter('a')
    ae.send('qa')
    check(wait_until(lambda: not ae._REG['a'].state['running']), 'T02 a 任务未完成')
    sa, aa = ae._REG['a'], ae._REG['a'].agent
    check(len(bh_of(sa)) == 2, 'T02 a 的 backend.history 应有一对')

    check(ae._switch_convo('b') == 'ok', 'T02 切 b 失败')
    sb = ae._REG['b']
    check(sb is not sa and sb.agent is not aa, 'T02 b 必须是独立 Sess+agent')
    check(bh_of(sb) == [], 'T02 串会话: b 带了 a 的上下文')
    ae.send('qb')
    check(wait_until(lambda: not sb.state['running']), 'T02 b 任务未完成')

    check(ae._switch_convo('a') == 'ok', 'T02 切回 a 失败')
    check(ae._REG['a'] is sa and ae._REG['a'].agent is aa, 'T02 切回 a 应是同一 Sess/agent 对象(未被换血)')
    check([m['content'] for m in bh_of(sa)] == ['qa', 'r:qa'], 'T02 切回 a 上下文被污染: ' + repr(bh_of(sa)))
    check(ae._state is sa.state and ae.agent is aa, 'T02 焦点模块名未绑到 a')


def t03_bind_convo_same_source():
    reset()
    enter('b1')
    s = ae._REG['b1']
    check(ae._bind_convo('b2') == 'bound', 'T03 bind 应回 bound')
    check(ae._focus_cid == 'b2', 'T03 _focus_cid 未改挂名')
    check(ae._REG.get('b2') is s and 'b1' not in ae._REG, 'T03 Sess 本体应原样改挂名')
    check(s.cid == 'b2', 'T03 s.cid 未改')
    check(ae._state is s.state and ae.agent is s.agent, 'T03 改挂名后 _focus_cid 与模块 _state 不同源')

    reset()
    check(ae._focus_sess() is None, 'T03 reset 后焦点应为 None')
    check(ae._bind_convo('z1') == 'bound', 'T03 焦点为 None 时 bind 应回 bound')
    check(ae._focus_cid == 'z1', 'T03 焦点为 None 时 _focus_cid 未设')
    tgt = ae._REG.get('z1')
    check(tgt is not None and ae._state is tgt.state and ae.agent is tgt.agent,
          'T03/FIX-9 焦点为 None 时 bind 后 _focus_cid 与模块 _state 不同源')

    reset()
    enter('y1')
    sy = ae._REG['y1']
    with ae._lock: sy.retired = True
    ae._bind_convo('y2')
    check(ae._REG.get('y2') is not sy, 'T03/F9 已 retired 的 Sess 不得被 _bind_convo 复活挂名')
    with ae._lock: sy.retired = False


HEAD_POLL_KEYS = {'running', 'status', 'gen', 'final', 'prompt', 'nsteps', 'steps', 'cmd_error',
                  'tok_in', 'tok_out', 'cache_read', 'cache_write', 'ask', 'route', 'active_convo',
                  'elapsed', 'lang', 'hist', 'cid', 'tool_events',
                  'end',   # end: 结束原因 done/stopped/error(悬浮窗区分中止/出错与完成); 旧客户端忽略未知键
                  'llm'}   # llm: 本任务主模型请求计时(首包/首 token/上下文规模/重试), 只观察


def t04_poll_contract():
    reset()
    enter('p')
    ae.send('qp')
    check(wait_until(lambda: not ae._REG['p'].state['running']), 'T04 任务未完成')
    d0 = json.loads(ae.poll('0'))
    check(set(d0.keys()) == HEAD_POLL_KEYS, 'T04 poll(since=0) 键集与 HEAD 不一致: ' +
          repr(sorted(set(d0.keys()) ^ HEAD_POLL_KEYS)))
    d1 = json.loads(ae.poll('1'))
    check(set(d1.keys()) == HEAD_POLL_KEYS - {'hist'}, 'T04 poll(since=1) 键集与 HEAD 不一致: ' +
          repr(sorted(set(d1.keys()) ^ (HEAD_POLL_KEYS - {'hist'}))))
    check(d0['active_convo'] == 'p', 'T04 active_convo 应为焦点 cid')
    with ae._notif_lock:
        ae._notif_pending = {'p': ae.deque([{'cid': 'p', 'app': 'x'}])}
    d2 = json.loads(ae.poll('0'))
    check(set(d2.keys()) == HEAD_POLL_KEYS | {'notif_pending'}, 'T04 notif_pending 加键不符')
    check(json.loads(ae.poll('0')).get('notif_pending') is None, 'T04 notif_pending 应一次性')


def t05_patches_direct_write_and_lock_identity():
    reset()
    lock0 = ae._lock
    enter('w1')
    with ae._lock:
        ae._state['tok_in'] = ae._state.get('tok_in', 0) + 11
    enter('w2')
    with ae._lock:
        ae._state['tok_in'] = ae._state.get('tok_in', 0) + 22
    check(ae._REG['w1'].state['tok_in'] == 11, 'T05 w1 的 tok_in 被串写: ' + repr(ae._REG['w1'].state['tok_in']))
    check(ae._REG['w2'].state['tok_in'] == 22, 'T05 w2 的 tok_in 不对: ' + repr(ae._REG['w2'].state['tok_in']))
    check(ae._lock is lock0, 'T05/FIX-1 _lock 对象被重新赋值(必须全进程恒定)')
    check(ae._REG['w1'].lock is lock0 and ae._REG['w2'].lock is lock0, 'T05/FIX-1 Sess.lock 必须共用模块级那把')
    check(isinstance(lock0, type(threading.RLock())), 'T05/FIX-1 _lock 必须是 RLock')


def t06_clear_invalidates_inflight_drain():
    reset()
    enter('c1')
    ae.send('qc')
    check(wait_until(lambda: not ae._REG['c1'].state['running']), 'T06 前置任务未完成')
    check(wait_until(lambda: os.path.exists(chat_json())), 'T06 前置: chat.json 应已生成')
    check(wait_until(lambda: len(sessions_files()) == 1), 'T06 前置: 会话快照应已生成')

    sess = ae._REG['c1']
    gate = threading.Event()
    parked = threading.Event()

    class GatedSess(ae._Sess):
        @property
        def last_active(self):
            return self.__dict__.get('_la', 0)

        @last_active.setter
        def last_active(self, v):
            self.__dict__['_la'] = v
            if gate_on[0]:
                parked.set()
                gate.wait(5.0)

    gate_on = [False]
    sess.__dict__['_la'] = sess.last_active
    sess.__class__ = GatedSess

    dq = queue.Queue()
    with ae._lock:
        sess.state.update(running=True, prompt='ghost', steps=[], final='')
        mygen = sess.state['gen']
    gate_on[0] = True
    th = threading.Thread(target=ae._drain, args=(dq, mygen, sess), daemon=True)
    th.start()
    dq.put({'done': 'late-final', 'source': 'user', 'turn': 3, 'outputs': ['x']})
    check(parked.wait(5.0), 'T06 前置: _drain 未进入 done 后置阶段')

    check(ae._cmd_clear('/clear') == 'cleared', 'T06 /clear 未返回 cleared')
    dir_after_clear = os.path.isdir(sessions_dir())
    gate.set()
    th.join(5.0)
    gate_on[0] = False
    sess.__class__ = ae._Sess

    check(not th.is_alive(), 'T06/FIX-5 陈旧 _drain 未退出')
    check(not os.path.exists(chat_json()), 'T06/C2 在飞 _drain 在 /clear 后重建了 chat.json')
    check(sessions_files() == [], 'T06/C2 在飞 _drain 在 /clear 后重建了 session_<cid>.json')
    check(os.path.isdir(sessions_dir()) == dir_after_clear,
          'T06/C2 在飞 _drain 在 /clear 后重建了 sessions/ 目录')
    check(os.listdir(sessions_dir()) == [] if os.path.isdir(sessions_dir()) else True,
          'T06/C2 /clear 后 sessions/ 目录不应有任何残留')
    with ae._hist_lock:
        check(ae._hist == [], 'T06/FIX-4 陈旧 _drain 污染了 _hist')


def t07_retire_atomic_concurrent():
    reset()
    enter('r1')
    enter('r2')
    s = ae._REG['r1']
    with ae._lock: s.state['running'] = True
    check(ae._retire_sess('r1') is False, 'T07/FIX-3 running 会话不得被回收')
    check(ae._REG.get('r1') is s and not s.retired, 'T07/FIX-3 拒绝回收后不得摘表/标 retired')
    g0 = s.state['gen']

    res = []
    res_lock = threading.Lock()
    start = threading.Event()

    def worker():
        start.wait(3.0)
        r = ae._retire_sess('r1', persist=False, force=True)
        with res_lock: res.append(r)

    ths = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for t in ths: t.start()
    start.set()
    for t in ths: t.join(5.0)
    check(all(not t.is_alive() for t in ths), 'T07 并发 retire 线程未全部退出')
    check(len(res) == 8, 'T07 并发 retire 结果数不对: ' + repr(res))
    check(res.count(True) == 1, 'T07/FIX-3 并发 force 回收必须恰好一个成功: ' + repr(res))
    check(s.retired and 'r1' not in ae._REG, 'T07 force 回收后应标 retired 并摘表')
    check(s.state['gen'] != g0, 'T07/FIX-4 force 回收必须打新 gen 作废在飞 drain')
    check(s.state['running'] is False, 'T07/FIX-4 force 回收必须落 running')


def t08_no_zombie_drain():
    reset()
    enter('h1')
    s = ae._REG['h1']
    s.agent.hang = True
    s.agent.handler = FakeHandler(s.agent)
    s.agent.put_task('blocker')
    check(wait_until(lambda: s.agent.is_running), 'T08 blocker 未开跑')

    dq = s.agent.put_task('queued-never-consumed')
    with ae._lock:
        s.state['running'] = True
        mygen = s.state['gen']
    th = threading.Thread(target=ae._drain, args=(dq, mygen, s), daemon=True)
    th.start()
    time.sleep(0.2)
    check(th.is_alive(), 'T08 前置: drain 应正在等 chunk')

    t0 = time.time()
    ae._retire_sess('h1', persist=False, force=True)
    th.join(2.0)
    check(not th.is_alive(), 'T08/FIX-5 哨兵回收后 _drain 未在 2s 内退出(僵尸线程)')
    check(time.time() - t0 < 2.5, 'T08 _drain 退出超时')
    check(dq.empty(), 'T08 前置: 该任务确实无人产出 chunk')
    check(wait_until(lambda: s.agent.stopped), 'T08 worker 未被哨兵干净收尾')
    check(s.agent.handler.code_stop_signal != [],
          'T08/N7 回收未走 abort(), 在飞 code_run 收不到中断信号')


def t09_preset_replay():
    reset()
    enter('m1')
    a1 = ae._REG['m1'].agent
    ae.send('/llm example-provider')
    check(wait_until(lambda: '/llm example-provider' in a1.received), 'T09 前置: m1 未收到 /llm')
    ae.send('/session.reasoning_effort=high')
    check(wait_until(lambda: '/session.reasoning_effort=high' in a1.received), 'T09 前置: m1 未收到 /session')

    check(ae._switch_convo('m2') == 'ok', 'T09 切 m2 失败')
    a2 = agent_of('m2')
    ae.send('hello')
    check(wait_until(lambda: 'hello' in a2.received), 'T09 m2 未收到用户任务')
    check('/llm example-provider' in a2.received, 'T09/FIX-6 新会话未重放 /llm(会跑在错误 provider 上)')
    check('/session.reasoning_effort=high' in a2.received, 'T09/FIX-6 新会话未重放 /session.*')
    check(a2.received.index('/llm example-provider') < a2.received.index('hello'),
          'T09/FIX-6 重放必须排在用户第一条消息之前: ' + repr(a2.received))
    check(a2.received.index('/llm example-provider') < a2.received.index('/session.reasoning_effort=high'),
          'T09/FIX-6 重放未按记录顺序: ' + repr(a2.received))


def t10_vars_survive_eviction_without_pinning_agent():
    reset()
    enter('v1')
    s1 = ae._REG['v1']
    a1 = s1.agent
    h1 = FakeHandler(a1, key_info='KI-V1', passed=3)
    a1.handler = h1
    ae.send('qv')
    check(wait_until(lambda: not s1.state['running']), 'T10 前置任务未完成')
    check(wait_until(lambda: sessions_files() != []), 'T10 前置: v1 快照未落盘')

    for i in range(ae._SESS_KEEP + 3):
        ae._switch_convo('e%d' % i)
    check('v1' not in ae._REG, 'T10 前置: v1 应已被 _SESS_KEEP 淘汰')

    snap = ae._VARS.get('v1')
    check(snap is not None, 'T10 前置: v1 快照未进 _VARS')
    check(not reaches(snap, a1), 'T10/N1 _VARS 快照仍可达活的 agent 对象(整条对象图被钉住→OOM)')
    check(not reaches(snap, h1), 'T10/N1 _VARS 快照仍持有真 handler 对象')
    check(snap.get('history') is not a1.history, 'T10/N1 list 成员未浅拷贝(与活 list 共享)')

    check(ae._switch_convo('v1') == 'ok', 'T10 切回 v1 失败')
    s2 = ae._REG['v1']
    check(s2 is not s1 and s2.agent is not a1, 'T10 前置: 淘汰后切回应是新建的 Sess/agent')
    h2 = ae._sess_agent(s2).handler
    check(h2 is not None and not isinstance(h2, FakeHandler), 'T10/N1 装回的应是替身而非真 handler: ' + repr(h2))
    check(not hasattr(h2, 'parent'), 'T10/N1 替身不得带 parent(否则仍钉住整个 GenericAgent)')
    check(getattr(h2, 'working', None) == {'key_info': 'KI-V1', 'passed_sessions': 3},
          'T10/FIX-8 工作记忆未随快照存活: ' + repr(getattr(h2, 'working', None)))
    check(isinstance(getattr(h2, 'code_stop_signal', None), list),
          'T10/N1 替身缺 code_stop_signal(agentmain.abort 会炸)')
    check([m['content'] for m in bh_of(s2)] == ['qv', 'r:qv'], 'T10 淘汰后切回 LLM 上下文未从磁盘回灌: ' +
          repr(bh_of(s2)))


def t11_bare_llm_not_recorded():
    reset()
    enter('n1')
    a1 = ae._REG['n1'].agent
    ae.send('/llm')
    check(wait_until(lambda: '/llm' in a1.received), 'T11 前置: n1 未收到裸 /llm')
    time.sleep(0.2)
    with ae._preset_lock:
        keys = dict(ae._PRESET_CMDS)
    check('llm' not in keys, 'T11/N2 裸 /llm 被记成预设(每个新会话都会重放成真实 LLM 轮): ' + repr(keys))
    check(ae._record_preset('/llm') is None, 'T11/N2 _record_preset 不得接受裸 /llm')
    check(ae._record_preset('/llm   ') is None, 'T11/N2 _record_preset 不得接受空参 /llm')
    check(ae._record_preset('/llmfoo bar') is None, 'T11/N2 _record_preset 不得接受 /llmfoo')
    check(ae._record_preset('/session.model=x') is not None, 'T11/N2 合法 /session.k=v 必须被记录')
    with ae._preset_lock:
        ae._PRESET_CMDS.clear()

    check(ae._switch_convo('n2') == 'ok', 'T11 切 n2 失败')
    a2 = agent_of('n2')
    ae.send('hello')
    check(wait_until(lambda: 'hello' in a2.received), 'T11 n2 未收到用户任务')
    check('/llm' not in a2.received, 'T11/N2 新会话重放了裸 /llm: ' + repr(a2.received))


def t12_failed_llm_does_not_overwrite_preset():
    reset()
    enter('k1')
    a1 = ae._REG['k1'].agent
    ae.send('/llm good_one')
    check(wait_until(lambda: '/llm good_one' in a1.received), 'T12 前置: 未收到 /llm good_one')
    check(wait_until(lambda: ae._PRESET_CMDS.get('llm') == '/llm good_one'), 'T12 前置: 成功的 /llm 未被记录')

    ae.send('/llm BAD_one')
    check(wait_until(lambda: '/llm BAD_one' in a1.received), 'T12 前置: 未收到 /llm BAD_one')
    check(wait_until(lambda: ae._PRESET_CMDS.get('llm') == '/llm good_one', 6.0),
          'T12/N3 失败的 /llm 覆盖了可用预设: ' + repr(ae._PRESET_CMDS.get('llm')))

    check(ae._switch_convo('k2') == 'ok', 'T12 切 k2 失败')
    a2 = agent_of('k2')
    ae.send('hello')
    check(wait_until(lambda: 'hello' in a2.received), 'T12 k2 未收到用户任务')
    check('/llm good_one' in a2.received, 'T12/N3 新会话未重放可用预设: ' + repr(a2.received))
    check('/llm BAD_one' not in a2.received, 'T12/N3 新会话重放了失败预设: ' + repr(a2.received))


def t13_focus_never_retired_without_force():
    reset()
    enter('g1')
    enter('g2')
    sg2 = ae._REG['g2']
    check(ae._focus_cid == 'g2', 'T13 前置: 焦点应为 g2')
    check(ae._retire_sess('g2') is False, 'T13/F1 焦点会话在 force=False 时必须拒绝回收')
    check(ae._REG.get('g2') is sg2 and not sg2.retired, 'T13/F1 拒绝后不得摘表/标 retired')
    check(ae._retire_sess('g1') is True, 'T13 非焦点空闲会话应可回收')
    check(ae._retire_sess('g2', persist=False, force=True) is True, 'T13 force 仍须能回收焦点(/clear 语义)')


def t14_send_after_concurrent_retire():
    reset()
    enter('sr0')
    s0 = ae._REG['sr0']
    held = []
    orig_put = s0.agent.put_task

    def spy(query, source='user', images=None):
        held.append((query, ae._lock._is_owned()))
        return orig_put(query, source, images)

    s0.agent.put_task = spy
    ae.send('lock-scoped')
    check(wait_until(lambda: not s0.state['running']), 'T14 前置: lock-scoped 任务未完成')
    rec = [h for h in held if h[0] == 'lock-scoped']
    check(rec and rec[0][1] is True,
          'T14/F2 put_task 必须与 retired 复检同处 sess.lock 内(否则 retire 哨兵可插到任务前): ' + repr(held))
    s0.agent.put_task = orig_put

    reset()
    enter('sr1')
    retired = ae._REG['sr1']
    with retired.lock: retired.retired = True
    result = ae._send_for(retired, 'after-retire')
    check(result == '', 'T14 retired send must use the command error channel')
    check(not any('after-retire' in a.received for a in FakeAgent.ALL),
          'T14 a retired session must never receive work')
    with retired.lock: retired.retired = False
    check('会话正在回收' in json.loads(ae.poll('1')).get('cmd_error', ''),
          'T14 retired rejection must be visible to the user')


def t15_dead_worker_resets_running():
    reset()
    enter('z1')
    s = ae._REG['z1']
    dead = threading.Thread(target=lambda: None, daemon=True)
    dead.start()
    dead.join()
    s.run_thread = dead

    dq = queue.Queue()
    with ae._lock:
        s.state.update(running=True, prompt='ghost', steps=[], final='', status='思考中')
        mygen = s.state['gen']
    th = threading.Thread(target=ae._drain, args=(dq, mygen, s), daemon=True)
    th.start()
    check(wait_until(lambda: not s.state['running'], 8.0),
          'T15/F5 worker 线程已死但 running 未被 _drain 复位(call_once 会永久 busy)')
    th.join(3.0)
    check(not th.is_alive(), 'T15/F5 worker 线程已死后 _drain 未退出(1Hz 空转)')
    check('!!!' in (s.state.get('final') or ''), 'T15/F5 未落终态错误: ' + repr(s.state.get('final')))
    check(ae._focus_busy() is False, 'T15/F5 复位后不得仍判定有任务在跑')


def t16_clear_busy_covers_non_focus_session():
    reset()
    enter('q1')
    enter('q2')
    s1 = ae._REG['q1']
    with ae._lock: s1.state['running'] = True
    s1.agent.is_running = True
    s1.agent.never_stop = True
    ae.send('seed')
    check(wait_until(lambda: os.path.exists(chat_json())), 'T16 前置: chat.json 未生成')
    orig = ae._quiesce_agent
    ae._quiesce_agent = lambda a, timeout=0.2: orig(a, timeout)
    try:
        r = ae._cmd_clear('/clear')
    finally:
        ae._quiesce_agent = orig
    check(r == 'busy', 'T16/N4 非焦点会话在跑且停不下时 /clear 必须回 busy, 实回 ' + repr(r))
    check(ae._REG.get('q1') is s1 and not s1.retired, 'T16/N4 回 busy 时不得已经回收会话')
    check(os.path.exists(chat_json()), 'T16/N4 回 busy 时不得已经删聊天归档')
    s1.agent.never_stop = False
    s1.agent.is_running = False
    with ae._lock: s1.state['running'] = False


def t17_save_hist_outside_lock():
    reset()
    enter('sh1')
    s = ae._REG['sh1']
    seen = []
    orig = ae._save_hist
    ae._save_hist = lambda: (seen.append(ae._lock._is_owned()), orig())[1]
    try:
        ae.send('qs')
        check(wait_until(lambda: not s.state['running']), 'T17 前置任务未完成')
        check(wait_until(lambda: seen != []), 'T17 前置: _save_hist 未被调用')
    finally:
        ae._save_hist = orig
    check(all(x is False for x in seen),
          'T17/F6 _save_hist(多 MB json.dumps) 仍在进程级 _lock 内执行: ' + repr(seen))
    with ae._hist_lock:
        check(len(ae._hist) == 1, 'T17 归档条数不对: ' + repr(len(ae._hist)))
    check(os.path.exists(chat_json()), 'T17 chat.json 未落盘')


def t18_slow_boot_is_serialised_per_sess():
    reset()
    orig = ae._sess_boot

    def slow(s):
        if s.cid == 'slow1': time.sleep(0.9)
        orig(s)

    ae._sess_boot = slow
    got = []
    n0 = len(FakeAgent.ALL)
    try:
        s0 = ae._ensure_sess('slow1')
        ths = [threading.Thread(target=lambda: got.append(ae._sess_agent(s0))) for _ in range(3)]
        for t in ths: t.start()
        for t in ths: t.join(20)
    finally:
        ae._sess_boot = orig
    check(len(got) == 3, 'T18/B2 有调用方未返回(等待者被超时踢掉): ' + repr(len(got)))
    check(len(set(map(id, got))) == 1, 'T18/B2 慢构造期间等待者必须拿到同一个 agent')
    check(got and got[0] is not None, 'T18/B2 _sess_agent 不得回 None')
    check(ae._REG.get('slow1') is s0, 'T18/B2 注册表里必须就是这个 Sess')
    check(len(FakeAgent.ALL) - n0 == 1, 'T18/B2 只允许建一个 agent, 实建 ' + repr(len(FakeAgent.ALL) - n0))


def t19_boot_failure_propagates_and_retries():
    reset()
    s = ae._ensure_sess('boom1')
    orig = ae._sess_boot
    calls = [0]

    def boom(x):
        calls[0] += 1
        if calls[0] == 1: raise RuntimeError('boot exploded')
        orig(x)

    ae._sess_boot = boom
    try:
        err = None
        try: ae._sess_agent(s)
        except Exception as e: err = e
        check(err is not None, 'T19/B2 boot 失败必须让调用方拿到异常, 不能永久挂起')
        check(s.agent is None, 'T19/B2 boot 失败后不得留下半装好的 agent')
        a2 = ae._sess_agent(s)
        check(a2 is not None and s.agent is a2, 'T19/B2 失败后必须还能重试建成')
    finally:
        ae._sess_boot = orig


def t20_agent_is_published_last():
    reset()
    orig = ae._sess_boot
    seen = []

    def boot(s):
        def peek():
            for _ in range(400):
                a = s.agent
                if a is not None:
                    seen.append((a.log_path, list(a.llmclient.backend.history)))
                    return
                time.sleep(0.002)
        t = threading.Thread(target=peek, daemon=True)
        t.start()
        orig(s)
        t.join(3.0)

    ae._sess_boot = boot
    try:
        s = ae._ensure_sess('pub1')
        a = ae._sess_agent(s)
    finally:
        ae._sess_boot = orig
    check(seen, 'T20/B2 前置: 观察线程未看到 agent')
    check(seen and seen[0][0] == a.log_path,
          'T20/B2 快路径看到了 hydrate 之前的 agent(半装好状态外泄): ' + repr(seen[:1]))


def t21_focus_never_binds_unregistered():
    reset()
    enter('f1')
    orphan = ae._Sess('f1')
    ae._sess_boot(orphan)
    real = ae._ensure_sess
    box = {'n': 0}

    def fake(cid, wipe=False):
        box['n'] += 1
        if box['n'] == 1: return orphan
        return real(cid, wipe)

    ae._ensure_sess = fake
    try: s = ae._focus(True)
    finally: ae._ensure_sess = real
    check(s is not orphan, 'T21/R1c _focus 不得返回未在册的 Sess')
    check(ae.agent is not orphan.agent, 'T21/R1c 模块级 agent 不得绑到未在册的 Sess')
    check(ae._state is not orphan.state, 'T21/R1c 模块级 _state 不得绑到未在册的 Sess')
    ae._stop_sess_agent(orphan)


def _fresh_round(cid, gen_only=False):
    s = ae._REG[cid]
    with s.lock:
        g = ae._next_gen()
        s.state.update(gen=g, steps=[], prompt='p2', running=True, final='')
    return s, g


def t22_drain_uses_send_time_cid():
    reset()
    enter('A')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['A'].state['running']), 'T22 首任务未完成')
    s, g = _fresh_round('A')
    q = queue.Queue()
    q.put({'done': 'final:x', 'source': 'user', 'turn': 1, 'outputs': ['o1']})
    with ae._reg_lock:
        ae._REG.pop('A', None)
        s.cid = 'B'
        ae._REG['B'] = s
    ae._drain(q, g, s, 'A')
    with ae._hist_lock:
        last = ae._hist[-1] if ae._hist else {}
    check(last.get('convo') == 'A', 'T22/R2 归属必须是发送时刻的 cid, 实为 ' + repr(last.get('convo')))
    files = [os.path.basename(p) for p in sessions_files()]
    check('session_A.json' in files, 'T22/R2 必须落盘到发送时刻的会话: ' + repr(files))
    check('session_B.json' not in files, 'T22/R2 不得落盘到 bind 之后的新 cid: ' + repr(files))


def t23_bind_writes_no_disk():
    reset()
    enter('A')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['A'].state['running']), 'T23 首任务未完成')
    check(wait_until(lambda: sessions_files()), 'T23 首任务未落盘')
    shutil.rmtree(sessions_dir(), ignore_errors=True)
    ae._bind_convo('C')
    time.sleep(0.25)
    check(not sessions_files(), 'T23/R2 _bind_convo 必须是纯登记(与 HEAD 一致), 不得写盘: ' + repr(sessions_files()))


def t24_model_is_global_across_convos():
    reset()
    enter('a')
    ae.send('/llm X')
    sa = ae._REG['a']
    check(wait_until(lambda: '/llm X' in agent_of('a').received), 'T24/R3 当前会话未收到切模型命令')
    enter('b')
    sb = ae._REG['b']
    b_agent = agent_of('b')
    check(wait_until(lambda: '/llm X' in b_agent.received), 'T24/R3 新建会话必须继承全局模型选择')
    enter('a')
    ae.send('/llm Y')
    check(wait_until(lambda: '/llm Y' in agent_of('a').received), 'T24/R3 当前会话未收到第二次切模型')
    enter('b')
    check(ae._REG['b'].agent is b_agent, 'T24/R3 已建会话不该被重建')
    check(wait_until(lambda: '/llm Y' in b_agent.received), 'T24/R3 已建会话切回焦点时必须补放最新模型选择')
    with ae._hist_lock:
        check(len(ae._hist) == 0, 'T24/R3 补放不得消耗任何一次 LLM 轮次(_hist 必须为空): ' + repr(len(ae._hist)))
    check(not ae._REG['b'].state['running'], 'T24/R3 补放不得把会话置为运行中')


def t25_preset_undo_is_cas():
    reset()
    with ae._preset_lock: ae._PRESET_CMDS.clear()
    tok1 = ae._record_preset('/llm A')
    tok2 = ae._record_preset('/llm B')
    ae._undo_preset(tok1)
    with ae._preset_lock: vals = list(ae._PRESET_CMDS.values())
    check(vals == ['/llm B'], 'T25/R5 过期 token 必须不回滚(CAS), 实为 ' + repr(vals))
    ae._undo_preset(tok2)
    with ae._preset_lock: vals = list(ae._PRESET_CMDS.values())
    check(vals == ['/llm A'], 'T25/R5 最新 token 必须回滚到上一条, 实为 ' + repr(vals))


def t26_preset_timeout_rolls_back():
    reset()
    enter('t1')
    s = ae._focus(True)
    a = s.agent
    with ae._preset_lock: ae._PRESET_CMDS.clear()

    class BoomQ:
        def get(self, timeout=None): raise queue.Empty

    orig = a.put_task
    a.put_task = lambda *args, **kw: BoomQ()
    try:
        seq0 = ae._preset_seq
        ae.send('/llm Z')
        check(wait_until(lambda: ae._preset_seq > seq0), 'T26/R5 切模型命令未被登记')
        with ae._preset_lock: mid = list(ae._PRESET_CMDS.values())
        check(wait_until(lambda: not ae._PRESET_CMDS), 'T26/R5 判定超时必须回滚, 残留 ' + repr(mid))
    finally:
        a.put_task = orig


def t27_clear_epoch_blocks_late_write():
    reset()
    enter('A')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['A'].state['running']), 'T27 首任务未完成')
    bh = list(bh_of(ae._REG['A']))
    ep = ae._clear_epoch
    ae._reset_convos()
    ok = ae._epoch_guard(ep, lambda: ae._persist_convo('A', bh, []))
    check(ok is False, 'T27/R4 /clear 后旧纪元的落盘必须被拒')
    check(not sessions_files(), 'T27/R4 已清空的会话不得被复活: ' + repr(sessions_files()))

    reset()
    enter('A')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['A'].state['running']), 'T27 第二轮首任务未完成')
    check(wait_until(lambda: sessions_files()), 'T27 第二轮首任务未落盘')
    try: os.remove(chat_json())
    except OSError: pass
    s, g = _fresh_round('A')
    q = queue.Queue()
    th = threading.Thread(target=ae._drain, args=(q, g, s, 'A'), daemon=True)
    th.start()
    time.sleep(0.2)
    with ae._epoch_lock:
        ae._clear_epoch += 1
        shutil.rmtree(sessions_dir(), ignore_errors=True)
    q.put({'done': 'final:x', 'source': 'user', 'turn': 1, 'outputs': ['o1']})
    th.join(5)
    check(not th.is_alive(), 'T27/R4 drain 未收尾')
    check(not sessions_files(), 'T27/R4 在飞 drain 在 /clear 之后不得重建会话文件: ' + repr(sessions_files()))
    check(not os.path.exists(chat_json()), 'T27/R4 /clear 之后不得回写 chat.json')


def t28_completed_round_persists_after_next_task():
    reset()
    enter('A')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['A'].state['running']), 'T28 首任务未完成')
    s, g = _fresh_round('A')
    shutil.rmtree(sessions_dir(), ignore_errors=True)
    q = queue.Queue()
    q.put({'done': 'final:x', 'source': 'user', 'turn': 1, 'outputs': ['o1']})
    orig = ae._save_hist

    def bump():
        with s.lock: s.state['gen'] = ae._next_gen()
        orig()

    ae._save_hist = bump
    try: ae._drain(q, g, s, 'A')
    finally: ae._save_hist = orig
    files = [os.path.basename(p) for p in sessions_files()]
    check('session_A.json' in files, 'T28/R4 正常完成的一轮不得因用户紧接着发下一条而不落盘: ' + repr(files))


def t29_shell_serves_ui_without_agent():
    reset()
    enter('warm')
    n0 = len(FakeAgent.ALL)
    r = ae._switch_convo('shell1')
    check(r == 'ok', 'T29/B2 切到未建会话应回 ok, 实回 ' + repr(r))
    s = ae._REG['shell1']
    check(s.agent is None, 'T29/B2 /convo 不得构造 GenericAgent(桥线程 ANR 根因)')
    check(s.run_thread is None, 'T29/B2 /convo 不得起 run 线程')
    check(len(FakeAgent.ALL) == n0, 'T29/B2 /convo 期间 agent 数不得增长: ' + repr(len(FakeAgent.ALL) - n0))
    check(ae.agent is None, 'T29/B2 焦点是壳时模块级 agent 必须是 None')
    d = json.loads(ae.poll('0'))
    check(d['active_convo'] == 'shell1' and d['running'] is False, 'T29/B2 壳上 poll 必须正常: ' + repr(d.get('active_convo')))
    check(ae.abort() == '已发送中止信号', 'T29/B2 壳上 abort 必须与 HEAD 早退一致')
    check(ae._bind_convo('shell2') == 'bound', 'T29/B2 壳上 bind 必须正常')
    check(ae._REG.get('shell2') is s, 'T29/B2 bind 应原样改挂名(仍是壳)')
    check(s.agent is None, 'T29/B2 bind 不得构造 agent')
    ae.send('first')
    check(wait_until(lambda: s.agent is not None), 'T29/B2 首次 send 必须构造 agent')
    check(len(FakeAgent.ALL) == n0 + 1, 'T29/B2 首发只应构造一个 agent: ' + repr(len(FakeAgent.ALL) - n0))
    check(wait_until(lambda: not s.state['running']), 'T29/B2 首发未跑完')
    check(wait_until(lambda: 'first' in s.agent.received), 'T29/B2 首发任务未落到 agent')


def t29b_convo_does_not_block_on_slow_boot():
    reset()
    enter('warm2')
    orig = ae._sess_boot
    ae._sess_boot = lambda s: (time.sleep(0.6), orig(s))[1]
    try:
        t0 = time.time()
        ae._switch_convo('slowui')
        ae.poll('0')
        ae.abort()
        ae._switch_convo('slowui2')
        dt = time.time() - t0
    finally:
        ae._sess_boot = orig
    check(dt < 0.3, 'T29b/B2 /convo+poll+abort 不得被 agent 构造阻塞(桥线程 ANR), 实耗 %.3fs' % dt)


def t30_disk_restore_wipes_history_on_switch():
    reset()
    enter('d1')
    a1 = agent_of('d1')
    a1.handler = FakeHandler(a1)
    a1.handler.history_info = ['ANCHOR-1']
    a1.history = ['[USER]: seed', 'ANCHOR-1']
    ae.send('qd')
    check(wait_until(lambda: not ae._REG['d1'].state['running']), 'T30 前置任务未完成')
    check(wait_until(lambda: sessions_files() != []), 'T30 前置: 快照未落盘')
    snap = json.load(open(os.path.join(sessions_dir(), 'session_d1.json'), encoding='utf-8'))
    check(snap.get('hist'), 'T30 前置: 落盘快照里必须有 hist 锚点')

    with ae._reg_lock: ae._REG.pop('d1', None)
    with ae._vars_lock: ae._VARS.pop('d1', None)
    ae._switch_convo('d2')
    ae._switch_convo('d1')
    s = ae._REG['d1']
    a2 = ae._sess_agent(s)
    check(a2 is not a1, 'T30 前置: 应是新建 agent')
    check(a2.history == [], 'T30/B3 磁盘回灌(切会话路径)必须与 HEAD _convo_restore 一致: 清空 agent.history, 实为 ' + repr(a2.history))
    check(a2.handler is None and a2.task_dir is None, 'T30/B3 磁盘回灌必须重置 handler/task_dir')
    check([m['content'] for m in bh_of(s)] == ['qd', 'r:qd'], 'T30/B3 磁盘回灌必须恢复 LLM 上下文: ' + repr(bh_of(s)))

    with ae._reg_lock: ae._REG.pop('d1', None)
    with ae._vars_lock: ae._VARS.pop('d1', None)
    with ae._lock: ae._focus_cid = 'd1'
    s3 = ae._focus(True)
    check(s3.agent.history == snap['hist'],
          'T30/B3 冷启 pending 路径(HEAD _maybe_hydrate)必须回灌锚点, 实为 ' + repr(s3.agent.history))


def t31_call_once_leaks_nothing():
    reset()
    enter('base')
    n0 = len(FakeAgent.ALL)
    r0 = len(ae._REG)
    t0 = threading.active_count()
    for _ in range(4):
        out = ae.call_once('alarm')
        check(out.startswith('final:'), 'T31 前置: call_once 未拿到终态, 实回 ' + repr(out))
    check(wait_until(lambda: len(ae._REG) == r0, 6.0),
          'T31/B4 call_once 泄漏会话槽位: %d -> %d' % (r0, len(ae._REG)))
    live = [a for a in FakeAgent.ALL if not a.stopped]
    check(wait_until(lambda: len([a for a in FakeAgent.ALL if not a.stopped]) <= n0, 6.0),
          'T31/B4 call_once 泄漏常驻 agent: ' + repr(len(live) - n0))
    check(threading.active_count() - t0 <= 1, 'T31/B4 call_once 泄漏 run 线程: ' + repr(threading.active_count() - t0))


def t32_call_once_busy_is_focus_scoped():
    reset()
    enter('bg')
    sbg = ae._REG['bg']
    enter('fg')
    with ae._lock: sbg.state['running'] = True
    try:
        out = ae.call_once('alarm-after-stuck-bg')
        check(out.startswith('final:'),
              'T32/B5 非焦点会话的卡死 running 旗标不得吞掉闹钟, 实回 ' + repr(out))
    finally:
        with ae._lock: sbg.state['running'] = False

    reset()
    enter('fg2')
    s = ae._REG['fg2']
    with ae._lock: s.state['running'] = True
    try:
        check(ae.call_once('alarm-while-fg-busy') == 'busy', 'T32/B5 焦点真在跑时闹钟必须回 busy')
    finally:
        with ae._lock: s.state['running'] = False

    reset()
    enter('fg3')
    s3 = ae._REG['fg3']
    with ae._lock: s3.state['running'] = True
    dead = threading.Thread(target=lambda: None)
    dead.start(); dead.join()
    s3.run_thread = dead
    check(ae._focus_busy() is False, 'T32/B5 run_thread 已死时必须交叉校验判定不忙')
    with ae._lock: s3.state['running'] = False


def t33_gen_not_burned_by_sess_construction():
    reset()
    enter('gz')
    ae.send('warm')
    check(wait_until(lambda: not ae._REG['gz'].state['running']), 'T33 前置任务未完成')
    with ae._reg_lock: ae._REG.pop('gz', None)
    with ae._lock: ae._focus_cid = 'g0'
    g_before = ae._cur_gen()
    s = ae._ensure_sess('g0')
    check(ae._cur_gen() == g_before, 'T33/B6 构造 _Sess 不得消耗一代 gen: %d -> %d' % (g_before, ae._cur_gen()))
    check(s.state['gen'] == g_before, 'T33/B6 新 Sess 必须继承当前代, 实为 ' + repr(s.state['gen']))
    ae._sess_agent(s)
    check(ae._cur_gen() == g_before, 'T33/B6 懒构造 agent 也不得消耗 gen')


def t34_每会话独立日志():
    reset()
    enter('lg1')
    a1 = agent_of('lg1')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['lg1'].state['running']), 'T34 前置任务未完成')
    ae._switch_convo('lg2')
    a2 = agent_of('lg2')
    check(a2.log_path and a2.log_path != a1.log_path, 'T34/B7 新会话必须拿到独立日志: ' + repr(a2.log_path))
    ae._switch_convo('lg1')
    check(agent_of('lg1').log_path == a1.log_path, 'T34/B7 切回已建会话不得换日志')

    with ae._reg_lock: ae._REG.pop('lg1', None)
    with ae._vars_lock: ae._VARS.pop('lg1', None)
    ae._switch_convo('lg3')
    ae._switch_convo('lg1')
    a3 = agent_of('lg1')
    check(a3.log_path and a3.log_path != a1.log_path,
          'T34/B7 磁盘回灌路径必须给全新日志(不得被快照里的旧 log_path 盖回): ' + repr(a3.log_path))
    check(ae._retire_sess('lg2') is True, 'T34 前置: lg2 应可回收')
    with ae._vars_lock: vs = ae._VARS.get('lg2')
    check(vs is not None and vs.get('log_path') == a2.log_path,
          'T34/B7 内存快照必须携带该会话自己的 log_path')
    ae._switch_convo('lg2')
    check(agent_of('lg2').log_path == a2.log_path, 'T34/B7 内存快照路径必须装回该会话自己的日志')


def t35_bind_onto_existing_does_not_persist_other():
    reset()
    enter('o1')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['o1'].state['running']), 'T35 前置 o1 未完成')
    ae._switch_convo('o2')
    ae.send('q2')
    check(wait_until(lambda: not ae._REG['o2'].state['running']), 'T35 前置 o2 未完成')
    check(wait_until(lambda: os.path.exists(os.path.join(sessions_dir(), 'session_o1.json'))), 'T35 前置: o1 未落盘')
    before = open(os.path.join(sessions_dir(), 'session_o1.json'), encoding='utf-8').read()
    so1 = ae._REG['o1']
    bh_of(so1).append({'role': 'user', 'content': 'DIRTY-NOT-PERSISTED'})
    r = ae._bind_convo('o1')
    check(r == 'bound', 'T35/B8 bind 应回 bound')
    time.sleep(0.3)
    after = open(os.path.join(sessions_dir(), 'session_o1.json'), encoding='utf-8').read()
    check(after == before,
          'T35/B8 bind 到已存在会话时必须 persist=False(与 HEAD 的纯登记一致), 实际被改写')
    check('DIRTY-NOT-PERSISTED' not in after, 'T35/B8 被顶掉的会话的脏内存不得写盘')
    check(so1.retired, 'T35/B8 被顶掉的同名会话必须已摘表')
    check(ae._REG.get('o1') is not so1, 'T35/B8 挂名后注册表应指向焦点 Sess')


def t35b_bind_waits_out_the_drain_unwind():
    reset()
    enter('w1')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['w1'].state['running']), 'T35b 前置 w1 未完成')
    ae._switch_convo('w2')
    ae.send('q2')
    check(wait_until(lambda: not ae._REG['w2'].state['running']), 'T35b 前置 w2 未完成')
    sw1 = ae._REG['w1']
    focus = ae._REG['w2']
    with sw1.lock: sw1.borrows += 1
    def release():
        time.sleep(0.12)
        with sw1.lock: sw1.borrows -= 1
    threading.Thread(target=release, daemon=True).start()
    t0 = time.time()
    r = ae._bind_convo('w1')
    dt = time.time() - t0
    check(r == 'bound', 'T35b bind 应回 bound')
    check(dt < 1.0, 'T35b bind 不得长时间占用桥线程(ANR 面), 实耗 %.2fs' % dt)
    check(sw1.retired, 'T35b 借用计数归零后被顶掉的会话必须已摘表(不得因 drain 尚未收尾就放弃)')
    check(ae._REG.get('w1') is focus,
          'T35b 挂名后 w1 必须指向焦点 Sess, 实为 %r' % (ae._REG.get('w1'),))
    check(ae._focus_cid == 'w1' and ae._state is focus.state, 'T35b 焦点名必须绑到改挂后的 Sess')


def t36_sess_keep_is_the_lru_bound():
    reset()
    check(ae._SESS_KEEP == 8,
          'T36 _SESS_KEEP 是常驻会话上限的唯一真值, 必须锁死为 8(改小=用户切回旧会话要走磁盘回灌, '
          '锚点 history 被清空), 实为 %r' % (ae._SESS_KEEP,))
    for i in range(8):
        ae._switch_convo('live%d' % i)
        ae._focus(True)
        ae.send('q%d' % i)
        check(wait_until(lambda: not ae._REG['live%d' % i].state['running']), 'T36 前置 live%d 未完成' % i)
    with ae._reg_lock: live = set(ae._REG)
    for i in range(8):
        check('live%d' % i in live, 'T36 8 个会话必须全部常驻内存(不得触发淘汰), live%d 已丢失' % i)
    reset()
    keep = ae._SESS_KEEP
    for i in range(keep + 5):
        ae._switch_convo('lru%d' % i)
        ae._focus(True)
    with ae._reg_lock: n = len(ae._REG)
    check(n <= keep, 'T36 注册表未被 _SESS_KEEP(=%d) 约束, 实为 %d' % (keep, n))
    check(n == keep, 'T36 淘汰过头, 应恰为 %d 实为 %d' % (keep, n))
    with ae._reg_lock: cids = set(ae._REG)
    check('lru%d' % (keep + 4) in cids, 'T36 焦点会话不得被淘汰')
    check('lru0' not in cids, 'T36 最久未访问者必须被淘汰')


def t37_persist_takes_no_reg_lock_under_epoch():
    reset()
    enter('lk1')
    ae.send('q1')
    check(wait_until(lambda: not ae._REG['lk1'].state['running']), 'T37 前置任务未完成')
    held = []
    orig = ae._prune_convo_disk
    ae._prune_convo_disk = lambda: (held.append(ae._epoch_lock.locked()), orig())[1]
    try:
        ae._persist_convo('lk1', [{'role': 'user', 'content': 'x'}], [], ae._clear_epoch)
        check(held, 'T37 前置: _prune_convo_disk 未被调用')
        check(all(x is False for x in held),
              'T37/B1 _prune_convo_disk(要取 _reg_lock) 仍在 _epoch_lock 内执行 → epoch→reg 边重现死锁环: ' + repr(held))
    finally:
        ae._prune_convo_disk = orig
    check(ae._LOCK_ORDER.index('reg') < ae._LOCK_ORDER.index('epoch'),
          'T37/B1 写下的锁序必须是 reg 先于 epoch')

TESTS = [t01_switch_return_values, t02_no_bleed_and_identity, t03_bind_convo_same_source,
         t04_poll_contract, t05_patches_direct_write_and_lock_identity,
         t06_clear_invalidates_inflight_drain, t07_retire_atomic_concurrent, t08_no_zombie_drain,
         t09_preset_replay, t10_vars_survive_eviction_without_pinning_agent,
         t11_bare_llm_not_recorded, t12_failed_llm_does_not_overwrite_preset,
         t13_focus_never_retired_without_force, t14_send_after_concurrent_retire,
         t15_dead_worker_resets_running, t16_clear_busy_covers_non_focus_session,
         t17_save_hist_outside_lock, t18_slow_boot_is_serialised_per_sess, t19_boot_failure_propagates_and_retries,
         t20_agent_is_published_last, t21_focus_never_binds_unregistered,
         t22_drain_uses_send_time_cid, t23_bind_writes_no_disk,
         t24_model_is_global_across_convos, t25_preset_undo_is_cas,
         t26_preset_timeout_rolls_back, t27_clear_epoch_blocks_late_write,
         t28_completed_round_persists_after_next_task,
         t29_shell_serves_ui_without_agent, t29b_convo_does_not_block_on_slow_boot,
         t30_disk_restore_wipes_history_on_switch, t31_call_once_leaks_nothing,
         t32_call_once_busy_is_focus_scoped, t33_gen_not_burned_by_sess_construction,
         t34_每会话独立日志, t35_bind_onto_existing_does_not_persist_other,
         t35b_bind_waits_out_the_drain_unwind,
         t36_sess_keep_is_the_lru_bound, t37_persist_takes_no_reg_lock_under_epoch]


def main():
    for fn in TESTS:
        try:
            fn()
        except Exception:
            import traceback
            FAILURES.append('%s 抛异常:\n%s' % (fn.__name__, traceback.format_exc()))
    try:
        reset()
    except Exception:
        pass
    shutil.rmtree(GA, ignore_errors=True)
    if FAILURES:
        for m in FAILURES: print('FAIL ' + m)
        print('RESULT %d_FAILURES' % len(FAILURES))
        return 1
    print('RESULT ALL_GREEN')
    return 0


if __name__ == '__main__':
    sys.exit(main())
