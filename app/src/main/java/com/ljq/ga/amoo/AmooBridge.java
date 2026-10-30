package com.ljq.ga.amoo;

import android.content.Context;
import android.content.Intent;

import com.ljq.ga.MainActivity;
import com.ljq.ga.Py;

import org.json.JSONObject;

/**
 * amoo(StepOS 语音助手 com.stepos.ailauncher) -> GA 的任务通道。
 *
 * amoo 侧实测链路(真机日志): amoo 模型 -> ability(search/exec) -> AbilityAgentBusNode
 *   -> AbilityManager.getAbilityMetaData(toolName -> pkg+functionId)
 *   -> JetpackAppFunctionsCallToolHandler -> 本应用的 AppFunctionService。
 * 第三方 AppFunctions 的工具名与描述在**装包时**就被 amoo 的本地 BM25 目录收录(无需云端审核),
 * 所以这里的函数描述写"微信"就是在写触发词。
 *
 * 两个约束:
 *   1) AppFunctions 单次调用超时 30s(amoo 原生工具只有 4.95s) => startTask 必须秒回 taskId;
 *      真正的执行发生在 GA 前台, 进度靠 taskStatus 轮询。
 *   2) Python(agent) 跑在 GA 进程里, 只由 MainActivity 启动时 boot => 服务只负责拉起 Activity,
 *      入队交给 Activity boot 之后调用 dispatch()。
 */
public final class AmooBridge {
    public static final String EXTRA_TASK = "ga_amoo_task";
    public static final String EXTRA_CID = "ga_amoo_cid";
    public static final String SRC = "amoo";

    private static final int MODE_MULTI = 1;
    private static final int MODE_SINGLE = 2;

    private static volatile String lastTaskId = "";
    /** 入队走的是哪条路: 多会话(send2/poll2) 还是焦点会话(send/poll)。状态要用同一条路去查。 */
    private static volatile int mode = MODE_MULTI;

    private AmooBridge() {}

    public static String newTaskId() {
        return "amoo" + Long.toString(System.currentTimeMillis(), 36);
    }

    public static String lastTaskId() {
        return lastTaskId;
    }

    /** 拉起 GA 前台并把任务挂到 Activity 上(boot 完成后由 Activity 调 dispatch)。 */
    public static void launch(Context ctx, String cid, String task) {
        lastTaskId = cid;
        Intent i = new Intent(ctx, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        i.putExtra("ga_src", SRC);
        i.putExtra(EXTRA_CID, cid);
        i.putExtra(EXTRA_TASK, task);
        ctx.startActivity(i);
    }

    /** Py 已就绪后真正入队(send2/send 都是异步的: 设 running / 起 drain 线程后立刻返回)。 */
    public static String dispatch(String cid, String task) {
        try {
            if (!Py.INSTANCE.getReady()) return "ERR:python not ready";
            // 多会话默认关闭: send2(显式 cid) 会回 "多会话未启用" —— 此时退回焦点会话的 send,
            // 与 WebUI 桥的处理一致(MainActivity.Bridge.send 的同款降级)。
            String r = Py.INSTANCE.call("send2", cid, task);
            if (r == null || r.isEmpty()) {
                mode = MODE_MULTI;
                lastTaskId = cid;
                return "ok";
            }
            String r2 = Py.INSTANCE.call("send", task);
            if (r2 == null || r2.isEmpty()) {
                mode = MODE_SINGLE;
                lastTaskId = cid;
                return "ok";
            }
            return "ERR:" + (r2.length() > 0 ? r2 : r);
        } catch (Throwable e) {
            return "ERR:" + e;
        }
    }

    /**
     * 分享接单(A 路线): 任何 App 把一句话 ACTION_SEND 给 GA, 就直接当任务跑。
     * 这条链路完全在端侧, 不经过 amoo 的能力目录, 所以不受 hasAbilityId/云端审核影响。
     */
    public static String taskFromShare(Intent it) {
        if (it == null) return "";
        String act = it.getAction();
        if (!Intent.ACTION_SEND.equals(act)) return "";
        CharSequence t = it.getCharSequenceExtra(Intent.EXTRA_TEXT);
        if (t == null || t.toString().trim().isEmpty()) {
            t = it.getCharSequenceExtra(Intent.EXTRA_SUBJECT);
        }
        String s = t == null ? "" : t.toString().trim();
        // 分享面板常带 标题+正文 两段(引用块), 只取第一段非空文字做任务
        int nl = s.indexOf((char) 10);
        if (nl > 0) {
            String head = s.substring(0, nl).trim();
            if (!head.isEmpty()) s = head;
        }
        return clip(s, 800);
    }

    /** 把结果推回 amoo: ShareActivity 会预填输入框(实测不会自动发送, 由用户点一下发送)。 */
    public static void report(Context ctx, String text) {
        try {
            Intent i = new Intent(Intent.ACTION_SEND);
            i.setType("text/plain");
            i.setClassName("com.stepos.ailauncher", "com.stepos.ailauncher.chat.activity.ShareActivity");
            i.putExtra(Intent.EXTRA_TEXT, text);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
            android.util.Log.i("GaAmoo", "report len=" + text.length());
        } catch (Throwable e) {
            android.util.Log.i("GaAmoo", "report fail " + e);
        }
    }

    /**
     * 盯到任务收尾就回推 amoo。轮询 6s 一次, 上限 40 分钟; 只回推本次派单的 cid,
     * 免得把别的会话的旧结果当成这次的结果(状态本来就是按 cid 查的)。
     */
    public static void watchAndReport(final Context ctx, final String cid) {
        String appCtx = ctx == null ? "" : ctx.getClass().getSimpleName();
        if (appCtx.isEmpty()) return;
        final Context c = ctx.getApplicationContext() == null ? ctx : ctx.getApplicationContext();
        Thread t = new Thread(new Runnable() {
            @Override public void run() {
                long deadline = System.currentTimeMillis() + 40L * 60L * 1000L;
                while (System.currentTimeMillis() < deadline) {
                    try {
                        Thread.sleep(6000L);
                        JSONObject o = new JSONObject(status(cid));
                        String st = o.optString("state", "");
                        if ("done".equals(st)) {
                            String fin = cleanFinal(o.optString("final", ""));
                            StringBuilder sb = new StringBuilder("GAgent 执行完毕");
                            sb.append((char) 10);
                            sb.append(fin.isEmpty() ? "(没有留下文字结论, 画面已在手机上执行完)" : fin);
                            report(c, clip(sb.toString(), 1200));
                            return;
                        }
                        if ("idle".equals(st) || "unknown".equals(st)) return;
                    } catch (InterruptedException ie) {
                        return;
                    } catch (Throwable e) {
                        android.util.Log.i("GaAmoo", "watch err " + e);
                    }
                }
            }
        }, "ga-amoo-watch");
        t.setDaemon(true);
        t.start();
    }

    /** 读执行进度: 复用 python 侧会话状态(poll2), 不另存文件, 免得两处状态打架。 */
    public static String status(String taskId) {
        String cid = (taskId == null || taskId.isEmpty()) ? lastTaskId : taskId;
        try {
            JSONObject out = new JSONObject();
            if (cid.isEmpty()) return out.put("ok", false).put("state", "idle")
                    .put("hint", "还没有通过 amoo 发起过任务").toString();
            out.put("taskId", cid);
            if (!Py.INSTANCE.getReady()) return out.put("ok", false).put("state", "starting")
                    .put("hint", "GAgent 正在启动, 稍等再查").toString();
            String raw = (mode == MODE_SINGLE)
                    ? Py.INSTANCE.call("poll", "0")
                    : Py.INSTANCE.call("poll2", cid, "0");
            JSONObject o = new JSONObject(raw == null ? "{}" : raw);
            if (o.has("error") && !o.isNull("error")) {
                return out.put("ok", false).put("state", "unknown")
                        .put("error", o.optString("error")).toString();
            }
            boolean running = o.optBoolean("running", false);
            String end = o.optString("end", "");
            String state = running ? "running" : (end.isEmpty() ? "idle" : "done");
            out.put("ok", true);
            out.put("state", state);
            out.put("status", o.optString("status", ""));
            out.put("steps", o.optJSONArray("steps") == null ? 0 : o.optJSONArray("steps").length());
            out.put("final", clip(o.optString("final", ""), 1500));
            if (!end.isEmpty()) out.put("end", end);
            return out.toString();
        } catch (Throwable e) {
            return "{\"ok\":false,\"state\":\"unknown\",\"error\":\"" + esc(e.toString()) + "\"}";
        }
    }

    /** 中止该任务(python 侧 abort2: 记 end=stopped, drain 收尾按"已停止"落账)。 */
    public static String cancel(String taskId) {
        String cid = (taskId == null || taskId.isEmpty()) ? lastTaskId : taskId;
        try {
            if (cid.isEmpty()) return "ERR:no task";
            if (!Py.INSTANCE.getReady()) return "ERR:python not ready";
            String r = (mode == MODE_SINGLE)
                    ? Py.INSTANCE.call("abort")
                    : Py.INSTANCE.call("abort2", cid);
            return (r == null || r.isEmpty()) ? "ok" : "ERR:" + r;
        } catch (Throwable e) {
            return "ERR:" + e;
        }
    }

    /**
     * python 侧 poll/poll2 的 final 是整段转写("**LLM Running (Turn 9) ...**" + 工具调用 JSON),
     * 直接推给 amoo 会变成一屏噪音。这里只留"人话": 丢掉代码围栏、工具行、纯 JSON 标点行。
     */
    private static String cleanFinal(String raw) {
        if (raw == null || raw.isEmpty()) return "";
        // 只取最后一个回合: 前面回合是走过场(点空/回退), 里面的自述对用户没意义
        int lastTurn = raw.lastIndexOf("**LLM Running");
        if (lastTurn > 0) raw = raw.substring(lastTurn);
        String[] lines = raw.split(String.valueOf((char) 10));
        StringBuilder keep = new StringBuilder();
        boolean inFence = false;
        for (String ln : lines) {
            String t = ln.trim();
            if (t.startsWith("```")) { inFence = !inFence; continue; }
            if (inFence) continue;
            if (t.startsWith("**LLM Running")) continue;
            if (t.startsWith("🛠") || t.startsWith("Tool:") || t.startsWith("[Action]")) continue;
            if (t.startsWith("[Error]") || t.startsWith("[OBS")) continue;
            if (t.equals("{") || t.equals("}") || t.equals("},")) continue;
            if (t.endsWith(":") && keep.length() == 0) continue;
            if (t.isEmpty() || t.length() < 12) continue;   // 碎词("入口：")不进报告
            keep.append(t).append((char) 10);
        }
        String out = keep.toString().trim();
        if (out.isEmpty()) return "";
        return clip(out, 900);
    }

    private static String clip(String s, int n) {
        return s.length() <= n ? s : s.substring(0, n);
    }

    private static String esc(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
