import Cocoa
import FlutterMacOS
import AVFoundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

@main
class AppDelegate: FlutterAppDelegate {
  override func applicationDidFinishLaunching(_ aNotification: Notification) {
    NSApp.setActivationPolicy(.accessory)

    let controller = mainFlutterWindow?.contentViewController as? FlutterViewController

    if let controller = controller {
      let permissionChannel = FlutterMethodChannel(name: "com.assistant/permission",
                                                    binaryMessenger: controller.engine.binaryMessenger)

      permissionChannel.setMethodCallHandler { [weak self] (call: FlutterMethodCall, result: @escaping FlutterResult) in
        if call.method == "requestMicrophonePermission" {
          self?.requestMicrophonePermission(result: result)
        } else if call.method == "checkMicrophonePermission" {
          self?.checkMicrophonePermission(result: result)
        } else {
          result(FlutterMethodNotImplemented)
        }
      }

      let proactiveVisionChannel = FlutterMethodChannel(name: "com.assistant/proactive_vision",
                                                        binaryMessenger: controller.engine.binaryMessenger)

      proactiveVisionChannel.setMethodCallHandler { [weak self] (call: FlutterMethodCall, result: @escaping FlutterResult) in
        switch call.method {
        case "checkScreenCapturePermission":
          self?.checkScreenCapturePermission(result: result)
        case "requestScreenCapturePermission":
          self?.requestScreenCapturePermission(result: result)
        case "captureMainDisplayPng":
          self?.captureMainDisplayPng(result: result)
        case "getForegroundAppInfo":
          self?.getForegroundAppInfo(result: result)
        case "listInstalledApplications":
          self?.listInstalledApplications(result: result)
        default:
          result(FlutterMethodNotImplemented)
        }
      }
    }

    super.applicationDidFinishLaunching(aNotification)
  }

  private func requestMicrophonePermission(result: @escaping FlutterResult) {
    AVCaptureDevice.requestAccess(for: .audio) { granted in
      DispatchQueue.main.async {
        result(granted)
      }
    }
  }

  private func checkMicrophonePermission(result: @escaping FlutterResult) {
    let status = AVCaptureDevice.authorizationStatus(for: .audio)
    switch status {
    case .authorized:
      result("granted")
    case .denied:
      result("denied")
    case .notDetermined:
      result("undetermined")
    case .restricted:
      result("denied")
    @unknown default:
      result("unknown")
    }
  }

  private func checkScreenCapturePermission(result: @escaping FlutterResult) {
    if #available(macOS 10.15, *) {
      result(CGPreflightScreenCaptureAccess())
    } else {
      result(true)
    }
  }

  private func requestScreenCapturePermission(result: @escaping FlutterResult) {
    if #available(macOS 10.15, *) {
      let granted = CGRequestScreenCaptureAccess()
      result(granted)
    } else {
      result(true)
    }
  }

  private func captureMainDisplayPng(result: @escaping FlutterResult) {
    guard let image = captureAllDisplaysImage() else {
      result(FlutterError(code: "capture_failed",
                          message: "无法截取显示器画面，请确认屏幕录制权限已授予 Control Center。",
                          details: nil))
      return
    }

    let data = NSMutableData()
    let pngType: CFString
    if #available(macOS 11.0, *) {
      pngType = UTType.png.identifier as CFString
    } else {
      pngType = "public.png" as CFString
    }

    guard let destination = CGImageDestinationCreateWithData(data, pngType, 1, nil) else {
      result(FlutterError(code: "png_encode_failed",
                          message: "无法创建 PNG 编码器。",
                          details: nil))
      return
    }

    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
      result(FlutterError(code: "png_encode_failed",
                          message: "无法编码屏幕截图。",
                          details: nil))
      return
    }

    result(FlutterStandardTypedData(bytes: data as Data))
  }

  private func captureAllDisplaysImage() -> CGImage? {
    var displayCount: UInt32 = 0
    var err = CGGetActiveDisplayList(0, nil, &displayCount)
    if err != .success || displayCount == 0 {
      return CGDisplayCreateImage(CGMainDisplayID())
    }

    var displays = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
    err = CGGetActiveDisplayList(displayCount, &displays, &displayCount)
    if err != .success || displayCount == 0 {
      return CGDisplayCreateImage(CGMainDisplayID())
    }
    displays = Array(displays.prefix(Int(displayCount)))

    let entries: [(id: CGDirectDisplayID, bounds: CGRect, image: CGImage)] = displays.compactMap { id in
      guard let image = CGDisplayCreateImage(id) else { return nil }
      return (id, CGDisplayBounds(id), image)
    }
    if entries.isEmpty {
      return CGDisplayCreateImage(CGMainDisplayID())
    }

    let unionBounds = entries
      .map { $0.bounds }
      .reduce(CGRect.null) { $0.union($1) }
      .integral
    guard unionBounds.width > 0, unionBounds.height > 0 else {
      return CGDisplayCreateImage(CGMainDisplayID())
    }

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(data: nil,
                                  width: Int(unionBounds.width),
                                  height: Int(unionBounds.height),
                                  bitsPerComponent: 8,
                                  bytesPerRow: 0,
                                  space: colorSpace,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
      return CGDisplayCreateImage(CGMainDisplayID())
    }

    context.setFillColor(NSColor.black.cgColor)
    context.fill(CGRect(origin: .zero, size: unionBounds.size))

    for entry in entries {
      let drawRect = CGRect(
        x: entry.bounds.minX - unionBounds.minX,
        y: unionBounds.maxY - entry.bounds.maxY,
        width: entry.bounds.width,
        height: entry.bounds.height
      )
      context.draw(entry.image, in: drawRect)
    }

    return context.makeImage()
  }

  private func getForegroundAppInfo(result: @escaping FlutterResult) {
    guard let app = NSWorkspace.shared.frontmostApplication else {
      result(["name": "", "bundleIdentifier": ""])
      return
    }

    result([
      "name": app.localizedName ?? "",
      "bundleIdentifier": app.bundleIdentifier ?? ""
    ])
  }

  private func listInstalledApplications(result: @escaping FlutterResult) {
    DispatchQueue.global(qos: .userInitiated).async {
      let fileManager = FileManager.default
      let urls = [
        URL(fileURLWithPath: "/Applications"),
        URL(fileURLWithPath: "/Applications/Utilities"),
        URL(fileURLWithPath: "/System/Applications"),
        URL(fileURLWithPath: "/System/Applications/Utilities"),
        URL(fileURLWithPath: "/System/Library/CoreServices"),
        fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
      ]
      var seen = Set<String>()
      var apps: [[String: Any]] = []

      for url in urls {
        guard let enumerator = fileManager.enumerator(
          at: url,
          includingPropertiesForKeys: [.isDirectoryKey],
          options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else {
          continue
        }

        for case let appURL as URL in enumerator {
          guard appURL.pathExtension.lowercased() == "app" else {
            continue
          }
          let bundle = Bundle(url: appURL)
          let bundleIdentifier = bundle?.bundleIdentifier ?? ""
          let displayName =
            bundle?.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ??
            bundle?.object(forInfoDictionaryKey: "CFBundleName") as? String ??
            appURL.deletingPathExtension().lastPathComponent
          let aliases = self.localizedApplicationNames(appURL: appURL, primaryName: displayName)
          let key = bundleIdentifier.isEmpty ? appURL.path : bundleIdentifier
          guard !seen.contains(key) else {
            continue
          }
          seen.insert(key)
          apps.append([
            "name": displayName,
            "bundleIdentifier": bundleIdentifier,
            "aliases": aliases
          ])
        }
      }

      apps.sort {
        let lhs = $0["name"] as? String ?? ""
        let rhs = $1["name"] as? String ?? ""
        return lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
      }

      DispatchQueue.main.async {
        result(apps)
      }
    }
  }

  private func localizedApplicationNames(appURL: URL, primaryName: String) -> [String] {
    let fileManager = FileManager.default
    let resourcesURL = appURL
      .appendingPathComponent("Contents")
      .appendingPathComponent("Resources")
    guard let resourceEntries = try? fileManager.contentsOfDirectory(
      at: resourcesURL,
      includingPropertiesForKeys: [.isDirectoryKey],
      options: [.skipsHiddenFiles]
    ) else {
      return []
    }

    var names = Set<String>()
    for entry in resourceEntries where entry.pathExtension == "lproj" {
      let stringsURL = entry.appendingPathComponent("InfoPlist.strings")
      guard let dictionary = NSDictionary(contentsOf: stringsURL) as? [String: Any] else {
        continue
      }
      for key in ["CFBundleDisplayName", "CFBundleName"] {
        guard let value = dictionary[key] as? String else {
          continue
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty && trimmed != primaryName {
          names.insert(trimmed)
        }
      }
    }

    return names.sorted {
      $0.localizedCaseInsensitiveCompare($1) == .orderedAscending
    }
  }

  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    return false
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }
}
