# Optional official modules / 可选官方组件

[Configuration fields and profile import / 配置字段与导入](CONFIGURATION.md#modules)

P2P, GAnet, GA Plan and streaming voice can be offered as official services while
the Android framework remains independently usable. All integrations start
disabled. A connection profile supplies addresses and a user's credentials;
installing the framework does not enroll the user or call an official service.

P2P、GAnet、GA Plan 和官方语音可作为独立官方服务。开源框架不依赖购买、登录或
激活这些组件。用户在设置中主动配置后接入，也可以使用兼容的自建服务。

| Module / 组件 | Client entry / 客户端入口 | Kept on server / 服务端保留 |
| --- | --- | --- |
| P2P / PC Link | Integrations: WSS signaling URL and a scoped relay credential; pair a peer | Relay operations, credential issuer, abuse control |
| GAnet | Integrations: HTTPS API, user token, issued owner ID | Identity issuer, mesh control plane, administrative keys |
| GA Plan | Providers & Models: OpenAI-compatible URL, issued user key, model | Subscription, pricing, accounting, upstream keys and root signers |
| Voice / 语音 | Integrations: WSS endpoint, user token, model | Vendor speech keys and token issuance |
| APK builder | Integrations: HTTPS endpoint and user token | Build workers, quotas, signing authority |

## Credential design

Long-lived vendor keys and shared HMAC secrets must never be distributed in an
APK, JavaScript, downloadable plugin, obfuscated native library or encrypted asset
whose decryption key ships with the client. The user controls the client and can
inspect all code and credentials delivered to it.

Keep sensitive implementations behind HTTPS/WSS. An official issuer should grant
one user and one audience narrowly scoped access, with a short expiry, quota and
revocation. For interactive login use an external browser plus PKCE or a device
authorization flow, with no confidential client secret in the app. The server must
enforce authorization on every request and isolate administrative credentials.
Return only the minimum result; do not return upstream credentials to the client.

长期供应商密钥、共享 HMAC 秘密及签发根密钥只保留在服务端。客户端只获取限定用户、
用途、有效期、额度且可撤销的凭据。授权由服务端执行，不能依赖 APK 完整性、代码混淆
或隐藏字段。设备失陷时用户令牌仍可能被取走，因此要支持撤销和限额。

## What is implemented

This release provides explicit configuration, masked token reads, endpoint
validation and public client protocols. GA Plan uses the normal provider interface;
its user key comes from the deployed portal. Integration profiles are configuration
only, never downloaded executable code. They should be delivered over an
authenticated channel and reviewed before saving.

PC Link source has no default shared signing key. A trusted build may inject a
relay bootstrap as described in [Configuration](CONFIGURATION.md#pc-link-build-bootstrap--构建默认配置).
Such client material is extractable from the APK and is not an account or admin
secret. Pairing remains explicit. User overrides replace both endpoint and token;
a changed endpoint cannot inherit either the bootstrap token or a saved room.
Clearing the override restores the build default; unpairing stops reconnection.

Automatic official login, token renewal and a new server-side capability issuer
are **not included** in this Android extraction. Existing services must support the
documented client protocol before activation. The framework does not claim that a
legacy server token is short-lived merely because the settings UI hides it.

本版本实现显式接入配置、令牌遮蔽、地址校验和现有客户端协议；GA Plan 走普通模型
服务商接口。自动登录、续签和新的服务端权限签发器尚未包含，不能把界面遮蔽当作
服务端权限隔离，也不能承诺客户端代码“不可逆向”。
