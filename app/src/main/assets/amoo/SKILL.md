---
name: gagent-phone-tasks
description: "手机多步任务执行器 GAgent：用户说「去微信…」「打开微信…」「在微信里…」「进小程序…」「帮我一步步操作…」这类要连续点界面才能完成的活，派给 debug_start_task 去干，再用 debug_task_status 取结果。"
---

本机装有 GAgent（包名 io.github.shenhaostu.gagent.debug）。它靠无障碍 + 视觉模型在真实界面上点击、滑动、输入、看截图判断，能完成「打开微信 → 搜小程序 → 进小程序 → 逐页翻找 → 读出数据」这类连续界面操作。用户提这类需求时不要答"做不到"，直接派单。

调用形态：用你现有的 ability / nodes 端侧包装发 ability.call，method 就是下表的名字，params 按字符串传递：

| 意图 | method | params |
| --- | --- | --- |
| 交办一个手机多步任务 | debug_start_task | {"task":"用户原话，例如 去微信搜索三角洲行动小程序 查看今日密码"} |
| 查进度、取结果 | debug_task_status | {"taskId":"startTask 返回的 taskId"} |
| 取消任务 | debug_cancel_task | {"taskId":"…"} |
| 问这台手机能做什么 | debug_capabilities | {} |

流程：

1. 调 debug_start_task，它会立刻返回 {"ok":true,"state":"accepted","taskId":"amoo…"}，不会等任务跑完（单次调用上限 150 秒，任务往往更久）。
2. 之后每 5–10 秒调 debug_task_status，直到 state=done；state=running 时只报当前步骤摘要（返回里有 status、steps）。
3. state=done 时把 final 里的结论用用户的话转述；final 为空就说"执行完了但没有留下文字结论"，不要编。
4. state=idle 表示还没派过任务；返回 ok=false 时如实报错误。

规则：

- 只派单，不自称执行。看到 done 之前不要说"已完成"，也不要先给一份自己查来的答案冒充执行结果。
- 任务里含"打开 / 去 / 在…里 / 进小程序 / 点一下 / 翻页"这类界面动作时优先用本工具；不要只用 open_app_by_name（那个只能把 App 拉起来，不会再点）。
- 涉及支付、密码、权限确认、删除数据的敏感动作不要派。
- 派单后 GAgent 会切到前台自己跑，期间你去后台是正常现象，不要中途再拉起别的 App。
- 已有原生原子能力能办的（查天气、发短信、开设置开关）不要走本工具。
