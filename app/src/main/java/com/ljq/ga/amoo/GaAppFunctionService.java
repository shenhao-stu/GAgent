package com.ljq.ga.amoo;

import android.annotation.TargetApi;
import android.app.appfunctions.AppFunctionException;
import android.app.appfunctions.AppFunctionService;
import android.app.appfunctions.ExecuteAppFunctionRequest;
import android.app.appfunctions.ExecuteAppFunctionResponse;
import android.app.appsearch.GenericDocument;
import android.content.pm.SigningInfo;
import android.os.CancellationSignal;
import android.os.OutcomeReceiver;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 把 GA 暴露成 amoo 的 AppFunction(元数据见 assets/amoo/app_functions*.xml)。
 *
 * 为什么是 Java 而不是 Kotlin: android.app.appfunctions.* 只在 API 36 存在,
 * 这里逐字照抄已验证可用的探针实现(Amoo-Phone-Tools 0.2.0), 避开 Kotlin 对平台
 * 平台类型/泛型 Builder 的空安全与型变约束。
 *
 * 超时契约: 第三方 AppFunctions 单次 30s(见 amoo 侧 AbilityAgentBusNode.timeoutMs=30000),
 * 而一次微信任务要几分钟 => startTask 只负责拉起前台并秒回 taskId, 进度用 taskStatus 轮询。
 */
@TargetApi(36)
public final class GaAppFunctionService extends AppFunctionService {
    private static final String TAG = "GaAppFunction";
    private static final String PREFIX = "com.ljq.ga.amoo.GaAppFunctionService#";
    /** 只认 StepOS 的能力层与 shell: 这些包会把 toolName 解析成 (pkg, functionId) 后调用。 */
    private static final Set<String> CALLERS = new HashSet<>(Arrays.asList(
            "com.stepos.ability", "com.stepos.agentbus", "com.stepos.aiengine",
            "com.stepos.ailauncher", "com.stepos.stepclaw", "com.android.shell"));

    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    @Override
    public void onExecuteFunction(ExecuteAppFunctionRequest request, String callingPackage,
            SigningInfo signingInfo, CancellationSignal cancellation,
            OutcomeReceiver<ExecuteAppFunctionResponse, AppFunctionException> callback) {
        if (!CALLERS.contains(callingPackage)) {
            callback.onError(new AppFunctionException(AppFunctionException.ERROR_DENIED,
                    "GAgent: caller " + callingPackage + " not allowed"));
            return;
        }
        final String fn = request.getFunctionIdentifier();
        worker.execute(() -> {
            try {
                cancellation.throwIfCanceled();
                String result = run(fn, request.getParameters());
                cancellation.throwIfCanceled();
                Log.i(TAG, "function=" + fn + " caller=" + callingPackage + " ok=1");
                GenericDocument doc = new GenericDocument.Builder<>("", "", "")
                        .setPropertyString(ExecuteAppFunctionResponse.PROPERTY_RETURN_VALUE, result)
                        .build();
                callback.onResult(new ExecuteAppFunctionResponse(doc));
            } catch (IllegalArgumentException e) {
                callback.onError(new AppFunctionException(AppFunctionException.ERROR_INVALID_ARGUMENT,
                        msg(e, "参数不对")));
            } catch (android.os.OperationCanceledException e) {
                callback.onError(new AppFunctionException(AppFunctionException.ERROR_CANCELLED, "Cancelled"));
            } catch (Throwable e) {
                Log.w(TAG, "function=" + fn + " failed", e);
                callback.onError(new AppFunctionException(AppFunctionException.ERROR_APP_UNKNOWN_ERROR,
                        msg(e, "GAgent 执行失败")));
            }
        });
    }

    private String run(String fn, GenericDocument params) throws Exception {
        if ((PREFIX + "capabilities").equals(fn)) {
            // 给 amoo 的模型一段"这台手机上我能干什么"的说明: 它检索工具时命中这里, 才不会答"没有这类能力"。
            return new JSONObject().put("ok", true)
                    .put("agent", "GAgent")
                    .put("can", "自动化操作手机界面: 打开微信/小程序, 点按钮, 滑动, 输入, 截图看画面判断, 多步骤任务")
                    .put("examples", new JSONArray()
                            .put("去微信搜索三角洲行动小程序, 查看今日密码")
                            .put("打开微信给文件传输助手发消息")
                            .put("在微信小程序里逐页翻找并读出某个数据"))
                    .put("howto", "用 startTask(task) 派活, 它会立刻返回 taskId; 再用 taskStatus(taskId) 查进度, 完成后 final 里是结果")
                    .toString();
        }
        if ((PREFIX + "startTask").equals(fn)) {
            String task = str(params, "task");
            if (task == null || task.trim().isEmpty()) throw new IllegalArgumentException("task 不能为空");
            String cid = AmooBridge.newTaskId();
            AmooBridge.launch(this, cid, task.trim());
            return new JSONObject().put("ok", true).put("state", "accepted").put("taskId", cid)
                    .put("hint", "GAgent 已在手机上开始执行, 用 taskStatus 查进度; 执行时请让它留在前台")
                    .toString();
        }
        if ((PREFIX + "taskStatus").equals(fn)) {
            return AmooBridge.status(optStr(params, "taskId", ""));
        }
        if ((PREFIX + "cancelTask").equals(fn)) {
            String r = AmooBridge.cancel(optStr(params, "taskId", ""));
            return new JSONObject().put("ok", "ok".equals(r)).put("result", r).toString();
        }
        throw new IllegalArgumentException("unknown function: " + fn);
    }

    private static String str(GenericDocument doc, String name) {
        try {
            return doc.getPropertyString(name);
        } catch (Throwable e) {
            return null;
        }
    }

    private static String optStr(GenericDocument doc, String name, String dflt) {
        String v = str(doc, name);
        return (v == null || v.trim().isEmpty()) ? dflt : v.trim();
    }

    private static String msg(Throwable e, String fallback) {
        String m = e.getMessage();
        return (m == null || m.isEmpty()) ? fallback : m;
    }
}
