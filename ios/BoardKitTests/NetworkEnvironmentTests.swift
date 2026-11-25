import XCTest
@testable import BoardKitHarness

final class NetworkEnvironmentTests: XCTestCase {
    /// Shadowrocket in HTTP mode: the proxy is published for its tunnel interface, not globally.
    func testTunnelScopedHTTPProxyIsReported() {
        let settings: [String: Any] = [
            "HTTPEnable": 0,
            "__SCOPED__": [
                "en0": ["ExceptionsList": ["*.local"]],
                "utun4": ["HTTPEnable": 1, "HTTPProxy": "127.0.0.1", "HTTPPort": 1082, "HTTPSEnable": 1],
            ],
        ]
        let summary = NetworkEnvironment.summary(of: settings)
        XCTAssertEqual(summary["proxy"] as? String, "http://127.0.0.1:1082")
        XCTAssertEqual(summary["tunnels"] as? [String], ["utun4"])
        XCTAssertEqual(summary["vpn"] as? Bool, true)
    }

    /// TUN mode: traffic is tunnelled but no HTTP proxy exists, so there is nothing to fill in.
    func testTunnelWithoutProxyIsVPNOnly() {
        let settings: [String: Any] = ["__SCOPED__": ["utun6": ["ExceptionsList": ["localhost"]], "en0": [:]]]
        let summary = NetworkEnvironment.summary(of: settings)
        XCTAssertNil(summary["proxy"])
        XCTAssertEqual(summary["vpn"] as? Bool, true)
        XCTAssertEqual(summary["tunnels"] as? [String], ["utun6"])
    }

    func testPlainWiFiHasNeitherAndManualWiFiProxyIsGlobal() {
        XCTAssertEqual(NetworkEnvironment.summary(of: ["__SCOPED__": ["en0": [:]]])["vpn"] as? Bool, false)
        let manual: [String: Any] = ["HTTPEnable": 1, "HTTPProxy": "192.168.10.199", "HTTPPort": 8899]
        XCTAssertEqual(NetworkEnvironment.summary(of: manual)["proxy"] as? String, "http://192.168.10.199:8899")
        XCTAssertNil(NetworkEnvironment.summary(of: ["HTTPEnable": 1, "HTTPProxy": "", "HTTPPort": 0])["proxy"],
                     "an enabled flag without an address is not a proxy")
    }
}
