# 能力解锁 / Onboarding SOP

> 触发见 `modes_index`。范式对齐桌面 `GETTING_STARTED §5`: 每项能力对我说一句话即可解锁。
> `capabilities.json` 是能力单一真相源——逐项读 json 驱动，本文件不写死清单(加能力=加 json 一项)。与机型无关，厂商助手由探针现场发现。

## 核心循环(每项四步)
1. **讲 why**: 用 `capability.why`(按 `GA_LANG` 选 zh/en)一句话说清解锁后能多做什么。
2. **引导解锁**: 照 `capability.unlock` 指路径，用户自己点，GA 引导。
3. **跑探针**: 执行 `capability.probe`(只读)。真值=解锁，假=未解锁——以探针为准。探针失败八成是用户还没点开 → 复述 unlock 再请一次，不硬推。
4. **回填** ✓/✗，进下一项。

## 顺序
`accessibility` 必先(跨 App 执行+读屏的总主控，没它其余几乎空转)；其余顺序不敏感: overlay/record_audio/install_unknown(权限逐项引导) → asset_scan(`droid.pkgs()` 列已装 App) → vendor_assistant(`vendor_bridge.discover` 现场识别，细节见 `vendor_assistant_sop`) → vision(内置 ONNX 免授权，A11y 树缺失时兜底)。

## 探针约定
- `droid.*` 探针直接 `code_run`(如 `droid.ping().get('a11y')`)。
- `perm:*`/`ui:*`(麦克风/悬浮窗/安装未知来源等系统授权态): 引导用户开后让其回话确认，或用真实动作旁证(如切到别的 App 看 GA 浮窗是否仍在)。能问就问，不为验证权限 dump 系统设置整树。

## 末尾产出: 能力地图
- 已解锁 `✓ <name>` — 一句话点出现在能做什么；未解锁 `✗ <name>` — 给可解释原因 + 原样复述 unlock。
- 收口: `★ accessibility 是地基；其余按需解锁，随时对我说对应话术即可。`

## 注意
- 系统授权由 Android 交用户在系统里开，GA 引导+探针验证即可；枚举已装 App 只为能力地图，不深挖隐私。
- 微信只走视觉(`gandroid-wechat-yolo`)。
