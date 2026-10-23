# Practical cases / 实操案例

[Setup](CONFIGURATION.md) · [Validation](VALIDATION.md) · [AndroidBench](https://androidbench.gaagent.ai/)

The first four cases summarize the recorded Pixel development run. Prompts below
are reusable examples, not a claim that these exact rewritten prompts were rerun.
The tested model was GLM-5.3-flash; app history and an optional detector were retained.
Warm state and iterative fixes limit comparisons. Details and source revision are
in [Validation](VALIDATION.md).

前四项来自既有 Pixel 开发验收，下面的指令是便于复用的示例，不是本轮新测试。
当时使用 GLM-5.3-flash，保留了应用历史与可选检测模型，不能外推到所有模型或全新安装。

<a id="settings"></a>
## 1. Change and verify a setting / 修改并核验设置

> 把自动亮度关闭，将亮度调到最低；读回实际状态，再恢复原来的亮度和模式。
>
> Turn off adaptive brightness, set the lowest brightness, verify it, then restore the original mode and value.

**Setup:** phone-use permissions; record the original setting first.
**Evidence:** both setting tasks passed. The final stored brightness was read back
as `1`; the adaptive-mode state was checked and original settings restored.
**Check yourself:** inspect the mode and value, not only a slider tap or a reply saying “done”.

先记录原值。既有两题均通过，亮度读回为 `1`，模式经过核验，测试后恢复原设置。
不同系统的数值范围可能不同，不要把这个读数当成所有手机的通用坐标或固定值。

<a id="video-search"></a>
## 2. Search and sort content / 搜索与排序

> 在 B 站搜索一个我指定的主题，按“播放多”排序，列出前三条的标题与 UP 主；不要点赞、关注或发评论。
>
> Search Bilibili for my topic, sort by most played, and list three titles and creators without interacting with the accounts.

**Setup:** installed app and a usable existing session.
**Evidence:** the simpler task verified the selected sort control and read back
titles/creators; its filter drawer was left open. The harder date-plus-duration
task remained partial: its date interval broadened and combined duration selections
were not established.
**Check yourself:** selected filter state and returned content must both match.

简单排序通过；复杂日期与时长组合筛选尚未通过。只看首条结果日期正确，不能证明筛选条件正确。

<a id="route"></a>
## 3. Read a route without starting it / 查路线，不启动导航

> 在高德查询从「起点」到「终点」的驾车路线，告诉我预计时间和距离，不启动导航或叫车。
>
> Read the driving time and distance from [start] to [destination] in Amap; do not start navigation or book a ride.

**Setup:** replace both placeholders with your intended locations; allow location
access only if the task needs the current location.
**Evidence:** the recorded task returned **33 minutes / 12 km**, with no navigation
started. A matching historical route helped the run. These values describe that
old task, not live travel advice or the result for your locations.
**Check yourself:** start, destination, travel mode, time and distance together.

旧任务读回 33 分钟 / 12 公里，并利用了匹配历史路线。地址和交通会变化，不能复用旧结果作为新查询答案。

<a id="wechat"></a>
## 4. WeChat mini-program, pure GUI / 微信小程序，纯 GUI

> 打开微信，在麦当劳小程序中按当前默认门店选择一份单人汉堡餐。只用截图和 GUI。
> 到提交订单前停止，告诉我商品和总价；遇到手机号登录先停下，不提交订单、不付款。
>
> Open McDonald's in WeChat and select a meal using screenshots and GUI only. Stop before submitting; pause at phone login and do not pay.

**Setup:** existing WeChat session, screenshot/gesture permissions, image-capable
vision adapter; optional YOLO can help with unlabeled controls. Store and menu state vary.
**Evidence:** the recorded run dismissed a promotion, opened the menu and selected
a **¥33.5 McChicken meal** with medium fries and cola. Add-to-cart reached a phone
login prompt. The owner deferred login, so cart confirmation, checkout, order
submission and payment were **not completed**.
**Check yourself:** merchant, store, items, quantity and displayed price; account
authorization is a separate decision. No node-tree reads, target-app CDP or private APIs.

实际完成到选餐，停在加购时的手机号登录，未证明加购成功，也未到结算页。
价格仅为该次记录，不是当前报价。此案例展示可核验的边界，不作为购物全流程成功案例。

<a id="recipes"></a>
## 5. More workflows to try / 其他可复用示例

These are suggested workflows supported by existing tools, **not new acceptance
results**. Configure prerequisites and verify the output before relying on them.
以下为示例配方，不计入实测成绩。

| Workflow / 场景 | Try saying / 示例指令 | Prerequisite and check / 条件与核验 |
| --- | --- | --- |
| Local files / 本地文件 | “Create a three-day study plan in Markdown in my chosen folder; show the saved path and read it back.” / “在我选定的目录创建三天学习计划，返回路径并读回内容。” | File access; verify a real file exists, without overwriting an existing one / 文件权限；核验真实文件，避免覆盖 |
| Reusable procedure / 复用方法 | “Save the verified steps for this task as a reusable procedure; keep device coordinates and personal data out.” / “将已验证步骤整理为可复用规程，不保留屏幕绝对坐标和个人数据。” | Review the saved text and try it on fresh observations / 检查内容并重新观察后复用 |
| Voice input / 语音 | Dictate a short note, check the transcript, then decide whether to send / 口述短便签，核对转写后再决定发送 | Configured compatible voice relay + microphone / 兼容语音服务和麦克风 |
| Scheduled task / 定时 | “In ten minutes, prepare a local checklist. Show me the schedule and how to cancel it.” / “十分钟后生成本地清单，列出任务及取消方法。” | Verify stored rule, cancellation and actual delivery; background restrictions apply / 核验规则、取消与到达，受后台限制 |
| Computer handoff / 电脑协作 | “On my paired computer, read this test folder and summarize the filenames; do not modify files.” / “在已配对电脑读取测试目录并总结文件名，不修改文件。” | Compatible PC Link/GAnet service, own peer, read-only test directory / 兼容服务、自有设备、只读测试目录 |

## Read the evidence / 如何读结果

The representative development sample had **4 passed, 3 partial, 1 login-blocked**
outcomes across eight queries. The final geometry/overlay build did not rerun the
entire sample. No overall success-rate or speedup claim follows from these examples.

The public [AndroidBench case explorer](https://androidbench.gaagent.ai/#traces)
and [methodology](https://androidbench.gaagent.ai/#method) offer additional studies.
Keep their models, tasks and budgets separate from this repository's snapshot.
Share minimized, redacted evidence; private device screenshots and conversations
are not part of these docs.
