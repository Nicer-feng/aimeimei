// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MeimeiCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "MeimeiCore", targets: ["MeimeiCore"])],
    targets: [
        .target(name: "MeimeiCore"),
        .testTarget(name: "MeimeiCoreTests", dependencies: ["MeimeiCore"])
    ]
)
