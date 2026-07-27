import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import '../base/proactive_vision_service_base.dart';
import '../installed_application_catalog.dart';

class MacOSProactiveVisionService extends ProactiveVisionServiceBase {
  static const _channel = MethodChannel('com.assistant/proactive_vision');
  final _applicationCatalog = InstalledApplicationCatalog();

  @override
  bool get isSupported => true;

  @override
  Future<ProactiveVisionStatus> checkStatus({
    required String ollamaUrl,
    required String model,
  }) async {
    final ollamaReachable = await _isOllamaReachable(ollamaUrl);
    final modelAvailable = ollamaReachable
        ? await _isModelAvailable(ollamaUrl, model)
        : false;
    final screenPermissionGranted = await _hasScreenCapturePermission();

    final parts = <String>[
      ollamaReachable ? 'Ollama 在线' : 'Ollama 未连接',
      modelAvailable ? '模型已安装' : '未找到模型 $model',
      screenPermissionGranted ? '屏幕录制已授权' : '屏幕录制未授权',
    ];

    return ProactiveVisionStatus(
      supported: true,
      ollamaReachable: ollamaReachable,
      modelAvailable: modelAvailable,
      screenPermissionGranted: screenPermissionGranted,
      model: model,
      message: parts.join(' · '),
    );
  }

  @override
  Future<bool> requestScreenPermission() async {
    try {
      return await _channel.invokeMethod<bool>(
            'requestScreenCapturePermission',
          ) ??
          false;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<ForegroundAppInfo> getForegroundAppInfo() async {
    try {
      final raw = await _channel.invokeMapMethod<String, String>(
        'getForegroundAppInfo',
      );
      return ForegroundAppInfo(
        name: raw?['name'] ?? '',
        bundleIdentifier: raw?['bundleIdentifier'] ?? '',
      );
    } catch (_) {
      return const ForegroundAppInfo(name: '', bundleIdentifier: '');
    }
  }

  @override
  Future<List<InstalledApplicationInfo>> listInstalledApplications() async {
    try {
      final raw = await _channel.invokeListMethod<Map<dynamic, dynamic>>(
        'listInstalledApplications',
      );
      final apps = (raw ?? const [])
          .map(
            (item) => InstalledApplicationInfo(
              name: item['name']?.toString() ?? '',
              bundleIdentifier: item['bundleIdentifier']?.toString() ?? '',
              aliases:
                  (item['aliases'] as List<dynamic>?)
                      ?.map((alias) => alias.toString().trim())
                      .where((alias) => alias.isNotEmpty)
                      .toList() ??
                  const [],
            ),
          )
          .where((app) => app.name.trim().isNotEmpty)
          .toList();
      apps.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
      return apps;
    } on MissingPluginException {
      return _applicationCatalog.listApplications();
    } catch (_) {
      return _applicationCatalog.listApplications();
    }
  }

  @override
  Future<ScreenAnalysisResult> analyzeCurrentScreen({
    required String ollamaUrl,
    required String model,
    required String prompt,
  }) async {
    final status = await checkStatus(ollamaUrl: ollamaUrl, model: model);
    if (!status.ollamaReachable) {
      throw StateError('无法连接到 Ollama 服务：$ollamaUrl');
    }
    if (!status.modelAvailable) {
      throw StateError('Ollama 中未找到模型：$model');
    }
    if (!status.screenPermissionGranted) {
      await requestScreenPermission();
      throw StateError('未获得屏幕录制权限。请授权 Control Center 后重启应用再试。');
    }

    final started = DateTime.now();
    final snapshot = await captureScreenSnapshot();
    return analyzeSnapshot(
      ollamaUrl: ollamaUrl,
      model: model,
      prompt: prompt,
      pngBytes: snapshot.pngBytes,
    ).then(
      (result) => ScreenAnalysisResult(
        response: result.response,
        elapsed: DateTime.now().difference(started),
      ),
    );
  }

  @override
  Future<ScreenSnapshot> captureScreenSnapshot() async {
    final screenshot = await _captureScreenPng();
    return ScreenSnapshot(
      pngBytes: screenshot,
      signature: _sampledFnv1a64(screenshot),
    );
  }

  @override
  Future<ScreenAnalysisResult> analyzeSnapshot({
    required String ollamaUrl,
    required String model,
    required String prompt,
    required List<int> pngBytes,
  }) async {
    final started = DateTime.now();
    final body = jsonEncode({
      'model': model,
      'prompt': prompt,
      'stream': false,
      'images': [base64Encode(pngBytes)],
    });

    final response = await _postJson(
      ollamaUrl,
      '/api/generate',
      body,
      timeout: const Duration(seconds: 90),
    );
    final decoded = jsonDecode(response) as Map<String, dynamic>;
    final text = decoded['response']?.toString().trim();
    if (text == null || text.isEmpty) {
      throw StateError('模型没有返回可读内容。');
    }
    return ScreenAnalysisResult(
      response: text,
      elapsed: DateTime.now().difference(started),
    );
  }

  int _sampledFnv1a64(List<int> bytes) {
    var hash = 0xcbf29ce484222325;
    final step = (bytes.length ~/ 4096).clamp(1, 256);
    for (var i = 0; i < bytes.length; i += step) {
      hash ^= bytes[i];
      hash = (hash * 0x100000001b3) & 0x7fffffffffffffff;
    }
    hash ^= bytes.length;
    return hash & 0x7fffffffffffffff;
  }

  Future<bool> _hasScreenCapturePermission() async {
    try {
      return await _channel.invokeMethod<bool>(
            'checkScreenCapturePermission',
          ) ??
          false;
    } catch (_) {
      return false;
    }
  }

  Future<List<int>> _captureScreenPng() async {
    final data = await _channel.invokeMethod<Uint8List>(
      'captureMainDisplayPng',
    );
    if (data == null || data.isEmpty) {
      throw StateError('截图失败，请确认屏幕录制权限已授予 Control Center。');
    }
    return data;
  }

  Future<bool> _isOllamaReachable(String baseUrl) async {
    try {
      await _getJson(baseUrl, '/api/tags', timeout: const Duration(seconds: 3));
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> _isModelAvailable(String baseUrl, String model) async {
    try {
      final response = await _getJson(
        baseUrl,
        '/api/tags',
        timeout: const Duration(seconds: 5),
      );
      final decoded = jsonDecode(response) as Map<String, dynamic>;
      final models = decoded['models'] as List<dynamic>? ?? const [];
      return models.any((raw) {
        final item = raw as Map<String, dynamic>;
        final name = item['name']?.toString();
        return name == model || name == '$model:latest';
      });
    } catch (_) {
      return false;
    }
  }

  Future<String> _getJson(
    String baseUrl,
    String path, {
    required Duration timeout,
  }) async {
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client.getUrl(_uri(baseUrl, path)).timeout(timeout);
      final response = await request.close().timeout(timeout);
      final text = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('HTTP ${response.statusCode}: $text');
      }
      return text;
    } finally {
      client.close(force: true);
    }
  }

  Future<String> _postJson(
    String baseUrl,
    String path,
    String body, {
    required Duration timeout,
  }) async {
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client
          .postUrl(_uri(baseUrl, path))
          .timeout(timeout);
      request.headers.contentType = ContentType.json;
      request.write(body);
      final response = await request.close().timeout(timeout);
      final text = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('HTTP ${response.statusCode}: $text');
      }
      return text;
    } finally {
      client.close(force: true);
    }
  }

  Uri _uri(String baseUrl, String path) {
    final normalized = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    return Uri.parse('$normalized$path');
  }
}
