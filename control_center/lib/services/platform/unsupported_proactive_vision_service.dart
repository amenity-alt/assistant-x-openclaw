import '../base/proactive_vision_service_base.dart';
import '../installed_application_catalog.dart';

class UnsupportedProactiveVisionService extends ProactiveVisionServiceBase {
  final _applicationCatalog = InstalledApplicationCatalog();

  @override
  bool get isSupported => false;

  @override
  Future<ProactiveVisionStatus> checkStatus({
    required String ollamaUrl,
    required String model,
  }) async {
    return ProactiveVisionStatus(
      supported: false,
      ollamaReachable: false,
      modelAvailable: false,
      screenPermissionGranted: false,
      model: model,
      message: '当前平台暂未接入屏幕视觉探测。',
    );
  }

  @override
  Future<bool> requestScreenPermission() async => false;

  @override
  Future<ForegroundAppInfo> getForegroundAppInfo() async {
    return const ForegroundAppInfo(name: '', bundleIdentifier: '');
  }

  @override
  Future<List<InstalledApplicationInfo>> listInstalledApplications() async {
    return _applicationCatalog.listApplications();
  }

  @override
  Future<ScreenSnapshot> captureScreenSnapshot() async {
    throw UnsupportedError('当前平台暂未接入屏幕视觉探测。');
  }

  @override
  Future<ScreenAnalysisResult> analyzeCurrentScreen({
    required String ollamaUrl,
    required String model,
    required String prompt,
  }) async {
    throw UnsupportedError('当前平台暂未接入屏幕视觉探测。');
  }

  @override
  Future<ScreenAnalysisResult> analyzeSnapshot({
    required String ollamaUrl,
    required String model,
    required String prompt,
    required List<int> pngBytes,
  }) async {
    throw UnsupportedError('当前平台暂未接入屏幕视觉探测。');
  }
}
