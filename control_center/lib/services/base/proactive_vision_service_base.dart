class ProactiveVisionStatus {
  final bool supported;
  final bool ollamaReachable;
  final bool modelAvailable;
  final bool screenPermissionGranted;
  final String model;
  final String message;

  const ProactiveVisionStatus({
    required this.supported,
    required this.ollamaReachable,
    required this.modelAvailable,
    required this.screenPermissionGranted,
    required this.model,
    required this.message,
  });

  bool get ready =>
      supported && ollamaReachable && modelAvailable && screenPermissionGranted;
}

class ScreenAnalysisResult {
  final String response;
  final Duration elapsed;

  const ScreenAnalysisResult({required this.response, required this.elapsed});
}

class ScreenSnapshot {
  final List<int> pngBytes;
  final int signature;

  const ScreenSnapshot({required this.pngBytes, required this.signature});
}

class ForegroundAppInfo {
  final String name;
  final String bundleIdentifier;

  const ForegroundAppInfo({required this.name, required this.bundleIdentifier});
}

class InstalledApplicationInfo {
  final String name;
  final String bundleIdentifier;
  final List<String> aliases;

  const InstalledApplicationInfo({
    required this.name,
    required this.bundleIdentifier,
    this.aliases = const [],
  });
}

abstract class ProactiveVisionServiceBase {
  bool get isSupported;

  Future<ProactiveVisionStatus> checkStatus({
    required String ollamaUrl,
    required String model,
  });

  Future<bool> requestScreenPermission();

  Future<ForegroundAppInfo> getForegroundAppInfo();

  Future<List<InstalledApplicationInfo>> listInstalledApplications();

  Future<ScreenSnapshot> captureScreenSnapshot();

  Future<ScreenAnalysisResult> analyzeCurrentScreen({
    required String ollamaUrl,
    required String model,
    required String prompt,
  });

  Future<ScreenAnalysisResult> analyzeSnapshot({
    required String ollamaUrl,
    required String model,
    required String prompt,
    required List<int> pngBytes,
  });
}
