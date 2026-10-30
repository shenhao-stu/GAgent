# GAgent 感知链路重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GAgent 手机感知的路由判据、通道选择与视觉生命周期从散文（`phone_use.md` §0.05）搬进代码，收敛成 `observe()`（本地定位）与 `see()`（视觉语义）两个入口。

**Architecture:** `_classify(dump_state())` 一个纯函数决定画面类；`observe()` 一次截图一次分类按类跑定位通道，YOLO 失败一律降级不抛；`see()` 升为第一级工具，预算与 code_run 解耦，backend 调用时解析 + 能力分类 + 按模型熔断；`run_guard.check()` 兼任看门狗检查点。

**Tech Stack:** Python 3.12（Chaquopy 运行时 + 桌面 CLI 同一份 `gacore/`），pytest 8.3.5，无新依赖。JS 侧 WebUI 一行改动。真机：`ZYPZ261A01M68700159`，包名 `io.github.shenhaostu.gagent.debug`。

**Spec:** `docs/superpowers/specs/2026-10-28-perception-routing-observe-see-design.md`

## Global Constraints

逐字取自 spec 与仓库约定，对全部任务生效：

- **不新增依赖**：`No new dependency is added to make a phase pass.`
- **不改现有测试以适应**：`pytest -q still passes; no existing test is modified to accommodate it.`（适配新信封时可以改断言，但不得删断言、不得把红的说成绿的）
- **不硬编码**：`Do not hardcode a device size, orientation, OEM layout or app-specific workaround for a general interface defect.`
- **第三方 App 只走视觉路线**：不为微信等引入节点树/内部 API/目标 App CDP；`webcdp` 只连 GAgent 自己的 WebView。
- **敏感或未解析前台返回空节点列表是设计如此**，不削弱这道闸。
- **不存在"结果未知还能重试"的循环**；`uncertain` 是合法终局。
- **畸形工具调用批次什么都不执行**（`llmcore.py:944`）。
- **记录不写屏幕内容/坐标以外信息**（`droid._track` 先例）。
- **文档不把计划写成能力声明**：每期完成以测试与真机证据为准。
- **门禁**：`pytest -q` 无非环境回归（基线 631 passed / 34 failed，34 个全是 Playwright 缺 chromium 与 Windows 文件模式，与改动无关）；`git diff --check`；`tools/audit_source.py` 0 findings。

### Spec 修订（执行期裁定，已与用户确认方向）

1. **能力探测不预探**。spec §4.4 原写"每个 backend 探一次（小图 + reply OK）"，改为**首次真实调用失败时按错误形态分类**：预探会让每个新模型（包括好模型）都多付一次 4-8s 往返。分类后的能力结果仍按 backend 身份缓存，第二次起零成本。
2. **看门狗复用现有检查点**。`run_guard.check()` 已在 `droid.py` 每个读写入口（`:180`/`:429`/`:435`/`:990`/`:1947`…），在其内部兼查截止时刻即可，不新增调用点。

## Review Focus

spec 是愿景文档，它没说到的输入不该把程序弄坏。以下五类最可能咬到用户，每条都钉到具体任务的测试上：

| # | 输入/条件 | 合理的人会期待 | 钉在 |
|---|---|---|---|
| R1 | `dump_state()` 抛异常（总线抖/无 a11y 权限） | 不该崩，也不该因此跳过本地通道 | Task 1 Step 1（`unknown` → 按 `tree`） |
| R2 | YOLO 注册表指向的文件被用户删了 | `look()` 照样返回 OCR/树结果，任务继续，且能告诉用户为什么少了图标框 | Task 2 Step 1/3 |
| R3 | 切到纯文本模型后第一次 `see()` | 立刻得到"该模型不能看图"的结构化答复，且**不**触发 120s 熔断 | Task 4 Step 1/3 |
| R4 | 同一次 `gui_act` 里设备侧挂住（真机 260s） | 到墙钟上限就返回结构化错误，不是无限挂住 + 空 tool_result | Task 6 Step 1/3 |
| R5 | 普通页被误判成 canvas（海报/骨架屏/WebView 首帧） | 图标框照常返回，不因为漏判被迫问 VLM | Task 1 Step 1（低信息树判据双向收口） |

---

## File Structure

| 文件 | 职责 | 本计划改动 |
|---|---|---|
| `gacore/droid.py` | 设备能力单一入口 | 新增 `_classify`/`observe`/`_ACTIVE_BACKEND`/`_vision_cap`/`_FUSE`；`look`/`screen_kind`/`ask_vision`/`ask_point` 改薄封装；删 `_VISION_TLS`/`_vision_total_budget`+3 常量/`vision_api` 死分支 |
| `gacore/models/ui_detect_v1/ui_detect_lite.py` | YOLO+OCR 检测器 | `_yolo` 失败降级返回 `([], err)`；`detect()` 记 `LAST_YOLO_ERROR` |
| `gacore/run_guard.py` | 僵尸线程护栏 | `check()` 兼查截止时刻；新增 `enter_deadline`/`WatchdogExpired` |
| `gacore/ga_android.py` | 工具派发 | 新增 `do_see`；`_compact_obs` 改调 `observe()`；`__init__` 登记 `_ACTIVE_BACKEND`；`do_gui_act` 设看门狗截止 |
| `gacore/vision_llm.py` | VLM 问答 | 不改（`ask_with_backend` 已有墙钟上限） |
| `gacore/assets/tools_schema.json` + `_cn.json` | 工具契约 | 新增 `see`；改 `gui_act`/`code_run` 描述 |
| `gacore/memory/phone_use.md` | L3 SOP | §0.05 删除、§0.1 删机制留纪律、§1 改指向、置顶三步契约 |
| `gacore/webui/app.js` | WebUI | `setDefaultModel` 补 `/llm` |
| `tests/` | 无设备单测 | 6 个新文件 + 3 个适配 |

---

### Task 1: `_classify` 画面分类纯函数

**Files:**
- Modify: `app/src/main/assets/gacore/droid.py`（在 `screen_kind()` 所在位置，`:817-832`）
- Test: `tests/test_classify.py`（新建）

**Interfaces:**
- Consumes: `droid.dump_state()` 返回 `{'nodes': [...], 'degraded': {'reason': str}|None, 'pkg': str}`；节点字段 `click`（SPEC §2.3 节点契约 `{t,d,x,y,b,cls,click,edit,range,sel}`）
- Produces: `droid._classify(st) -> str`，取值 `'tree'|'blanked'|'canvas'|'unknown'`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_classify.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore'))
import droid


def _node(click=False, text='x'):
    return {'t': 'text' if text else 'icon', 'd': '', 'x': 1, 'y': 1, 'b': [0, 0, 9, 9],
            'cls': 'Text', 'click': click, 'edit': False, 'range': None, 'sel': None}


def _st(nodes, reason=None):
    return {'nodes': nodes, 'degraded': {'reason': reason} if reason else None, 'pkg': 'com.x'}


def test_tree_when_normal_widget_tree():
    assert droid._classify(_st([_node(click=True), _node(click=True)])) == 'tree'


def test_blanked_when_sensitive_blank():
    assert droid._classify(_st([], 'sensitive_blank')) == 'blanked'


def test_blanked_when_unresolved_fg():
    assert droid._classify(_st([], 'unresolved_fg')) == 'blanked'


def test_canvas_when_tree_empty():
    assert droid._classify(_st([], 'tree_empty')) == 'canvas'


def test_canvas_when_low_information_tree():
    """王者荣耀实测形态: 1 个不可点节点("Game view")。旧判据只认 tree_empty 会漏。"""
    assert droid._classify(_st([_node(click=False)])) == 'canvas'


def test_canvas_when_nodes_exist_but_none_clickable():
    """海报/骨架屏/WebView 首帧: 多个节点但全无 text/desc/clickable。"""
    nodes = [_node(click=False, text=''), _node(click=False, text='')]
    assert droid._classify(_st(nodes)) == 'canvas'


def test_unknown_when_state_is_none():
    assert droid._classify(None) == 'unknown'


def test_one_clickable_node_is_not_canvas():
    """有 1 个可点节点就不是低信息树 —— 双向收口的另一侧。"""
    assert droid._classify(_st([_node(click=False), _node(click=True)])) == 'tree'
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_classify.py -q`
Expected: FAIL，`AttributeError: module 'droid' has no attribute '_classify'`

- [ ] **Step 3: 实现 `_classify`，`screen_kind()` 改为它的薄封装**

在 `droid.py` 的 `screen_kind()`（`:817-832`）处替换为：

```python
def _clickable_count(nodes):
    """可点节点数。低信息树判据的一边: 树里有可点目标就不是"没树"。"""
    n = 0
    for x in nodes or []:
        try:
            if x.get('click'):
                n += 1
        except AttributeError:
            continue
    return n


def _classify(st):
    """dump_state() 的产物 → 'tree'|'blanked'|'canvas'|'unknown'。纯函数, 无设备依赖。

    为什么要它: YOLO 与 vision 的分流判据。有可用控件树时 YOLO+OCR 又快又准(31ms);
    没有时(游戏/SurfaceView/自绘/混淆) YOLO 的 21 个通用 Android 类既认不出语义, 框还会
    把模型带偏——那种画面定位只能问 VLM。判据不额外花钱: 就是一次 dump_state() 的产物。

    旧判据只认 degraded.reason=='tree_empty', 两个方向都错(真机实证):
    - 漏: 王者荣耀是 1 个不可点节点("Game view"), 不是 tree_empty → 判成 ui, YOLO 在游戏上跑;
    - 误: 海报页/骨架屏/WebView 首帧所有节点都无 text/desc/clickable → tree_empty → 判成
      canvas, 该拿图标框的普通页被跳过 YOLO。
    故补"低信息树": 节点数<=1 且无可点节点 → 同样是没有可用控件树。"""
    if not st:
        return 'unknown'
    reason = (st.get('degraded') or {}).get('reason')
    if reason in ('sensitive_blank', 'unresolved_fg'):
        return 'blanked'
    if reason == 'tree_empty':
        return 'canvas'
    nodes = st.get('nodes') or []
    if len(nodes) <= 1 and _clickable_count(nodes) == 0:
        return 'canvas'
    return 'tree'


def screen_kind():
    """当前画面类型: 'canvas'(自绘/游戏/SurfaceView) | 'blanked'(敏感 App 树被置空) | 'ui'(普通控件树)。

    _classify 的公开薄封装; 'unknown'(dump_state 抛异常) 归一成 'ui' 保持历史契约。
    新代码请直接用 _classify —— 'unknown' 与 'ui' 的通道选择不同(见 observe)。"""
    try:
        st = dump_state()
    except Exception:
        return 'ui'
    k = _classify(st)
    return 'ui' if k == 'unknown' else k
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_classify.py tests/test_droid_dump_state.py -q`
Expected: 8 + 既有用例全 PASS

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/droid.py tests/test_classify.py
git commit -m "refactor(droid): _classify 画面分类补低信息树判据——游戏漏判/海报页误判双向收口" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 2: YOLO 失败一律降级，绝不外抛

**Files:**
- Modify: `app/src/main/assets/gacore/models/ui_detect_v1/ui_detect_lite.py:76-85`（`_yolo`）、`:114-158`（`detect`）
- Test: `tests/test_ui_detect_degrade.py`（新建）

**Interfaces:**
- Consumes: `detector_models.model_path()`（注册表指向的文件丢失时抛 `ValueError`）；`_session()`（文件不存在时经 APK 总线抛 `RuntimeError: model not found`）
- Produces: `ui_detect_lite.LAST_YOLO_ERROR`（`None` 或 `str`，每次 `detect()` 入口重置）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ui_detect_degrade.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore', 'models', 'ui_detect_v1'))
import numpy as np
import ui_detect_lite


def _img():
    return np.zeros((64, 64, 3), dtype=np.uint8)


def test_registry_points_at_missing_file_degrades_to_ocr(monkeypatch):
    """真机 A 次运行: 注册表在但文件被删 → detector_models.model_path() 抛 ValueError。
    旧行为: 异常穿透 detect() → look() 整条崩 → 整轮作废。"""
    import detector_models
    monkeypatch.setattr(detector_models, 'model_path', lambda: (_ for _ in ()).throw(ValueError('missing')))
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))
    out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
    assert out == []
    assert ui_detect_lite.LAST_YOLO_ERROR


def test_onnx_session_failure_degrades(monkeypatch):
    """真机 A 次运行: model not found(RuntimeError, 来自 APK 总线)。"""
    monkeypatch.setattr(ui_detect_lite, '_session', lambda p: (_ for _ in ()).throw(RuntimeError('model not found: /x')))
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))
    out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
    assert out == []
    assert 'model not found' in ui_detect_lite.LAST_YOLO_ERROR


def test_last_error_cleared_on_success(monkeypatch):
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))
    monkeypatch.setattr(ui_detect_lite, '_yolo', lambda img, conf: ([], None))
    ui_detect_lite.detect(_img(), yolo=True)
    assert ui_detect_lite.LAST_YOLO_ERROR is None


def test_ocr_only_path_reports_no_yolo_error(monkeypatch):
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))
    ui_detect_lite.detect(_img(), yolo=False)
    assert ui_detect_lite.LAST_YOLO_ERROR is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_ui_detect_degrade.py -q`
Expected: FAIL，`AttributeError: module 'ui_detect_lite' has no attribute 'LAST_YOLO_ERROR'`

- [ ] **Step 3: 实现降级**

`ui_detect_lite.py` 顶部常量区（`:43` 附近）加：

```python
LAST_YOLO_ERROR = None   # 最近一次 detect() 的 YOLO 失败原因; None=本次没失败。observe() 据此降级并记 note
```

`_yolo`（`:76-85`）改为返回 `(boxes, err)`：

```python
def _yolo(img, conf):
    """YOLO ONNX(内置NMS, 输出(1,300,6)) → ([[x1,y1,x2,y2,conf,cls],...], err)。

    返回二元组而不是抛: 检测器缺失/损坏时调用方必须能降级到其余通道, 而不是让整条
    look()/observe() 崩掉把轮次作废(真机 A 次运行 22 分钟的根因之一)。"""
    try:
        x, r, left, top = _letterbox(img)
        import detector_models
        model = str(detector_models.model_path())
        if not os.path.isfile(model):
            return [], 'detector model file missing: %s' % model
        sess = _session(model)
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]  # (300,6)
        return _restore(out, conf, r, left, top, img.shape[1], img.shape[0]), None
    except Exception as exc:
        # 收窄前先确认被调方真实抛什么: detector_models.model_path() 抛 ValueError(注册表
        # 指向的文件丢了), _session() 经 APK 总线抛 RuntimeError(model not found), 推理本身
        # 可能抛任意 ORT 异常。三类都要降级, 故保留宽捕获——这是容错边界, 不是消告警。
        return [], '%s: %s' % (type(exc).__name__, str(exc)[:160])
```

`detect()`（`:114-158`）入口与 YOLO 调用处改为：

```python
def detect(image, conf=0.25, contain_thresh=0.5, yolo=True):
    """...（docstring 不变, 追一句）...
    降级: YOLO 失败不外抛, 记 LAST_YOLO_ERROR 并只跑 OCR —— 调用方据此降级并告知用户。"""
    global LAST_YOLO_ERROR
    img = cv2.imread(image) if isinstance(image, str) else image
    assert img is not None, "image load failed"

    LAST_YOLO_ERROR = None
    if yolo:
        yolo_boxes, LAST_YOLO_ERROR = _yolo(img, conf)
    else:
        yolo_boxes = []
```

（其余 OCR/匹配逻辑不动）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_ui_detect_degrade.py tests/test_vision_accel.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/models/ui_detect_v1/ui_detect_lite.py tests/test_ui_detect_degrade.py
git commit -m "fix(ui_detect): YOLO 缺失/损坏一律降级只跑 OCR——不再让 look() 整条崩掉作废轮次" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 3: `observe()` 单一本地感知入口

**Files:**
- Modify: `app/src/main/assets/gacore/droid.py`（`_LOOK_CACHE`/`_ROI_NAMES` `:804-810`、`look()` `:835-894`、`ui_detect()` `:1875-1882`）
- Modify: `app/src/main/assets/gacore/ga_android.py`（`_compact_obs` `:466-490`）
- Test: `tests/test_observe.py`（新建）

**Interfaces:**
- Consumes: `droid._classify`（Task 1）、`ui_detect_lite.LAST_YOLO_ERROR`（Task 2）、`droid.shot()`、`droid.dump_state()`、`droid.ui_detect(img, conf)`
- Produces:
  - `droid.observe(roi=None, conf=0.25, cache=True) -> dict`：`{'kind', 'items', 'channels', 'notes', 'ms'}`
  - item 形状：`{'src': 'tree'|'yolo', 't', 'label', 'cls', 'x', 'y', 'rx', 'ry', 'bbox', 'click', 'conf'}`
  - `droid.look(...)` 保持原签名与返回形状（内部委托 observe）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_observe.py
import sys
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid

_IMG = np.zeros((100, 200, 3), dtype='uint8')


def _node(x=10, y=10, click=True):
    return {'t': 'text', 'd': 'd', 'x': x, 'y': y, 'b': [x - 5, y - 5, x + 5, y + 5],
            'cls': 'Text', 'click': click, 'edit': False, 'range': None, 'sel': None}


def _det(x=50, y=50, label='确定', cls='TextButton'):
    return {'bbox': [x - 10, y - 10, x + 10, y + 10], 'type': 'icon', 'label': label,
            'cls': cls, 'confidence': 0.9}


def _wire(monkeypatch, kind, nodes=(), dets=(), note=None):
    monkeypatch.setattr(droid, 'dump_state', lambda full=False: {'nodes': list(nodes), 'degraded': None, 'pkg': 'com.x'})
    monkeypatch.setattr(droid, '_classify', lambda st: kind)
    monkeypatch.setattr(droid, 'shot', lambda *a, **k: _IMG)
    monkeypatch.setattr(droid, 'ui_detect', lambda img, conf=0.25, yolo=True: list(dets))
    monkeypatch.setattr(droid, '_yolo_note', lambda: note)
    monkeypatch.setattr(droid, 'screen', lambda: (200, 100))
    monkeypatch.setattr(droid, 'ping', lambda: {'w': 200, 'h': 100, 'rot': 0})
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)


def test_tree_kind_merges_tree_and_yolo(monkeypatch):
    _wire(monkeypatch, 'tree', nodes=[_node()], dets=[_det()])
    r = droid.observe()
    assert r['kind'] == 'tree'
    srcs = sorted(i['src'] for i in r['items'])
    assert srcs == ['tree', 'yolo']
    assert 'yolo' in r['channels'] and 'tree' in r['channels']


def test_canvas_kind_runs_no_local_channel(monkeypatch):
    """游戏/混淆/canvas: 不跑 YOLO 也不为定位跑 OCR —— 定位问 VLM。"""
    _wire(monkeypatch, 'canvas', nodes=[], dets=[_det()])
    r = droid.observe()
    assert r['kind'] == 'canvas'
    assert r['items'] == []
    assert r['channels'] == []
    assert r['needs_vision'] is True


def test_blanked_kind_runs_yolo(monkeypatch):
    _wire(monkeypatch, 'blanked', nodes=[], dets=[_det(label='Q', cls='Icon')])
    r = droid.observe()
    assert r['kind'] == 'blanked'
    assert [i['src'] for i in r['items']] == ['yolo']
    assert 'yolo' in r['channels']


def test_yolo_failure_degrades_with_note(monkeypatch):
    """R2: YOLO 挂了不抛, 树项照回, 且 notes 说清为什么少了图标框。"""
    _wire(monkeypatch, 'tree', nodes=[_node()], dets=[], note='RuntimeError: model not found: /x')
    r = droid.observe()
    assert [i['src'] for i in r['items']] == ['tree']
    assert r['notes'] == ['detector_unavailable: RuntimeError: model not found: /x']
    assert 'yolo' not in r['channels']


def test_unknown_kind_falls_back_to_tree(monkeypatch):
    """R1: dump_state 抛异常 → unknown → 仍跑本地通道, 不崩也不空手。"""
    _wire(monkeypatch, 'unknown', nodes=[], dets=[_det()])
    r = droid.observe()
    assert r['kind'] == 'unknown'
    assert [i['src'] for i in r['items']] == ['yolo']


def test_items_carry_both_units(monkeypatch):
    _wire(monkeypatch, 'tree', nodes=[], dets=[_det(x=100, y=50)])
    r = droid.observe()
    it = r['items'][0]
    assert (it['x'], it['y']) == (100, 50)
    assert (it['rx'], it['ry']) == (500, 500)      # 100/200*1000, 50/100*1000


def test_cache_miss_after_package_change(monkeypatch):
    """SPEC §2.3 缺陷: 缓存键不含 pkg → 切 App 后命中旧结果。"""
    _wire(monkeypatch, 'tree', nodes=[_node(x=10)], dets=[_det(x=10, y=10)])
    first = droid.observe()
    assert first['items'][0]['x'] == 10
    _wire(monkeypatch, 'tree', nodes=[_node(x=180)], dets=[_det(x=180, y=90)])
    monkeypatch.setattr(droid, 'dump_state', lambda full=False: {'nodes': [_node(x=180)], 'degraded': None, 'pkg': 'com.other'})
    second = droid.observe()
    assert second['items'][0]['x'] == 180
    assert not second.get('cached')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_observe.py -q`
Expected: FAIL，`AttributeError: module 'droid' has no attribute 'observe'`

- [ ] **Step 3: 实现 `observe()`**

`droid.py` 用 `observe()` 取代 `_LOOK_CACHE`/`look()` 主体（`:804-894` 区间）：

```python
_OBS_CACHE = {"thumb": None, "roi": None, "pkg": None, "rot": None, "res": None}


def _yolo_note():
    """最近一次 ui_detect 的 YOLO 失败原因; 检测器不可 import(PC 侧)时返回 None。"""
    try:
        from models.ui_detect_v1 import ui_detect_lite
        return getattr(ui_detect_lite, 'LAST_YOLO_ERROR', None)
    except Exception:
        return None


def _obs_item_from_node(n, x1, y1, W, H):
    bx = n.get('b') or n.get('bbox') or [n.get('x', 0), n.get('y', 0), n.get('x', 0), n.get('y', 0)]
    cx, cy = n.get('x'), n.get('y')
    if cx is None or cy is None:
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    cx, cy = int(cx) + x1, int(cy) + y1
    return {'src': 'tree', 't': str(n.get('t') or ''), 'label': str(n.get('d') or ''),
            'cls': str(n.get('cls') or ''), 'x': cx, 'y': cy,
            'rx': geom.to_norm(cx, cy, W, H)[0], 'ry': geom.to_norm(cx, cy, W, H)[1],
            'bbox': [int(bx[0]) + x1, int(bx[1]) + y1, int(bx[2]) + x1, int(bx[3]) + y1],
            'click': bool(n.get('click')), 'conf': None}


def _obs_item_from_det(d, x1, y1, W, H):
    bx1, by1, bx2, by2 = d['bbox']
    cx, cy = int((bx1 + bx2) / 2) + x1, int((by1 + by2) / 2) + y1
    rx, ry = geom.to_norm(cx, cy, W, H)
    return {'src': 'yolo', 't': str(d.get('type') or ''), 'label': str(d.get('label') or ''),
            'cls': str(d.get('cls') or ''), 'x': cx, 'y': cy, 'rx': rx, 'ry': ry,
            'bbox': [bx1 + x1, by1 + y1, bx2 + x1, by2 + y1], 'click': None,
            'conf': d.get('confidence')}


def observe(roi=None, conf=0.25, cache=True):
    """本地定位通道一步到位: 一次截图 + 一次分类 + 按类选通道。

    返回 {'kind', 'items', 'channels', 'notes', 'needs_vision', 'ms'}:
    - kind: _classify 的产物('tree'|'blanked'|'canvas'|'unknown')
    - items: [{src:'tree'|'yolo', t,label,cls,x,y,rx,ry,bbox,click,conf}] —— x/y 像素可直接当
      gui_act 的 point, rx/ry 是 0-1000 可直接当 rel
    - channels: 实际跑了哪些通道
    - notes: 降级原因(如 detector_unavailable); 空列表=没降级
    - needs_vision: True 表示本地定位通道为空, 要定位得问 see()

    通道选择(判据在 _classify, 不靠模型现推):
    - tree     : 控件树 + YOLO(YOLO 的 label 由 OCR 贴)
    - blanked  : YOLO(树被策略置空但屏幕有字)
    - canvas   : 都不跑 —— 定位问 VLM; 要"读画面"由调用方显式 droid.ocr()
    - unknown  : 按 tree(YOLO 失败会降级, 没有风险)

    降级铁律: YOLO 侧任何失败只记 note, 绝不外抛。"""
    t0 = time.time()
    import cv2
    import numpy as np
    img = shot()
    H, W = img.shape[:2]
    if isinstance(roi, str):
        if roi not in _ROI_NAMES:
            raise ValueError('observe: unknown roi %r, choose from: %s' % (roi, '/'.join(sorted(_ROI_NAMES))))
        roi = _ROI_NAMES[roi]
    if roi:
        x1, y1, x2, y2 = roi
        if max(x1, y1, x2, y2) <= 1.0:
            x1, y1, x2, y2 = x1 * W, y1 * H, x2 * W, y2 * H
        x1, y1, x2, y2 = int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2))
    else:
        x1, y1, x2, y2 = 0, 0, W, H
    crop = img[y1:y2, x1:x2]

    thumb = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (36, 80), interpolation=cv2.INTER_AREA)
    try:
        st = dump_state() or {}
        pkg = str(st.get('pkg') or '')
    except Exception:
        st, pkg = {}, ''
    try:
        p = ping(); rot = int(p.get('rot') or 0)
    except Exception:
        rot = 0
    c = _OBS_CACHE
    if cache and c["res"] is not None and c["roi"] == (x1, y1, x2, y2) \
            and c["pkg"] == pkg and c["rot"] == rot and c["thumb"] is not None:
        if float((cv2.absdiff(thumb, c["thumb"]) > 16).mean()) < 0.003:
            res = dict(c["res"]); res["cached"] = True
            return res

    kind = _classify(st)
    items, channels, notes = [], [], []
    if kind in ('tree', 'unknown'):
        channels.append('tree')
        for n in (st.get('nodes') or []):
            if isinstance(n, dict):
                items.append(_obs_item_from_node(n, x1, y1, W, H))
    if kind in ('tree', 'blanked', 'unknown'):
        channels.append('yolo')
        dets = ui_detect(crop, conf=conf)
        for d in dets:
            items.append(_obs_item_from_det(d, x1, y1, W, H))
        note = _yolo_note()
        if note:
            notes.append('detector_unavailable: %s' % note)
            channels = [c for c in channels if c != 'yolo']
            items = [i for i in items if i['src'] != 'yolo']
    needs_vision = not any(i['src'] == 'yolo' for i in items) and kind in ('canvas', 'blanked', 'unknown') \
        or (kind == 'canvas')
    res = {'kind': kind, 'items': items, 'channels': channels, 'notes': notes,
           'needs_vision': needs_vision, 'ms': round((time.time() - t0) * 1000, 1)}
    c.update(thumb=thumb, roi=(x1, y1, x2, y2), pkg=pkg, rot=rot, res=res)
    global _LAST_OBS, _OBS_STALE
    _LAST_OBS = {"nodes": [], "detections": [i for i in items if i['src'] == 'yolo'],
                 "screen": (W, H), "pkg": pkg}
    _OBS_STALE = False
    _trace("observe", result={"kind": kind, "count": len(items)})
    return res
```

`needs_vision` 一行写复杂了，实现时拆成可读形式：

```python
    if kind == 'canvas':
        needs_vision = True
    elif not items:
        needs_vision = True
    else:
        needs_vision = False
```

`look()` 改为薄封装（保持原签名/返回形状，配方与 SOP 不破）：

```python
def look(conf=0.25, path=None, roi=None, cache=True, *, label=None, yolo=None):
    """视觉路径一步到位: observe() 后取 YOLO 项, 形状与历史一致。

    yolo 参数保留但已无意义(通道选择搬进了 observe 的 _classify); 传 True/False 都忽略,
    显式传 False 会走 observe 的 canvas 分支。新代码请用 observe()。"""
    if label is not None and not isinstance(label, str):
        raise TypeError('look label must be a string or None')
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        raise ValueError('look(conf=0.25, ...) 返回检测框，不接受问题；看图问答请用 see()') from None
    if not 0 <= conf <= 1:
        raise ValueError('look conf must be between 0 and 1')
    res = observe(roi=roi, conf=conf, cache=cache)
    out = []
    for i in res['items']:
        if i['src'] != 'yolo':
            continue
        out.append({'bbox': list(i['bbox']), 'type': i['t'], 'label': i['label'],
                    'cls': i['cls'], 'confidence': i['conf'], 'x': i['x'], 'y': i['y'],
                    'rx': i['rx'], 'ry': i['ry'], 'cached': res.get('cached', False)})
    if label:
        out = [d for d in out if label in (d.get('label') or '')]
    if path:
        import cv2
        cv2.imwrite(path, shot())
    return out
```

`ga_android._compact_obs`（`:466-490`）替换为：

```python
    def _compact_obs(self):
        """动作后的紧凑观测: observe() 一次出结果, 带 kind 与 src。

        旧实现在这里分 dump/look 两路 + canvas 特判, 还要额外付一次 screen_kind() 的
        dump_state 往返; 现在路由在 _classify 里, 这里只负责截断成模型看得动的条数。"""
        import droid
        try:
            res = droid.observe()
        except Exception:
            return []
        items = []
        for i in res['items'][:self._OBS_ITEMS]:
            label = str(i.get('label') or i.get('cls') or '').strip()[:self._OBS_LABEL]
            items.append({'t': i['t'], 'src': i['src'], 'label': label, 'cls': i['cls'],
                          'x': i['x'], 'y': i['y'], 'rx': i['rx'], 'ry': i['ry'],
                          'click': i['click']})
        return items
```

> 注：`_compact_obs` 的返回值进了 `gui_act` 结果的 `obs` 字段，字段名从 `{t,cls,x,y,rx,ry}` 扩到含 `src`/`label`/`click`——是增量子集变化，`tests/test_structured_action.py` 的断言需要同步（Task 3 Step 4）。

- [ ] **Step 4: 跑测试确认通过 + 适配受影响断言**

Run: `python -m pytest tests/test_observe.py tests/test_structured_action.py tests/test_gui_act_obs_e2e.py tests/test_vision_accel.py -q`
Expected: 新用例全 PASS；`test_structured_action.py` / `test_gui_act_obs_e2e.py` 若因 `obs` 新增字段失败，只加不断言（把期望字典补上 `src`/`label`/`click` 键），不得删原有断言。

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q 2>&1 | tail -3`
Expected: `631 passed` 以上；failed 数不超基线 34，且失败集合仍是 Playwright/Windows 文件模式那批。

```bash
git add app/src/main/assets/gacore/droid.py app/src/main/assets/gacore/ga_android.py tests/test_observe.py tests/test_structured_action.py tests/test_gui_act_obs_e2e.py
git commit -m "feat(droid): observe() 单一本地感知入口——一次截图一次分类按类选通道" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 4: 视觉生命周期——backend 登记、能力分类、按模型熔断

**Files:**
- Modify: `app/src/main/assets/gacore/droid.py`（`_VISION_TLS` `:900-948`、`ask_vision` `:980-1037`）
- Modify: `app/src/main/assets/gacore/ga_android.py`（`code_run` 注入 `:44-48`/`:61`、`__init__` `:219-226`、`_vision_backend` `:247-253`、`turn_end_callback` `:744`）
- Modify: `conftest.py:27,32`（**必须改**：autouse 夹具引用 `droid._VISION_FAILS`，该名字本任务删除，不改则全部用例 error）
- Test: `tests/test_vision_lifecycle.py`（新建）

**Interfaces:**
- Consumes: `vision_llm.ask_with_backend(backend, image, prompt, max_pixels=, timeout=)`
- Produces:
  - `droid.set_active_backend(backend)` / `droid.active_backend()`
  - `droid._vision_cap(backend) -> 'ok'|'no_vision'|None`
  - `droid.reset_vision_fuse(backend=None)`（兼容旧签名：无参=全清）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_vision_lifecycle.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore'))
import numpy as np
import droid

_IMG = np.zeros((32, 32, 3), dtype='uint8')


class _Backend:
    def __init__(self, name, boom=None):
        self.name, self.boom = name, boom
    def __hash__(self):
        return hash(self.name)


def _no_cap(monkeypatch):
    """让能力分类器可编排: 返回一个可控的 ask_with_backend。"""
    calls = {'n': 0}
    def fake(backend, image, prompt, **kw):
        calls['n'] += 1
        if backend.boom:
            raise RuntimeError(backend.boom)
        return 'ok'
    monkeypatch.setattr('vision_llm.ask_with_backend', fake)
    return calls


def test_active_backend_survives_child_thread(monkeypatch):
    """R?: 用户代码自起子线程调 ask_vision —— threading.local() 不跨线程继承, 旧实现拿不到。"""
    import threading
    be = _Backend('a')
    droid.set_active_backend(be)
    box = {}
    t = threading.Thread(target=lambda: box.update(b=droid.active_backend()))
    t.start(); t.join()
    assert box['b'] is be
    droid.set_active_backend(None)


def test_non_multimodal_model_does_not_trip_fuse(monkeypatch):
    """R3: 切到纯文本模型 → 第一次就明确拒绝, 且不计熔断。"""
    be = _Backend('text-only', boom='400 Bad Request: image not supported by this model')
    droid.set_active_backend(be)
    _no_cap(monkeypatch)
    for _ in range(5):
        try:
            droid.ask_vision(_IMG, 'q')
        except RuntimeError as e:
            assert 'no_vision' in str(e) or '不支持图片' in str(e)
    assert droid._FUSE.get(droid._backend_id(be), {}).get('n', 0) == 0
    assert droid._vision_cap(be) == 'no_vision'
    droid.set_active_backend(None)


def test_transport_failure_trips_fuse_per_model(monkeypatch):
    be = _Backend('flaky', boom='read timeout')
    droid.set_active_backend(be)
    _no_cap(monkeypatch)
    droid.reset_vision_fuse()
    for _ in range(2):
        try:
            droid.ask_vision(_IMG, 'q')
        except RuntimeError:
            pass
    assert droid._vision_cap(be) != 'no_vision'
    try:
        droid.ask_vision(_IMG, 'q')
        raise AssertionError('应当已熔断')
    except RuntimeError as e:
        assert '熔断' in str(e)
    droid.set_active_backend(None)


def test_switching_model_resets_that_models_fuse(monkeypatch):
    bad = _Backend('bad', boom='read timeout')
    droid.reset_vision_fuse()
    droid.set_active_backend(bad)
    _no_cap(monkeypatch)
    for _ in range(2):
        try: droid.ask_vision(_IMG, 'q')
        except RuntimeError: pass
    assert droid._fuse_state(bad)['n'] >= 2
    droid.set_active_backend(_Backend('good'))
    assert droid._fuse_state(_Backend('good'))['n'] == 0
    droid.set_active_backend(None)


def test_success_clears_that_models_fuse(monkeypatch):
    be = _Backend('ok')
    droid.set_active_backend(be)
    _no_cap(monkeypatch)
    droid.reset_vision_fuse()
    assert droid.ask_vision(_IMG, 'q') == 'ok'
    assert droid._fuse_state(be)['n'] == 0
    droid.set_active_backend(None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_vision_lifecycle.py -q`
Expected: FAIL，`AttributeError: module 'droid' has no attribute 'set_active_backend'`

- [ ] **Step 3: 实现**

先改 `conftest.py` 的 autouse 夹具（`:21-32`），把对已删名字的引用换成新状态，并补上新引入的模块级可变状态：

```python
@pytest.fixture(autouse=True)
def _reset_module_state():
    """重置 gacore 的模块级可变状态, 防止跨用例泄漏:
    phone_ledger.ACTIVE(守卫账本) / droid._TRACE+_LAST_OBS(录制痕迹) /
    droid._FUSE+_CAP+_ACTIVE_BACKEND(视觉生命周期) / droid._OBS_CACHE(观测缓存)。"""
    import phone_ledger
    import droid
    phone_ledger.ACTIVE.clear()
    droid._TRACE.clear()
    droid._LAST_OBS = None
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)
    droid._FUSE.clear(); droid._CAP.clear(); droid._ACTIVE_BACKEND = None
    yield
    phone_ledger.ACTIVE.clear()
    droid._TRACE.clear()
    droid._LAST_OBS = None
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)
    droid._FUSE.clear(); droid._CAP.clear(); droid._ACTIVE_BACKEND = None
```

然后按上述 Files 清单改 `droid.py` 视觉状态区（`:900-948`）整体替换为：

```python
# ---- 视觉通道生命周期 ----
# 三件事各自独立, 曾互相打架(真机: 选个不支持图片的模型 = 2 次 2.4s 快速失败 = 120s 全瞎):
#   ① backend 从哪来  ② 这个模型能不能看图  ③ 传输失败几次算熔断
# ① 任务开始由 ga_android 登记到模块级 _ACTIVE_BACKEND(不是 threading.local —— 后者不跨
#    线程继承, 用户代码自起子线程调 ask_vision 会莫名拿不到; 模块级登记没有这个问题)。
# ② 首次真实调用失败时按错误形态分类并缓存, 不预探(预探让每个新模型都多付一次往返)。
# ③ 熔断按 backend 身份, 切模型即重置 —— 上个模型的失败不该罚下一个模型。
_ACTIVE_BACKEND = None
_FUSE = {}                 # backend_id -> {'n': int, 'until': float}
_CAP = {}                  # backend_id -> 'ok'|'no_vision'
_VISION_FAIL_LIMIT = 2     # 连续传输失败此次数后熔断
_VISION_COOLDOWN_S = 120   # 熔断静默期: 期间直接拒, 不再反复烧超时
_VISION_TIMEOUT_S = 30     # 单次**读**超时(流式下=两个 chunk 之间最多静默多久): 抓"真挂住"
_NO_VISION_MARKS = ('image', 'vision', 'multimodal', 'multi-modal', '不支持图片', '无法处理图片',
                    'image_url', 'base64')


def set_active_backend(backend):
    """ga_android 在任务开始/模型切换时登记当前任务的模型后端; None=清除。"""
    global _ACTIVE_BACKEND
    _ACTIVE_BACKEND = backend


def active_backend():
    return _ACTIVE_BACKEND


def _backend_id(backend):
    """backend 的稳定身份: provider/model/base 的哈希。切模型即变, 熔断与能力缓存随之失效。"""
    if backend is None:
        return None
    parts = []
    for name in ('model', 'name', 'api_base', 'base_url', 'provider'):
        try:
            v = getattr(backend, name, None)
            if isinstance(v, str) and v:
                parts.append(v)
        except Exception:
            pass
    if not parts:
        parts.append(repr(type(backend).__name__))
    return '|'.join(parts)


def _fuse_state(backend):
    return _FUSE.setdefault(_backend_id(backend), {'n': 0, 'until': 0.0})


def reset_vision_fuse(backend=None):
    """清零视觉熔断。backend=None 全清(任务边界, 兼容旧调用); 给了只清那一个(切模型时)。"""
    if backend is None:
        _FUSE.clear(); _CAP.clear()
    else:
        _FUSE.pop(_backend_id(backend), None)
        _CAP.pop(_backend_id(backend), None)


def _looks_like_no_vision(msg):
    low = str(msg).lower()
    return any(m in low for m in _NO_VISION_MARKS)


def _vision_cap(backend):
    """该模型能不能看图: 'ok' | 'no_vision' | None(还没试过)。"""
    return _CAP.get(_backend_id(backend))


def _mark_cap(backend, value):
    _CAP[_backend_id(backend)] = value
```

`ask_vision`（`:980-1037`）的 backend 分支替换为：

```python
    backend = active_backend()
    if backend is not None:
        cap = _vision_cap(backend)
        if cap == 'no_vision':
            # 明确拒绝, 不计熔断不重试: 这是配置问题, 不是网络问题。用户切到纯文本模型时
            # 旧实现会让它 2.4s 连错两次 → 熔断 120s → 整个游戏阶段瞎掉。
            raise RuntimeError(
                '当前任务选择的模型不支持图片(%s), 视觉通道已停用: 不要重试 ask_vision/see —— '
                '立即改用 droid.observe() 拿本地图标框、droid.ocr() 读画面文字, 或 ask_user 请用户'
                '换个支持图片的模型。' % (_backend_id(backend)[:80],))
        st = _fuse_state(backend)
        if st['n'] >= _VISION_FAIL_LIMIT and time.time() < st['until']:
            raise RuntimeError('该模型视觉连续失败已熔断 %ds: 不要重试 —— 立即改用 droid.observe()/'
                               'droid.ocr() 读屏, 或 ask_user。换个模型会自动解除。'
                               % _VISION_COOLDOWN_S)
        try:
            from vision_llm import ask_with_backend
            kw = {"timeout": timeout or _VISION_TIMEOUT_S}
            if max_pixels:
                kw["max_pixels"] = max_pixels
            result = ask_with_backend(backend, _crop_roi(image_input, roi), prompt, **kw)
        except Exception as exc:
            if _looks_like_no_vision(exc):
                _mark_cap(backend, 'no_vision')
                raise RuntimeError(
                    '当前任务选择的模型不支持图片(%s): %s。不要重试 ask_vision —— 立即改用 '
                    'droid.observe()/droid.ocr() 读屏, 或 ask_user。'
                    % (_backend_id(backend)[:80], str(exc)[:120])) from None
            st['n'] += 1
            if st['n'] >= _VISION_FAIL_LIMIT:
                st['until'] = time.time() + _VISION_COOLDOWN_S
            raise RuntimeError('视觉请求失败(%s): 不要重试 ask_vision —— 立即改用 droid.observe()/'
                               'droid.ocr() 读屏; 确需看图请在任务页选择支持图片的模型。'
                               % (str(exc)[:160],)) from None
        _mark_cap(backend, 'ok')
        st['n'] = 0
    else:
        raise RuntimeError('当前任务没有可用模型后端, 视觉不可用: 不要重试 ask_vision —— 立即改用 '
                           'droid.observe()/droid.ocr() 读屏, 或 ask_user。')
```

> `timeout` 此时已是调用方传入的原始值（Task 4 先不接 `_vision_total_budget`，那套在 Task 9 删；`see()` 在 Task 5 自带预算）。

删除 `_VISION_TLS` / `set_vision_backend` / `_vision_backend()` / `_vision_failed()` / `_vision_total_budget()`（`_vision_total_budget` 留到 Task 9 与常量一起删，本任务只把 `ask_vision` 对它的调用摘掉——改为直接用调用方传入值）。

`ga_android.py`：
- `code_run()` 的 `_run()`（`:44-48`）与 finally（`:58-63`）删掉 `droid.set_vision_backend(...)` 两处
- `do_code_run` inline_eval 分支（`:280-293`）同样删两处
- `code_run()` 函数签名的 `vision_backend=None` 参数删除，`do_code_run:295` 的实参删除
- `__init__`（`:219-226`）把 `droid.reset_vision_fuse()` 保留（无参=全清，兼容），并新增任务开始登记：

```python
        try:
            import droid; droid.set_active_backend(self._vision_backend())   # 任务边界登记模型后端
        except Exception: pass
```

- `_vision_backend()`（`:247-253`）docstring 补一句"任务开始与每次 /llm 后刷新"

> 注：`_vision_backend()` 在 `__init__` 里被调用时 `self.parent.llmclient` 可能尚未就绪（keyless 构造态）→ 返回 None → 视觉明确不可用（比旧的静默不设更好：至少报得出话）。任务真正开跑时由 `do_code_run` 前的 `_get_anchor_prompt` 路径不会再刷新——因此在 `agent_runner_loop` 每次 turn 前由 `turn_end_callback` 刷新一次即可。实现时在 `turn_end_callback` 开头加：

```python
        try:
            import droid; droid.set_active_backend(self._vision_backend())
        except Exception: pass
```

- [ ] **Step 4: 跑测试确认通过 + 适配**

Run: `python -m pytest tests/test_vision_lifecycle.py tests/test_vision_backend.py tests/test_vision_llm.py tests/test_vision_accel.py tests/test_droid_loop_guard.py -q`
Expected: 新用例全 PASS；`test_vision_backend.py` 中断言 `do_code_run` 传 `vision_backend` 的两个用例（`:50-63`）改为断言 `set_active_backend` 被登记——**保留"视觉用当前 agent backend"这条断言，只换机制**。

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q 2>&1 | tail -3`
Expected: passed 数 ≥ 631；failed ≤ 34 且集合不变（conftest 若漏改，这里会是一片 error 而不是失败，一眼可辨）。

```bash
git add app/src/main/assets/gacore/droid.py app/src/main/assets/gacore/ga_android.py conftest.py tests/test_vision_lifecycle.py tests/test_vision_backend.py
git commit -m "fix(droid): 视觉后端改模块级登记+能力分类+按模型熔断——纯文本模型不再换来 120s 全瞎" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 5: `see()` 第一级视觉工具

**Files:**
- Modify: `app/src/main/assets/gacore/ga_android.py`（新增 `do_see`，放在 `do_gui_act` 之后）
- Modify: `app/src/main/assets/gacore/droid.py`（`ask_vision`/`ask_point` 改为 `see()` 语义的 code_run 内薄封装）
- Modify: `app/src/main/assets/gacore/assets/tools_schema.json`、`tools_schema_cn.json`
- Test: `tests/test_see_tool.py`（新建）

**Interfaces:**
- Consumes: `droid.active_backend()`、`droid._vision_cap`、`droid._ASK_POINT_PROMPT`、`droid._parse_point`、`droid._resolve_roi`、`droid.shot()`
- Produces: 工具 `see`；`ga_android.GenericAgentHandler.do_see(args, response) -> StepOutcome`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_see_tool.py
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore'))
import numpy as np
import ga_android
import droid

_IMG = np.zeros((100, 200, 3), dtype='uint8')


class _Handler(ga_android.GenericAgentHandler):
    def __init__(self):
        self.working = {}; self.current_turn = 1; self.cwd = '.'
        self.code_stop_signal = []; self._done_hooks = []; self.print = lambda *a, **k: None
        self.history_info = []
        class _P: llmclient = None
        self.parent = _P()


def _wire(monkeypatch, answer='512,703', boom=None, cap=None):
    monkeypatch.setattr(droid, 'shot', lambda *a, **k: _IMG)
    monkeypatch.setattr(droid, 'screen', lambda: (200, 100))
    monkeypatch.setattr(droid, '_vision_cap', lambda be: cap)
    def fake(backend, image, prompt, **kw):
        if boom: raise RuntimeError(boom)
        return answer
    monkeypatch.setattr('vision_llm.ask_with_backend', fake)
    monkeypatch.setattr(droid, 'active_backend', lambda: object())


def _run(h, args):
    gen = h.do_see(args, None)
    try:
        next(gen)
    except StopIteration as e:
        return e.value
    return None


def test_see_text_returns_envelope(monkeypatch):
    h = _Handler(); _wire(monkeypatch, answer='大厅里有通行证入口')
    out = _run(h, {'question': '大厅里有什么'})
    d = json.loads(out.data)
    assert d['ok'] is True and d['answer'] == '大厅里有通行证入口'
    assert d['model'] and 'ms' in d


def test_see_point_returns_normalized_pair(monkeypatch):
    h = _Handler(); _wire(monkeypatch, answer='约 (512, 703)')
    out = _run(h, {'question': '通行证在哪', 'want': 'point', 'roi': 'lower'})
    d = json.loads(out.data)
    assert d['ok'] is True and (d['rx'], d['ry']) == (512, 703)


def test_see_point_rejects_percent(monkeypatch):
    h = _Handler(); _wire(monkeypatch, answer='85% 宽度处')
    out = _run(h, {'question': 'x', 'want': 'point'})
    d = json.loads(out.data)
    assert d['ok'] is False and 'percent' in d['reason'].lower() or '百分号' in d.get('hint', '')


def test_see_no_vision_model_is_structured_and_no_fuse(monkeypatch):
    h = _Handler(); _wire(monkeypatch, cap='no_vision')
    out = _run(h, {'question': 'x'})
    d = json.loads(out.data)
    assert d['ok'] is False and d['reason'] == 'model_no_vision'
    assert 'observe' in d['hint']


def test_see_requires_question(monkeypatch):
    h = _Handler(); _wire(monkeypatch)
    out = _run(h, {})
    assert out.data is not None and 'question' in str(out.data)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_see_tool.py -q`
Expected: FAIL，`AttributeError: 'GenericAgentHandler' object has no attribute 'do_see'`

- [ ] **Step 3: 实现 `do_see`**

`ga_android.py` 在 `do_gui_act` 之后插入：

```python
    _SEE_BUDGET_S = 90    # see() 自己的墙钟预算。视觉调用实测 15-46s, 而 code_run 默认只有 60s
                          # —— 旧实现让 ask_vision 在 code_run 里跟脚本抢这 60s, 一轮最多一次,
                          # 还要靠 4 个常量推导剩余。升为第一级工具后预算独立, 那套全删。

    def do_see(self, args, response):
        """看图问答(第一级工具, 不走 code_run)。

        什么时候用: 画面是 canvas/游戏/混淆(没有可用控件树, observe() 定位通道为空)、
        或目标不在 obs 里、或需要理解画面语义。普通控件树上的图标/按钮/输入框用 obs 就够,
        不要为"某个图标在哪"打视觉模型——本地 31ms, 视觉 15-46s。

        want='point' 拿坐标(固定问句 + 只认 0-1000 + 拒百分号, 可直接传 gui_act 的 rel);
        want='text' 拿自由文本。roi 送锚带名('title'/'status'/'navbar')或 0-1000 四元组,
        裁到局部像素量降 3-6 倍, 单次从 25-50s 降到 8-15s。"""
        import json, time
        import droid
        q = str(args.get('question') or '').strip()
        if not q:
            return StepOutcome('[Error] see needs question (what you want to know about the screen)',
                               next_prompt='\n')
        want = str(args.get('want') or 'text')
        if want not in ('text', 'point'):
            return StepOutcome("[Error] see want must be 'text' or 'point'", next_prompt='\n')
        roi = args.get('roi')
        try:
            box = droid._resolve_roi(roi) if roi else (0, 0, geom.NORM, geom.NORM)
        except ValueError as e:
            return StepOutcome('[Error] see roi: %s' % e, next_prompt='\n')
        try:
            max_pixels = int(args['max_pixels']) if args.get('max_pixels') else None
        except (TypeError, ValueError):
            return StepOutcome('[Error] see max_pixels must be an int', next_prompt='\n')
        backend = droid.active_backend()
        if backend is None:
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'no_backend',
                'hint': '当前任务没有可用模型后端, 视觉不可用。改用 obs 里的本地图标框或 droid.ocr() 读屏; '
                        '确需看图请在任务页选择支持图片的模型。'}, ensure_ascii=False), next_prompt='\n')
        if droid._vision_cap(backend) == 'no_vision':
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'model_no_vision', 'model': droid._backend_id(backend)[:80],
                'hint': '当前模型不支持图片, 视觉通道已停用。改用 obs 里的本地图标框或 droid.ocr() 读屏; '
                        '确需看图请换个支持图片的模型(切模型会自动解除)。'}, ensure_ascii=False),
                next_prompt='\n')
        t0 = time.time()
        try:
            img = droid.shot()
            if want == 'point':
                text = droid.ask_vision(img, droid._ASK_POINT_PROMPT % q, roi=box,
                                        timeout=self._SEE_BUDGET_S, max_pixels=max_pixels)
                cx, cy = droid._parse_point(text)
                rx1, ry1, rx2, ry2 = box
                rx = int(round(rx1 + cx / float(geom.NORM) * (rx2 - rx1)))
                ry = int(round(ry1 + cy / float(geom.NORM) * (ry2 - ry1)))
                out = {'ok': True, 'rx': rx, 'ry': ry}
            else:
                text = droid.ask_vision(img, q, roi=box, timeout=self._SEE_BUDGET_S,
                                        max_pixels=max_pixels)
                out = {'ok': True, 'answer': text}
        except Exception as e:
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'call_failed', 'error': '%s: %s' % (type(e).__name__, str(e)[:200]),
                'hint': '不要重试 see。改用 obs 里的本地图标框或 droid.ocr() 读屏; '
                        '确需看图检查当前模型是否支持图片, 或 ask_user。'}, ensure_ascii=False),
                next_prompt='\n')
        out.update({'ms': round((time.time() - t0) * 1000, 1),
                    'model': droid._backend_id(backend)[:80]})
        return StepOutcome(json.dumps(out, ensure_ascii=False),
                           next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))
```

`tools_schema.json` 追加（`_cn.json` 同构，描述用中文）：

```json
{
  "type": "function",
  "function": {
    "name": "see",
    "description": "Ask the current model what is on screen (vision). Use it ONLY when the local channels cannot answer: the screen is a game / self-drawn canvas / obfuscated page (no widget tree, so obs carries no usable boxes), or the target is not in obs, or you need to understand what the screen means. For ordinary widget trees, icons, buttons and input boxes are already in obs from the last gui_act - a local 31ms lookup beats a 15-46s vision call, so do NOT call see to find an icon on a normal page. want='point' returns a 0-1000 pair (pass it unchanged to gui_act's rel) using a fixed prompt that rejects percent answers; want='text' returns free text. roi crops before sending ('title'/'status'/'navbar' or a 0-1000 box) and cuts a call from 25-50s to 8-15s. One call per turn is enough. Never retry after a failure: switch to obs / droid.ocr() or ask_user.",
    "parameters": {
      "type": "object",
      "properties": {
        "question": {"type": "string", "description": "What you want to know about the screen. For want='point', name the target plainly (e.g. 'the magnifier icon in the title row')."},
        "want": {"type": "string", "enum": ["text", "point"], "description": "'point' = locate a target and return rx,ry (0-1000); 'text' = free-form answer. Default 'text'."},
        "roi": {"description": "Crop before sending: 'title'|'status'|'navbar'|'top'|'upper'|'middle'|'lower'|'bottom', or a 0-1000 [x1,y1,x2,y2]. Use it whenever you know roughly where the target is."},
        "max_pixels": {"type": "integer", "description": "Optional hard cap on encoded pixels. Omit unless the image is huge."}
      },
      "required": ["question"]
    }
  }
}
```

- [ ] **Step 4: 跑测试确认通过 + schema 契约测试**

Run: `python -m pytest tests/test_see_tool.py tests/test_tools_schema_contract.py -q`
Expected: 全 PASS；若 `test_tools_schema_contract.py` 断言工具数量/名单，把 `see` 补进期望（加断言，不删）。

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/ga_android.py app/src/main/assets/gacore/droid.py app/src/main/assets/gacore/assets/tools_schema.json app/src/main/assets/gacore/assets/tools_schema_cn.json tests/test_see_tool.py tests/test_tools_schema_contract.py
git commit -m "feat(gacore): see() 升为第一级视觉工具——预算与 code_run 解耦, 失败结构化不挂死" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 6: 看门狗——工具调用硬墙钟

**Files:**
- Modify: `app/src/main/assets/gacore/run_guard.py`
- Modify: `app/src/main/assets/gacore/ga_android.py`（`do_gui_act` 入口设截止）
- Test: `tests/test_watchdog.py`（新建）

**Interfaces:**
- Consumes: 既有 `run_guard.check()`（已在 `droid.py:180/429/435/990/1947/1957/1972/2062/2077/2090` 每个读写入口）
- Produces: `run_guard.enter_deadline(seconds)` / `run_guard.WatchdogExpired` / `run_guard.clear_deadline()`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_watchdog.py
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore'))
import run_guard


def test_check_raises_past_deadline():
    run_guard.enter_deadline(0.05)
    try:
        time.sleep(0.12)
        raised = False
        try:
            run_guard.check()
        except run_guard.WatchdogExpired:
            raised = True
        assert raised, '超过截止时刻后 check() 必须抛 WatchdogExpired'
    finally:
        run_guard.clear_deadline()


def test_check_passes_before_deadline():
    run_guard.enter_deadline(30)
    run_guard.check()          # 不得抛
    run_guard.clear_deadline()


def test_clear_deadline_is_idempotent():
    run_guard.clear_deadline()
    run_guard.clear_deadline()
    run_guard.check()          # 无截止上下文永不抛


def test_watchdog_expired_is_base_exception():
    """用户代码常见的 except Exception 不该吞掉它。"""
    assert issubclass(run_guard.WatchdogExpired, BaseException)
    assert not issubclass(run_guard.WatchdogExpired, Exception)


def test_cancel_token_still_works_alongside_deadline():
    tok = [False]
    run_guard.enter(tok, None)
    run_guard.enter_deadline(30)
    run_guard.cancel(tok)
    try:
        run_guard.check()
        raise AssertionError('令牌取消应优先抛 RunCancelled')
    except run_guard.RunCancelled:
        pass
    finally:
        run_guard.leave(); run_guard.clear_deadline()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_watchdog.py -q`
Expected: FAIL，`AttributeError: module 'run_guard' has no attribute 'enter_deadline'`

- [ ] **Step 3: 实现**

`run_guard.py` 在 `check()` 之前插入：

```python
class WatchdogExpired(BaseException):
    """本次工具调用已超过硬墙钟上限, 拒绝继续操作手机。继承 BaseException 以躲开 except Exception。"""


def enter_deadline(seconds):
    """登记本线程的看门狗截止时刻(itime.monotonic()+seconds)。None/<=0 = 不设。"""
    _tls.watchdog = (time.monotonic() + float(seconds)) if seconds and float(seconds) > 0 else None


def clear_deadline():
    _tls.watchdog = None


def watchdog_left():
    dl = getattr(_tls, 'watchdog', None)
    return None if dl is None else max(0.0, dl - time.monotonic())
```

`check()` 改为：

```python
def check():
    """副作用入口检查点: 令牌已取消抛 RunCancelled; 超过看门狗截止抛 WatchdogExpired。

    兼作看门狗检查点, 不新增调用点: droid 的每个读写入口早已调 check()
    (droid.py:180/429/435/990/1947/1957/1972/2062/2077/2090), 于是墙钟一超,
    下一个设备操作即自裁 —— 治真机 213s/260s 那种"工具调用挂住 + 空 tool_result",
    它的恢复只能中止整个任务并从原 prompt 重启, 此前进度全部作废。"""
    tok = getattr(_tls, "token", None)
    if tok and tok[0]:
        raise RunCancelled("code_run 已超时/被终止, 拒绝继续操作手机(僵尸线程护栏)")
    dl = getattr(_tls, 'watchdog', None)
    if dl is not None and time.monotonic() > dl:
        raise WatchdogExpired("工具调用超过墙钟上限, 已停止继续操作手机(看门狗)")
```

`ga_android.do_gui_act` 入口（`act = str(...)` 之前）加：

```python
        # 看门狗: gui_act 此前没有任何墙钟上限 —— 真机一次 wait(8s) 挂了 260s 并返回空
        # tool_result, 只能中止任务从头再来。设备侧每次调用自带 60s 超时, 故检查点式
        # 看门狗把失控半径压到 ≤1 次设备调用。
        try:
            run_guard.enter_deadline(self._GUI_ACT_BUDGET_S)
        except Exception:
            pass
```

finally 里清掉（`do_gui_act` 结尾 `return StepOutcome(...)` 之前包 try/finally，或在其 `except Exception as e` 分支之后统一清）。类常量：

```python
    _GUI_ACT_BUDGET_S = 120   # gui_act 硬墙钟。code_run 已有 timeout(默认 60s), see() 有自己
                              # 的 90s; gui_act 是唯一没有上限的工具, 真机 260s 那次就是它。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_watchdog.py tests/test_droid_loop_guard.py -q`
Expected: 全 PASS（`test_droid_loop_guard.py 是既有僵尸线程护栏回归，确认没被看门狗破坏）

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/run_guard.py app/src/main/assets/gacore/ga_android.py tests/test_watchdog.py
git commit -m "feat(run_guard): check() 兼作看门狗——工具调用超墙钟即自裁, 不再挂死成空 tool_result" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 7: 模型切换完整性——`setDefaultModel` 补 `/llm`

**Files:**
- Modify: `app/src/main/assets/gacore/webui/app.js:3446-3448`
- Test: `tests/test_default_model_switch.py`（新建，静态断言 JS 契约）

**Interfaces:**
- Consumes: 既有 `sendLlmSwitch(name, model)`（`app.js:2492-2495`）
- Produces: 无（修一条漏发的切换路径）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_default_model_switch.py
"""设置页「设为默认模型」必须真正切运行时, 不只写持久层。

漏的那次: setDefaultModel 只写 kv/ga.active.json + mykey.py, 不发 /llm → 当前会话的
agent backend 不切, 主对话和 vision 都继续用旧型号, 要等下次冷启才生效。"""
import os
import re

_JS = os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore', 'webui', 'app.js')


def _fn(name):
    src = open(_JS, encoding='utf-8').read()
    m = re.search(r'function %s\(([^)]*)\)\{(.*?)\n\}' % re.escape(name), src, re.S)
    assert m, 'function %s not found' % name
    return m.group(2)


def test_set_default_model_switches_runtime():
    body = _fn('setDefaultModel')
    assert 'sendLlmSwitch' in body, 'setDefaultModel 必须发 /llm, 否则运行时模型不切换'


def test_select_model_still_switches_runtime():
    body = _fn('selectModel')
    assert 'sendLlmSwitch' in body
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_default_model_switch.py -q`
Expected: FAIL，`AssertionError: setDefaultModel 必须发 /llm`

- [ ] **Step 3: 实现**

`app.js:3446-3448` 改为：

```javascript
function setDefaultModel(id){if(runLocked())return;editing.model=id;
  if(editingId&&active&&active.pid===editing.id){active={pid:editing.id,model:id};LS.set('active',active);
    sendLlmSwitch(editing.name,id,{noAbort:true});}   // 只写持久层不够: 不发 /llm 则当前会话 backend 不切, 主对话与 vision 都留旧型号直到下次冷启
  persistEditing();renderModelList();toast(t('t_defaultModel')+id)}
```

> `noAbort:true`：本入口已有 `runLocked()` 守门，无需再中止在飞任务。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_default_model_switch.py -q`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/webui/app.js tests/test_default_model_switch.py
git commit -m "fix(webui): 设为默认模型也要发 /llm——否则主对话与 vision 都留在旧型号" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 8: SOP 与 schema 重写成三步契约

**Files:**
- Modify: `app/src/main/assets/gacore/memory/phone_use.md`（§0.05 `:37-52` 删除、§0.1 `:53-` 删机制留纪律、§1 `:181-` 改指向、文件头插入三步契约）
- Modify: `app/src/main/assets/gacore/assets/tools_schema.json`、`tools_schema_cn.json`（`gui_act`/`code_run` 描述）
- Test: `tests/test_sop_three_step.py`（新建）

**Interfaces:**
- Consumes: `observe()`/`see()` 契约（Task 3/5）
- Produces: 无（纯契约文档）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sop_three_step.py
"""SOP 必须教三步契约, 且不得再教已搬进代码的机制细节。"""
import os

_SOP = os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'main', 'assets', 'gacore', 'memory', 'phone_use.md')


def _sop():
    return open(_SOP, encoding='utf-8').read()


def test_three_step_contract_is_at_the_top():
    head = _sop()[:1200]
    assert 'gui_act' in head and 'see()' in head and 'code_run' in head


def test_screen_kind_table_is_gone():
    """判据已进 _classify, 再留一张表就是让模型现推 + 双重真相。"""
    assert '## §0.05' not in _sop()


def test_vision_budget_mechanics_are_gone():
    """预算/一轮一次/从 code_run 剩余推导 都是 see() 的内部事, 不该占模型注意力。"""
    s = _sop()
    assert '从 code_run 的剩余时间自动推导' not in s
    assert '同一轮里调第二次' not in s


def test_canvas_judgement_discipline_survives():
    """删机制, 留判断纪律 —— 这些是真机踩出来的, 不能一起删。"""
    s = _sop()
    for keep in ('禁把 tap diff 当成功证据', '指纹比对', '层叠', '双通道', 'ask_user'):
        assert keep in s, keep
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sop_three_step.py -q`
Expected: FAIL（`## §0.05` 仍在）

- [ ] **Step 3: 改 SOP**

`phone_use.md` 头部（`# Phone Use — 手机 GUI 工具契约` 之后、`## §0.0` 之前）插入：

```markdown
## §0.-1 三步契约（每一步先对这张表）

| 你要做什么 | 用什么 | 坐标从哪来 |
| --- | --- | --- |
| **操作屏幕**（点/滑/输入/启动/等待） | `gui_act` | 上一条结果的 `obs`：`x/y` 是像素原样传 `point`，`rx/ry` 是 0-1000 原样传 `rel`。`obs` 为空或没有你要的目标才另想办法 |
| **看画面**（游戏盘面 / 自绘 canvas / 混淆页 / 目标不在 obs 里 / 要理解语义） | `see(question, want='point'|'text', roi=?)` | `want='point'` 直接给 `rx,ry`，原样传 `gui_act` 的 `rel` |
| **其它**（读画面文字、多步逻辑、非 GUI 工作） | `code_run` | `droid.ocr(droid.shot())` 读文字；`droid.observe()` 重新取一次本地定位 |

**普通控件树上的图标/按钮/输入框已经在 `obs` 里了**（本地 31ms），不要为"某个图标在哪"打
`see()`（15-46s）。反过来说：`obs` 里没有可用框、或画面是游戏/自绘/混淆页时，**不要**反复
`look()`/`ocr()` 试图定位——那类画面没有控件树，本地通道拿不到可点目标，直接 `see()`。
```

删除 §0.05 全节（`:37-52`）。§0.1 保留判断纪律、删掉机制叙述（"每轮最多一次 ask_vision"、
"总时长预算从 code_run 的剩余时间自动推导"、"首次进 canvas 页先用强降插图问区域边界"中属于
`see()` 内部行为的部分），把 `droid.ask_vision` 字样统一改为 `see()`。§1 工具表里 `look()` /
`ask_vision()` 两行改为指向 `observe()` / `see()`，并各加一句"旧名仍可用，形状不变"。

`tools_schema.json` / `_cn.json`：
- `gui_act` 描述删掉末尾 "Icon-only title/toolbar buttons … locate them in TWO tiers …" 整段（改由 `obs` 与 `see()` 分担）
- `code_run` 描述删掉 "Channel routing (decide once with droid.screen_kind(), don't try both): …" 整段，替换为一行：`To observe the screen use droid.observe() (returns kind + items with src); to read text off a game/canvas screen use droid.ocr(droid.shot()); to ask the model what is on screen use the see tool. Do not call look() on a canvas/game page - it has no widget tree and its boxes mislead.`

- [ ] **Step 4: 跑测试确认通过 + 全套**

Run: `python -m pytest tests/test_sop_three_step.py tests/test_phone_task_regressions.py tests/test_tools_schema_contract.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/memory/phone_use.md app/src/main/assets/gacore/assets/tools_schema.json app/src/main/assets/gacore/assets/tools_schema_cn.json tests/test_sop_three_step.py
git commit -m "docs(gacore): SOP 重写成三步契约——判据与预算已进代码, 不再让模型现推通道" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 9: 删除被取代的机制

**Files:**
- Modify: `app/src/main/assets/gacore/droid.py`（删 `_vision_total_budget` + `_VISION_TOTAL_S`/`_VISION_RESERVE_S`/`_VISION_MIN_S`、`look(yolo=)`/`ui_detect(yolo=)` 形参、`vision_api` 兜底分支的残留引用）
- Modify: `app/src/main/assets/gacore/ga_android.py`（`_compact_obs` 里已无 kind 分支则确认无残留）
- Test: `tests/test_dead_code_gone.py`（新建）

**Interfaces:**
- Consumes: Task 3/4/5 的产物
- Produces: 无（纯删除）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dead_code_gone.py
"""被 observe()/see() 取代的机制必须真删掉, 不是留着不调。"""
import os
import subprocess

_ROOT = os.path.join(os.path.dirname(__file__), '..')


def _gacore():
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, 'app', 'src', 'main', 'assets', 'gacore')):
        if '__pycache__' in dirpath:
            continue
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.join(dirpath, f))
    return out


def _all_src():
    return '\n'.join(open(p, encoding='utf-8', errors='replace').read() for p in _gacore())


def test_vision_total_budget_is_gone():
    assert '_vision_total_budget' not in _all_src()


def test_budget_constants_are_gone():
    s = _all_src()
    for c in ('_VISION_TOTAL_S', '_VISION_RESERVE_S', '_VISION_MIN_S'):
        assert c not in s, c


def test_vision_api_fallback_is_gone():
    """memory/vision_api.py 从来不存在(只有 .template.py), 那条兜底必然报错。"""
    assert 'from vision_api import' not in _all_src()


def test_vision_tls_is_gone():
    assert '_VISION_TLS' not in _all_src()


def test_no_unused_imports_left_in_droid():
    """死代码铁律: 顺带确认 run_guard 仍被用(看门狗), 没留只赋值不读取的变量。"""
    s = _all_src()
    assert 'run_guard.check()' in s
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_dead_code_gone.py -q`
Expected: FAIL（`_vision_total_budget` 仍在）

- [ ] **Step 3: 删除**

`droid.py`：
- 删 `_VISION_TOTAL_S` / `_VISION_RESERVE_S` / `_VISION_MIN_S` 三个常量与 `_vision_total_budget()` 整个函数
- `ask_vision` 里 `timeout = _vision_total_budget(timeout)` 一行删除，`timeout` 直接用调用方传入值（`see()` 传 90，code_run 内裸调走默认 `_VISION_TIMEOUT_S=30`）
- `look()` 的 `yolo=None` 形参删除（Task 3 已把它变成忽略位，这里收口）；`ui_detect(img, conf=0.25)` 删 `yolo=True` 形参，内部恒 `detect(img, conf=conf)`——`observe()` 已按 kind 决定要不要调它
- 确认无 `vision_api` 残留 import

`ga_android.py`：确认 `_compact_obs` 无 kind 分支残留（Task 3 已替换）

- [ ] **Step 4: 跑测试确认通过 + 全套门禁**

Run: `python -m pytest tests/ -q 2>&1 | tail -3`
Expected: passed 数 ≥ Task 3 时的值；failed 不超基线 34 且仍是 Playwright/Windows 文件模式那批。

Run: `python tools/audit_source.py 2>&1 | tail -3`
Expected: `0 findings`

Run: `git diff --check`
Expected: 无输出

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/droid.py app/src/main/assets/gacore/ga_android.py tests/test_dead_code_gone.py
git commit -m "refactor(droid): 删掉被 observe()/see() 取代的预算推导与 yolo 形参——清债务不留死码" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 10: 真机回归 + 打包推送

**Files:**
- 修改：无（验证与交付）
- 证据：`temp/logpull/` 下的运行日志

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 装机 APK + 回归证据

- [ ] **Step 1: 全套测试门禁**

Run: `python -m pytest tests/ -q 2>&1 | tail -3`
Expected: `631 passed` 以上（Task 1-9 新增约 40 用例）；failed ≤ 34 且集合不变。

- [ ] **Step 2: 构建 APK**

工具链在 `E:\project\build-toolchain`。**不要用 `build-gagent.cmd`/`.sh`**（实测 cmd 按 GBK 解析中文注释错位、sh 把 `E:/...` 放进 PATH 被 `:` 拆坏），在 Git Bash 里直接调 Gradle 并显式给全环境变量：

```bash
cd /e/project/daiyimo/GAgent
SDK=$(cygpath -m "$LOCALAPPDATA/Android/Sdk")      # 不写死用户名: audit_source 的 personal-path 规则会拦
JAVA_HOME=E:/project/build-toolchain/jdk17.0.21_0 \
ANDROID_HOME="$SDK" \
ANDROID_NDK_HOME="$SDK/ndk/25.1.8937393" \
CHAQUOPY_PYTHON=E:/project/build-toolchain/py310full/tools/python.exe \
PATH=/e/project/build-toolchain/gradle-8.2/bin:$PATH \
gradle :app:assembleDebug --no-daemon --console=plain 2>&1 | tail -25
```

Expected: `BUILD SUCCESSFUL`；产物 `app/build/outputs/apk/debug/app-debug.apk`（约 132MB，增量约 21s）

> 版本硬约束不可换：gradle-8.2（AGP 8.1.4）、JDK17（AGP 8.1.4 用 JDK 21 会 `jlink` 失败）、Chaquopy 3.10 要 CPython 3.10 且必须是非 embeddable 包（要建 venv）。

- [ ] **Step 3: 装机**

```bash
adb -s ZYPZ261A01M68700159 install -r app/build/outputs/apk/debug/app-debug.apk
```

Expected: `Success`

> **装机会清空应用数据**（2026-10-27 实测：重装后模型/provider 配置、设备版 phone_use 与 recipes 全丢）。装机后必须让用户重新导入 YOLO 模型与 provider，否则真机回归测的是"没有 YOLO"的路径，不是本次改动的目标路径。

- [ ] **Step 4: 真机回归（同一任务，对标 C 次运行 4min/20 轮）**

任务：`在微信中搜索小程序 元梦之星 小游戏 并进入到游戏主页面，关闭所有开屏广告，进入到大厅 点击通行证 并告诉我都有哪些核心模块`

拉取运行记录：

```bash
adb -s ZYPZ261A01M68700159 shell "run-as io.github.shenhaostu.gagent.debug ls -t /data/data/io.github.shenhaostu.gagent.debug/files/ga/temp/model_responses/ | head -3"
```

逐条核对 spec §8 的四条验收：

- [ ] 轮数 ≤ 20、墙钟 ≤ 5 min
- [ ] 零空返回（无 213s/260s 那种挂死）
- [ ] 游戏段定位来源可从 `obs.kind` / `see()` 信封读出来
- [ ] 微信段 `obs` 里有无文字图标框（YOLO 生效）

- [ ] **Step 5: 记录结论**

把实测轮数/墙钟/各段定位来源写进 `docs/superpowers/specs/2026-10-28-perception-routing-observe-see-design.md` 的 §8 真机验收小节（**只写实测值，不写预期**）。若某条不达标：记录不达标的那一条与观测到的现象，不宣称通过。

- [ ] **Step 6: 提交证据**

```bash
git add docs/superpowers/specs/2026-10-28-perception-routing-observe-see-design.md
git commit -m "docs(spec): 补感知重构 M1-M4 真机回归实测值" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```
