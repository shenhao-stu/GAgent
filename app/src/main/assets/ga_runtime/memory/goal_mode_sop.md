# Goal Mode SOP

## 何时用
用户给开放目标 + 时间预算(如"花3小时持续优化X"、"没事也找事干"), 非一次性闭环任务。

## 设置
写 `temp/goal_state.json`(或自定义路径):
```json
{"objective": "用户原话目标", "budget_seconds": 10800, "start_time": <time.time()>,
 "turns_used": 0, "max_turns": 200, "status": "running", "done_prompt": ""}
```
- budget_seconds 最少 3 小时(10800), 按用户要求调; max_turns 防空转, 一般 200; status 必须 `"running"`。

## 启动(必须后台, 不占前台终端)
```bash
start /b python agentmain.py --reflect reflect/goal_mode.py                       # 默认 temp/goal_state.json
set GOAL_STATE=temp/goal_xxx.json && start /b python agentmain.py --reflect reflect/goal_mode.py            # 自定义路径(多实例)
set GOAL_STATE=temp/goal_xxx.json && start /b python agentmain.py --reflect reflect/goal_mode.py --llm_no 1 # 换模型(第N个LLM, 从0起)
```

## 停止 / 观察
- 预算耗尽自动收口轮后停止; 手动停=杀进程。
- 状态: 读 goal_state.json 的 turns_used/status; 详情: 看 `temp/model_responses/` 最近文件尾部。
