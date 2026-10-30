# Vision SOP (Android端)

## 前置规则
1. **能不用 vision 就不用**：droid.dump()(a11y树) / droid.ui_detect()(检测框+OCR) 能解决就不调 vision API。Vision 是最后手段(看图答疑/验证上屏/OCR搞不定的版式)。
2. **感知双通道皆不可用时就停**：dump 为空/敏感置空、look()/ocr 无有效结果、ask_vision 抛错(含"已熔断"/"未配置")——此时禁止自行编写 OpenCV/PIL 图像分析代码去盲猜(真机实证一: 手写阈值/HV/降采样分析棋盘, 每轮 5-37s 模型调用花在写 CV 代码上, 仍看不出图案, 300s 未完成; 实证二: 同一路径玩羊了个羊 41 步/7 分钟 0 消除, 指纹比对产出 0.58"确定的一对"与 1.00"三张相同"两个假阳性, 且据 tap diff 虚假宣称"已消除"并换目标)。正确做法: ask_user 报告感知缺口, 或换不需要看画面的路径。消除类棋盘 tap 后必须核验卡槽实际内容再认定成功——diff 非零只证明画面变了。
3. 截图用 `droid.shot()`(返回BGR ndarray, 直接传给ask_vision) 或 `droid.shot(path)`。

## 用法
```python
# 必须用 droid.ask_vision（已预导入，勿再从 vision_api 导入！）
# 它统一提供: roi(0-1000 裁剪)/max_pixels(降采样)/timeout(单次上限30s)/连续失败熔断120s
ask_vision(droid.shot(), '描述当前界面')                          # 全屏(仅首次问边界)
ask_vision(droid.shot(), '卡槽有哪几张牌', roi=[0,700,1000,1000])  # 只送局部, 快 3-6 倍
ask_vision(droid.shot(), '哪三张图案相同、哪张在顶层可拿', roi=[0,600,1000,900])  # 消除类棋盘每步必问(层叠盘, 禁固定网格/禁指纹比对)
ask_vision(droid.shot(), '可交互区域百分比边界', max_pixels=300000) # 强降插图问边界
```

**禁止 `from vision_api import ask_vision`**：裸调用没有 ROI/超时/熔断，
真机实证单次全屏 60s 超时后 agent 放弃视觉、盲玩 20 轮（白烧 300s+）。
code_run 已预导入 `from droid import ask_vision`，直接调用即可。

## 模型来源
`ask_vision` 默认复用**任务页当前选择的模型**（多模态）：同一个 provider / model / key / proxy，切换模型时自动跟随，不需要单独配置。
只有需要独立的视觉后端/端点时，才复制 `memory/vision_api.template.py` → `memory/vision_api.py`；它仅在该任务没有可用模型时作为后备。

如果当前模型不支持图片，`ask_vision` 会明确报错，立即改用 `droid.look()`/`droid.ocr()`，不要重试或自写 CV。

Anthropic 视觉请求复用该 provider 的 `max_tokens`，未设置时为 8192；推理和回答共用输出预算。小图成功后，还需用真实任务截图验证完整回答。`stop_reason=max_tokens` 表示截断，不能据此操作；调整 provider 预算后再验证，不自动反复请求。已复制的旧 `vision_api.py` 不随 APK 覆盖，升级模板实现时保留头部配置引用，不复制密钥值。
