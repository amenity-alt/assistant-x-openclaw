import 'dart:io';

import 'base/proactive_vision_service_base.dart';

class InstalledApplicationCatalog {
  Future<List<InstalledApplicationInfo>> listApplications() async {
    final apps = <InstalledApplicationInfo>[];
    if (Platform.isMacOS) {
      apps.addAll(await _listMacOSApplications());
    } else if (Platform.isLinux) {
      apps.addAll(await _listLinuxApplications());
    } else if (Platform.isWindows) {
      apps.addAll(await _listWindowsApplications());
    }
    return _dedupeAndSort(apps);
  }

  Future<List<InstalledApplicationInfo>> _listMacOSApplications() async {
    final home = Platform.environment['HOME'] ?? '';
    final roots = [
      Directory('/Applications'),
      Directory('/Applications/Utilities'),
      Directory('/System/Applications'),
      Directory('/System/Applications/Utilities'),
      Directory('/System/Library/CoreServices'),
      if (home.isNotEmpty) Directory('$home/Applications'),
    ];
    final apps = <InstalledApplicationInfo>[];
    for (final root in roots) {
      if (!await root.exists()) continue;
      await for (final entity in root.list(
        recursive: true,
        followLinks: false,
      )) {
        if (entity is! Directory || !entity.path.endsWith('.app')) continue;
        final name = entity.uri.pathSegments.isEmpty
            ? entity.path
            : entity.uri.pathSegments.last.replaceFirst(RegExp(r'\.app$'), '');
        final metadata = await _readMacOSAppMetadata(entity, name);
        apps.add(
          InstalledApplicationInfo(
            name: metadata.name,
            bundleIdentifier: metadata.bundleIdentifier,
            aliases: metadata.aliases,
          ),
        );
      }
    }
    return apps;
  }

  Future<_MacOSAppMetadata> _readMacOSAppMetadata(
    Directory app,
    String fallbackName,
  ) async {
    final names = <String>{fallbackName};
    var bundleIdentifier = '';
    final infoPlist = File('${app.path}/Contents/Info.plist');
    if (await infoPlist.exists()) {
      try {
        final result = await Process.run('plutil', [
          '-convert',
          'json',
          '-o',
          '-',
          infoPlist.path,
        ]);
        if (result.exitCode == 0) {
          final text = result.stdout.toString();
          bundleIdentifier = _jsonStringValue(text, 'CFBundleIdentifier');
          for (final key in ['CFBundleDisplayName', 'CFBundleName']) {
            final value = _jsonStringValue(text, key);
            if (value.isNotEmpty) names.add(value);
          }
        }
      } catch (_) {}
    }

    final resources = Directory('${app.path}/Contents/Resources');
    if (await resources.exists()) {
      await for (final entity in resources.list(followLinks: false)) {
        if (entity is! Directory || !entity.path.endsWith('.lproj')) continue;
        final strings = File('${entity.path}/InfoPlist.strings');
        if (!await strings.exists()) continue;
        try {
          final content = await strings.readAsString();
          for (final key in ['CFBundleDisplayName', 'CFBundleName']) {
            final value = _plistStringValue(content, key);
            if (value.isNotEmpty) names.add(value);
          }
        } catch (_) {}
      }
    }

    final primary = names.first;
    final aliases = names.where((name) => name != primary).toList();
    aliases.sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return _MacOSAppMetadata(
      name: primary,
      bundleIdentifier: bundleIdentifier,
      aliases: aliases,
    );
  }

  String _jsonStringValue(String json, String key) {
    final pattern = RegExp('"${RegExp.escape(key)}"\\s*:\\s*"([^"]*)"');
    return pattern.firstMatch(json)?.group(1)?.trim() ?? '';
  }

  String _plistStringValue(String content, String key) {
    final pattern = RegExp(
      '"?${RegExp.escape(key)}"?\\s*=\\s*"([^"]*)"',
      multiLine: true,
    );
    return pattern.firstMatch(content)?.group(1)?.trim() ?? '';
  }

  Future<List<InstalledApplicationInfo>> _listLinuxApplications() async {
    final home = Platform.environment['HOME'] ?? '';
    final roots = [
      Directory('/usr/share/applications'),
      Directory('/usr/local/share/applications'),
      if (home.isNotEmpty) Directory('$home/.local/share/applications'),
    ];
    final apps = <InstalledApplicationInfo>[];
    for (final root in roots) {
      if (!await root.exists()) continue;
      await for (final entity in root.list(
        recursive: true,
        followLinks: false,
      )) {
        if (entity is! File || !entity.path.endsWith('.desktop')) continue;
        final parsed = await _parseDesktopFile(entity);
        if (parsed != null) apps.add(parsed);
      }
    }
    return apps;
  }

  Future<InstalledApplicationInfo?> _parseDesktopFile(File file) async {
    try {
      var name = '';
      var noDisplay = false;
      final lines = await file.readAsLines();
      for (final line in lines) {
        final trimmed = line.trim();
        if (trimmed.startsWith('Name=') && name.isEmpty) {
          name = trimmed.substring(5).trim();
        } else if (trimmed.startsWith('NoDisplay=')) {
          noDisplay = trimmed.substring(10).trim().toLowerCase() == 'true';
        }
      }
      if (name.isEmpty || noDisplay) return null;
      return InstalledApplicationInfo(
        name: name,
        bundleIdentifier: file.uri.pathSegments.last,
        aliases: _desktopLocalizedNames(lines, name),
      );
    } catch (_) {
      return null;
    }
  }

  List<String> _desktopLocalizedNames(List<String> lines, String primaryName) {
    final aliases = <String>{};
    for (final line in lines) {
      final trimmed = line.trim();
      if (!trimmed.startsWith('Name[')) continue;
      final index = trimmed.indexOf('=');
      if (index < 0) continue;
      final value = trimmed.substring(index + 1).trim();
      if (value.isNotEmpty && value != primaryName) aliases.add(value);
    }
    final result = aliases.toList();
    result.sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return result;
  }

  Future<List<InstalledApplicationInfo>> _listWindowsApplications() async {
    final roots = <Directory>[];
    for (final key in ['APPDATA', 'PROGRAMDATA']) {
      final value = Platform.environment[key];
      if (value == null || value.isEmpty) continue;
      roots.add(Directory('$value\\Microsoft\\Windows\\Start Menu\\Programs'));
    }
    for (final key in ['ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA']) {
      final value = Platform.environment[key];
      if (value == null || value.isEmpty) continue;
      roots.add(Directory(value));
    }

    final apps = <InstalledApplicationInfo>[];
    for (final root in roots) {
      if (!await root.exists()) continue;
      await for (final entity in root.list(
        recursive: true,
        followLinks: false,
      )) {
        if (entity is File && entity.path.toLowerCase().endsWith('.lnk')) {
          apps.add(
            InstalledApplicationInfo(
              name: _basenameWithoutExtension(entity.path),
              bundleIdentifier: entity.path,
            ),
          );
        } else if (entity is File &&
            entity.path.toLowerCase().endsWith('.exe') &&
            _isLikelyWindowsAppExe(entity.path)) {
          apps.add(
            InstalledApplicationInfo(
              name: _basenameWithoutExtension(entity.path),
              bundleIdentifier: entity.path,
            ),
          );
        }
      }
    }
    return apps;
  }

  bool _isLikelyWindowsAppExe(String path) {
    final lower = path.toLowerCase();
    if (lower.contains('\\windows\\')) return false;
    final file = _basenameWithoutExtension(path).toLowerCase();
    return !{
      'uninstall',
      'update',
      'setup',
      'crashpad_handler',
      'helper',
    }.contains(file);
  }

  List<InstalledApplicationInfo> _dedupeAndSort(
    List<InstalledApplicationInfo> apps,
  ) {
    final byKey = <String, InstalledApplicationInfo>{};
    for (final app in apps) {
      final name = app.name.trim();
      if (name.isEmpty) continue;
      final bundleIdentifier = app.bundleIdentifier.trim();
      final key = (bundleIdentifier.isEmpty ? name : bundleIdentifier)
          .toLowerCase();
      byKey.putIfAbsent(
        key,
        () => InstalledApplicationInfo(
          name: name,
          bundleIdentifier: bundleIdentifier,
          aliases: app.aliases,
        ),
      );
    }
    final result = byKey.values.toList();
    result.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    return result;
  }

  String _basenameWithoutExtension(String path) {
    final normalized = path.replaceAll('\\', '/');
    final filename = normalized.split('/').last;
    final index = filename.lastIndexOf('.');
    return index <= 0 ? filename : filename.substring(0, index);
  }
}

class _MacOSAppMetadata {
  final String name;
  final String bundleIdentifier;
  final List<String> aliases;

  const _MacOSAppMetadata({
    required this.name,
    required this.bundleIdentifier,
    required this.aliases,
  });
}
