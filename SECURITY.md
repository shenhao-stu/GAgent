# Security / 安全

[Dependency findings](docs/DEPENDENCY_SECURITY.md) · [Architecture](docs/ARCHITECTURE.md) · [Release checks](docs/RELEASING.md)

## Report a vulnerability / 报告漏洞

Do not include credentials, personal data, production traces or exploit details
in a normal issue or PR. Include the affected commit/version, boundary, expected
versus observed behavior and a minimal reproduction using synthetic data in a
private report.

Use GitHub's [private vulnerability report](https://github.com/shenhao-stu/GAgent/security/advisories/new)
from **Security → Report a vulnerability**. If that control is unavailable, request
a private maintainer contact without disclosing the vulnerability in a public issue.
See [GitHub's reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

通过上方 GitHub 私密漏洞入口提交；若入口不可用，只请求私下联系方式。
不要在普通 Issue 中披露漏洞细节、账号、日志或密钥。

Maintainers should acknowledge the report, assess reachability and impact, agree
on a disclosure path and record which release actually contains a fix.
The current candidate has no separately maintained LTS branch; report the exact
revision, and verify whether a fix is present on main and in a distributed APK.

## Threat model / 信任边界

GAgent executes generated Python and operates Android with the user's granted
capabilities. It is not a sandbox for hostile models, prompts, websites or plugins.
App-private storage limits ordinary peer-app access; it does not protect against
a rooted device, a compromised runtime or code executing with the app's privileges.

客户端执行生成代码并操作真实设备，不是面向恶意输入的隔离沙箱。
用户或攻击者控制设备后，可以提取客户端代码和交付给客户端的凭据。

| Data / 数据 | Stored or sent where / 存储或发送位置 |
| --- | --- |
| Provider keys | App-private configuration; sent to the selected provider for authentication / 本地保存，调用时向所选服务认证 |
| Tasks, screenshots and tool output | Local session/runtime data; relevant content may be sent to the configured model / 本地会话，必要内容可能发给模型 |
| Optional-service tokens | App-private configuration; sent when using the configured integration / 本地配置，使用组件时发送 |
| Local bus capability | Per-process random capability for the exact loopback origin / 每进程随机能力，只发往规定回环来源 |
| Diagnostic information | Local diagnostics; users must inspect and redact before sharing / 本地诊断，分享前检查脱敏 |

Hosted telemetry and prompt collection are disabled in this distribution. This
does not mean that model use or explicitly enabled services are offline.
A masked or write-only settings response is not protection from arbitrary code
running inside the app.

## Controls and their limits / 防护及其局限

- Local device requests use `bus_auth.py` / `LocalBusAuth.kt`; do not expose the
  device bus or its capability to remote peers or arbitrary WebView content.
- Keep external content separate from the privileged UI bridge. Treat model and
  page output as untrusted data, not permission to change policy.
- Preserve certificate verification. Credentials must not follow an untrusted
  redirect, fallback origin or changed integration endpoint.
- Keep optional services opt-in. Unconfigured clients must fail explicitly
  without using a shared fallback credential.
- Keep screenshots and test traces private unless minimized and redacted.
  A model's final response does not prove that no side effect occurred.
- Do not automatically retry a mutation with an unknown result; first reconcile
  the state to avoid duplicate messages, purchases or other actions.

## Official modules / 官方组件

Vendor keys, root signers, billing authority and privileged implementations belong
on servers. The client may receive user-scoped credentials whose expiry, quota
and revocation are enforced by that server. Source encryption, obfuscation and
encrypted assets cannot make a client-held secret unextractable.

Long-lived or shared credentials must not be shipped in an APK, model file,
JavaScript bundle or downloadable plugin. The framework does not implement a new
issuer or automatic renewal for every legacy service; see
[Official modules](docs/OFFICIAL_MODULES.md).

## Security evidence / 安全证据

`tools/audit_source.py` scans source, nested archives and APK contents; CI also
runs a redacted full-history secret scan and packaged-runtime inventory checks.
The source audit permits exact public navigation links in reviewed documentation
files. This exception does not permit API paths, URL credentials or queries, does
not skip secret rules, and does not apply to APKs or nested archives.
These are bounded detection tools, not proof that arbitrary text contains no
private data or that every dependency is safe.

[Dependency security](docs/DEPENDENCY_SECURITY.md) records unresolved native
version findings and scoped mitigations. Disabling an affected path does not
upgrade the library. A desktop test environment cannot certify Android binaries.
Never label a pending check, untested device or author's self-review as a completed
independent audit.

扫描、构建、兼容性、可达性分析与独立安全审计是不同证据。公开前按实际制品重新核对，
不要把“本次未调用”写成“依赖已修复”。
