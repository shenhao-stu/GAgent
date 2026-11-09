# Optional official modules / 可选官方组件

[Configuration fields and profile import / 配置字段与导入](CONFIGURATION.md#modules)

P2P and GAnet can be offered as official services while
the Android framework remains independently usable. All integrations start
disabled. A connection profile supplies addresses and a user's credentials;
installing the framework does not enroll the user or call an official service.

P2P 和 GAnet 可作为独立官方服务。开源框架不依赖购买、登录或
激活这些组件。用户在设置中主动配置后接入，也可以使用兼容的自建服务。

| Module / 组件 | Client entry / 客户端入口 | Kept on server / 服务端保留 |
| --- | --- | --- |
| P2P / PC Link | Integrations: WSS signaling URL and a scoped relay credential; pair a peer | Relay operations, credential issuer, abuse control |
| GAnet | Integrations: HTTPS API, user token, issued owner ID | Identity issuer, mesh control plane, administrative keys |
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
validation and public client protocols. Integration profiles are configuration
only, never downloaded executable code. They should be delivered over an
authenticated channel and reviewed before saving.

PC Link has no default shared signing key in source or release APKs; see
[Configuration](CONFIGURATION.md#pc-link-relay-profile--中继配置). The endpoint
and credential come only from the user's Optional modules settings, optionally filled
by an explicit, confirmed public-relay preset whose access value is already public in
the GenericAgent desktop client. Pairing remains
explicit; a changed endpoint cannot inherit a saved room, clearing the settings
stops relay use, and unpairing stops reconnection. Per-device, revocable
credentials require a relay-side issuer, which this repository does not provide.

Automatic official login, token renewal and a new server-side capability issuer
are **not included** in this Android extraction. Existing services must support the
documented client protocol before activation. The framework does not claim that a
legacy server token is short-lived merely because the settings UI hides it.

本版本实现显式接入配置、令牌遮蔽、地址校验和现有客户端协议。自动登录、续签和新的服务端权限签发器尚未包含，不能把界面遮蔽当作
服务端权限隔离，也不能承诺客户端代码“不可逆向”。

Voice input is local and needs no service profile; see [offline voice](OFFLINE_VOICE.md).
语音输入使用离线模型，不属于可选服务配置。
