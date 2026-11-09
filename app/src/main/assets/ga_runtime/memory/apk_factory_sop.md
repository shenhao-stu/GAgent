# APK 工厂 SOP (apk_factory) — GA 造 App(写工程 → 服务端离线编译签名 → 装机)

> 触发见 `modes_index`。GA 写**完整 Android 工程**交自建服务(example.invalid)编译, 手机端不装工具链。服务**离线构建**。
> 第一纪律: 照可编译边界生成, 一次成功。第二纪律: UI 照 `memory/apk_design_guide.md` 做(维护者在 PC 更新蒸馏源: `npx skills add https://github.com/wshobson/agents --skill mobile-android-design` / `--skill mobile-ios-design`; 设备端无 npx 勿执行)。

## 可编译边界(出界=必编译失败)
| 项 | 唯一可用 |
|---|---|
| compileSdk / targetSdk | 34 或 35(scaffold 默认 35 不用改) |
| minSdk / JDK・jvmTarget | 24 / 17 |
| AGP / Gradle / Kotlin | `8.6.0` / `8.9` / `1.9.25` — scaffold 已钉, **禁改这些版本行** |

依赖只准用以下精确坐标(清单外 `--offline` 拉不到必失败; **纯系统控件零依赖最稳**; scaffold 已 resolutionStrategy.force 钉死, 子集也能离线编过):
```
androidx.core:core-ktx:1.13.1                        androidx.appcompat:appcompat:1.7.0
com.google.android.material:material:1.12.0          androidx.constraintlayout:constraintlayout:2.1.4
androidx.recyclerview:recyclerview:1.3.2             androidx.activity:activity-ktx:1.9.2
androidx.lifecycle:lifecycle-runtime-ktx:2.8.6       androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.6
```
> 参考 `apk_factory/examples/calendar`: 纯 Kotlin 零依赖也能「简洁好看」。

## 三步
1. **起工程+写真实代码**(code_run(python) 进程内, 无 shell python): `import scaffold; proj = scaffold.scaffold("app.ga.calendar", "我的日历", "temp/cal_proj")` → 在 proj 里写 Kotlin/res/Manifest(权限按需写, 装机时系统安装器列给用户把关)。包名**必须 `app.ga.` 开头**; 同一 App 重出=同包名+versionCode+1; 不动 build.gradle 版本行, 依赖只在清单内增删; UI 动手前读 apk_design_guide.md。
2. **编译取包(一次调用)**: `r = F.build_and_fetch(project_dir, label="日历", on_update=...)`(import apk_factory as F; 包名/versionCode 自动从工程读) → `{job_id, state:'SUCCEEDED', apk_path(已下到设备), sha256, size, quota}`。失败抛异常, **异常文本含【关键错误】(kotlin `e:`/AAPT 真实编译错误行)——照它改源码, 别猜、别换语言**。失败 reason:
   - `USER_COMPILE_FAIL` → 读【关键错误】改源码重编(先确认没用边界外 SDK/依赖)。
   - `daily_quota`=今日额度尽; `already_active`=已有在途构建(弱网重发同工程=幂等命中不双扣)。
   - `package_taken` → 换包名(仍 app.ga. 开头); `STATIC_REJECT`=工程结构/体检不过。
   - **下载失败(异常带 job_id) → 编译已成功、额度已计, 勿重新 build**: `F.status(job_id, base)` 取新链接再 `F.download`(产物保 24h)。
3. **装机(系统安装器, 用户确认)**: `droid.install_apk(r["apk_path"])`(PackageInstaller; 首次需开「安装未知应用」)。装完 `droid.ping()` 确认; 魅族等首次被拦重试即可。

## 身份与额度
- 构建需登录(gauth token), guest 额度 0。token: env `GA_APK_TOKEN` → `apk_factory.json` → gauth 会话。
- **一次服务端编译=一次额度, 每日 10 次**(设置页「APK 工厂」可见); 开发者账号不限次。编译失败(自己代码问题)也计次, 服务器故障自动返还。改完重编=再一次额度——先本地想清楚再提交。
- `F.quota()` 查 {used_today, remaining_today, unlimited}; build_and_fetch 开头自动上报一次, **把剩余次数告诉用户**。

## 注意
- 工厂自有签名非商店签名, 如实告知来源; 凭证/私钥不进源码/日志; 临时工程写 agent temp, 用后清理。
