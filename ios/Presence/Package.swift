// swift-tools-version:5.9
// Host-side tests for the pure half of Presence:  ios/Presence/test.sh  (keeps build output under build/)
// The app and the widget compile Core/ directly; this package is not a dependency of either.
import PackageDescription

let package = Package(
    name: "PresenceCore",
    platforms: [.macOS(.v13)],
    targets: [
        .target(name: "PresenceCore", path: "Core"),
        .testTarget(name: "PresenceCoreTests", dependencies: ["PresenceCore"], path: "Tests/PresenceCoreTests"),
    ]
)
