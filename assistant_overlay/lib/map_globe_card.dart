import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// 地图态势卡片（左上角悬浮 WebView）
///
/// 加载 jarvis-map-module 的 embed 模式（http://127.0.0.1:5199/?embed=1）：
/// 透明背景 + 玻璃 HUD 卡片 + Three.js 3D 地球，随唤醒显示 / 待机隐藏。
/// 服务未启动时显示 OFFLINE 占位并可点击重试（软失败，不影响主流程）。
class MapGlobeCard extends StatefulWidget {
  final double width;
  final double height;

  const MapGlobeCard({super.key, required this.width, required this.height});

  @override
  State<MapGlobeCard> createState() => _MapGlobeCardState();
}

class _MapGlobeCardState extends State<MapGlobeCard> {
  static const String _mapUrl = 'http://127.0.0.1:5199/?embed=1';

  late final WebViewController _controller;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    _initController();
  }

  void _initController() {
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0x00000000))
      ..setNavigationDelegate(
        NavigationDelegate(
          onWebResourceError: (WebResourceError error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() => _offline = true);
            }
          },
          onPageFinished: (String url) {
            if (mounted && _offline) {
              setState(() => _offline = false);
            }
          },
        ),
      )
      ..loadRequest(Uri.parse(_mapUrl));
  }

  void _retry() {
    setState(() => _offline = false);
    _controller.loadRequest(Uri.parse(_mapUrl));
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: SizedBox(
        width: widget.width,
        height: widget.height,
        child: _offline ? _buildOffline() : WebViewWidget(controller: _controller),
      ),
    );
  }

  Widget _buildOffline() {
    return Container(
      width: widget.width,
      height: widget.height,
      color: const Color(0x330D67BC),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.public_off, color: Color(0x886EB9FF), size: 26),
            const SizedBox(height: 8),
            const Text(
              'SATCOM OFFLINE',
              style: TextStyle(
                color: Color(0x886EB9FF),
                fontSize: 10,
                letterSpacing: 2,
              ),
            ),
            const SizedBox(height: 6),
            GestureDetector(
              onTap: _retry,
              child: const Text(
                'RETRY',
                style: TextStyle(
                  color: Color(0xFF6EB9FF),
                  fontSize: 9,
                  letterSpacing: 2,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
