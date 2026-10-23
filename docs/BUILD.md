# Build Android / 构建 Android

[Documentation](README.md) · [Development](DEVELOPMENT.md) · [Testing](TESTING.md)

The [Android workflow](../.github/workflows/android.yml) is the executable build
recipe. This repository currently uses a system Gradle installation; it does not
include a Gradle wrapper. Run commands below from the repository root.

[CI](../.github/workflows/android.yml)是可执行的构建依据。仓库当前没有 Gradle wrapper，
请使用已安装的 Gradle，在仓库根目录执行以下命令。

## Toolchain / 工具链

| Component / 组件 | Declared configuration / 当前配置 | Source / 来源 |
| --- | --- | --- |
| Build host in CI | Ubuntu 24.04 | Android workflow |
| JDK | Liberica 17.0.21 in CI; Java 17 target | Workflow, app/build.gradle |
| Gradle / Android Gradle Plugin | 8.2 / 8.1.4 | Workflow, build.gradle |
| Kotlin / Chaquopy | 1.9.22 / 17.1.0 | build.gradle |
| Android SDK / build tools | 34 / 34.0.0 | Workflow, app/build.gradle |
| Android NDK | 25.1.8937393 | Workflow, app/build.gradle |
| Build Python / embedded Python | 3.10 / Chaquopy 3.10 line | Workflow, app/build.gradle |
| Node.js for JavaScript checks | Runner-provided in CI; version not pinned by the workflow | Android workflow |
| Go | 1.27.3 | Workflow, tsbridge/go.mod |
| gomobile / mesh dependencies | Pinned module revisions | tsbridge/go.mod, tsbridge/go.sum |
| Target device | arm64-v8a, minSdk 24, targetSdk 34 | app/build.gradle |

These are compatibility pins, not a statement that every dependency is supported
or free of known vulnerabilities. Read [Dependency security](DEPENDENCY_SECURITY.md),
especially the Python/native-wheel migration requirements. APK inventory checks
the packaged runtime; host Python and OpenSSL versions do not prove APK versions.

版本固定用于可复现构建配置，不代表全部依赖已完成安全升级。Go/TLS 代码会编入 AAR，
只升级开发电脑而不重建 AAR/APK，不会更新已安装应用。

## Prepare the environment / 准备环境

Install the listed toolchain through your normal development environment.
Set `ANDROID_HOME` to the Android SDK directory, then install the SDK components:

~~~sh
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" "ndk;25.1.8937393"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/25.1.8937393"
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
~~~

Use a project environment; do not install test dependencies into a shared system
Python. For UI tests, either set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to a compatible
installed browser or install Playwright Chromium:

~~~sh
python -m playwright install chromium
~~~

If Chaquopy cannot locate Python 3.10, set `CHAQUOPY_PYTHON` to its executable, or
pass `-Pchaquopy.python=/absolute/path/to/python3.10` to Gradle.
A full build downloads public Android, Maven, Go and Python dependencies.
No model API key, hosted-service account or source-encryption secret is needed.

使用独立 Python 环境。构建需要下载公开依赖，不需要模型或商业服务密钥；
模型请求属于设备验收，不属于编译步骤。

## Build / 构建

~~~sh
python tools/audit_source.py
bash tools/build_tsbridge.sh
python tools/build_pure_wheels.py
gradle :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease --no-daemon --stacktrace
~~~

Order matters: the mesh script produces `app/libs/tsbridge.aar` and Go notices;
the wheel script produces the portable HTTP dependencies under
`build/python-wheels/`. Gradle consumes both. Android wheels are not the desktop
wheels installed for tests.

| Output / 产物 | Meaning / 含义 |
| --- | --- |
| app/build/outputs/apk/debug/app-debug.apk | Debug package; separate application ID |
| app/build/outputs/apk/release/app-release-unsigned.apk | Release without configured signing; not directly installable |
| app/build/outputs/apk/release/app-release.apk | Release when signing is configured |

For full local regression commands, follow [Testing](TESTING.md). A successful
assembly alone is not the complete CI gate.

## Signing and installation / 签名与安装

For local release signing, supply `GAGENT_KEYSTORE_PATH` through a private path
and `GAGENT_STORE_PASSWORD` through your secret manager. The PKCS12 alias is
`gagent`, with the same store/key password expected by the current build script.
Never put these values in source, shell history, a PR or an issue.

Without signing variables, debug uses the local debug identity and release is
unsigned. With them, both variants use the configured identity, but debug retains
its `.debug` application-ID suffix. Different debug keys from different machines
can also cause update incompatibility.

本地调试签名与维护者签名可能不同。保留原安装和数据，先核对包名及证书，再决定迁移；
不要把“卸载重装”当作签名不匹配的默认解决办法。

For a debug installation on a selected test device:

~~~sh
adb devices -l
adb -s DEVICE_SERIAL install -r app/build/outputs/apk/debug/app-debug.apk
~~~

Replace `DEVICE_SERIAL` deliberately. Do not use data-clearing commands during
an upgrade test. ADB is a development connection, not a normal model transport.

## CI artifacts / CI 制品

Both `verify` and `build` jobs must succeed for the **same commit**. They run as
separate jobs; a green build does not imply the verification job passed.

The artifact `GAgent-android-<commit>` contains APKs, inventories, SHA256SUMS,
SOURCE_COMMIT and signature information for signed packages. Retention is
currently 14 days, so a CI artifact is not a permanent release archive.

Maintainer signing uses Actions secrets `GAGENT_RELEASE_KEYSTORE` (base64 PKCS12)
and `GAGENT_STORE_PASSWORD`. Fork PRs do not need these secrets. The workflow
removes its temporary keystore and does not publish a GitHub release or change
repository visibility. Follow [Releasing](RELEASING.md) for those separate steps.
