# Vision SOP (Android端)

## 前置规则
1. **能不用 vision 就不用**：droid.dump()(a11y树) / droid.ui_detect()(检测框+OCR) 能解决就不调 vision API。Vision 是最后手段(看图答疑/验证上屏/OCR搞不定的版式)。
2. 截图用 `droid.shot()`(返回BGR ndarray, 直接传给ask_vision) 或 `droid.shot(path)`。

## 用法
```python
from vision_api import ask_vision
ask_vision(droid.shot(), '描述当前界面')  # 返回str; 失败为 'Error: ...'
```

## 没有 memory/vision_api.py 时(初次自建)
按 `memory/vision_api.template.py` 头部三步说明操作：复制为 vision_api.py → 扫 mykey 配置变量名(禁止输出key值)填头部 → 小图实测。

Anthropic 视觉请求复用该 provider 的 `max_tokens`，未设置时为 8192；推理和回答共用输出预算。小图成功后，还需用真实任务截图验证完整回答。`stop_reason=max_tokens` 表示截断，不能据此操作；调整 provider 预算后再验证，不自动反复请求。已复制的旧 `vision_api.py` 不随 APK 覆盖，升级模板实现时保留头部配置引用，不复制密钥值。
