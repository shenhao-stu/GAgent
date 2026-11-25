import CFNetwork
import Foundation

/// What the system says about proxies and tunnels, for the "detect local proxy" setting.
///
/// On iOS a proxy app is a VPN (NetworkExtension) tunnel: it already carries this app's traffic, and only
/// some apps also publish an HTTP proxy (Shadowrocket in HTTP mode writes 127.0.0.1:1082 for its utun
/// interface). Probing loopback ports therefore cannot tell "no proxy" from "tunnelled without a proxy";
/// the system proxy dictionary can.
public enum NetworkEnvironment {
    static let tunnelPrefixes = ["utun", "tun", "tap", "ppp", "ipsec"]

    /// `proxy` is the first enabled HTTP proxy (global, then per tunnel interface); `tunnels` lists tunnel
    /// interfaces that carry their own network settings, which is how an active VPN shows up.
    public static func summary(of settings: [String: Any]) -> [String: Any] {
        let scoped = settings["__SCOPED__"] as? [String: Any] ?? [:]
        let tunnels = scoped.keys.filter { name in tunnelPrefixes.contains { name.hasPrefix($0) } }.sorted()
        var out: [String: Any] = ["tunnels": tunnels, "vpn": !tunnels.isEmpty]
        let candidates = [settings] + tunnels.compactMap { scoped[$0] as? [String: Any] }
        for dict in candidates {
            guard (dict["HTTPEnable"] as? NSNumber)?.intValue == 1,
                  let host = dict["HTTPProxy"] as? String, !host.isEmpty,
                  let port = (dict["HTTPPort"] as? NSNumber)?.intValue, port > 0 else { continue }
            out["proxy"] = "http://\(host):\(port)"
            break
        }
        return out
    }

    public static func current() -> [String: Any] {
        guard let settings = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any] else {
            return ["tunnels": [], "vpn": false]
        }
        return summary(of: settings)
    }

    public static func currentJSON() -> String {
        let data = try? JSONSerialization.data(withJSONObject: current())
        return data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
    }
}
