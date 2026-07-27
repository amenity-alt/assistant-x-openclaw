import 'dart:io';
import 'base/permission_service_base.dart';
import 'base/proactive_vision_service_base.dart';
import 'base/speaker_service_base.dart';
import 'base/voice_assistant_service_base.dart';
import 'config_service.dart';
import 'platform/macos_permission_service.dart';
import 'platform/macos_proactive_vision_service.dart';
import 'platform/macos_speaker_service.dart';
import 'platform/macos_voice_assistant_service.dart';
import 'proactive_vision_watcher.dart';
import 'platform/unsupported_proactive_vision_service.dart';
import 'platform/windows_permission_service.dart';
import 'platform/windows_speaker_service.dart';
import 'platform/windows_voice_assistant_service.dart';
import 'platform/linux_permission_service.dart';
import 'platform/linux_speaker_service.dart';
import 'platform/linux_voice_assistant_service.dart';

class ServiceFactory {
  static PermissionServiceBase? _permissionService;
  static SpeakerServiceBase? _speakerService;
  static VoiceAssistantServiceBase? _voiceAssistantService;
  static ProactiveVisionServiceBase? _proactiveVisionService;
  static ProactiveVisionWatcher? _proactiveVisionWatcher;

  static PermissionServiceBase get permissionService {
    _permissionService ??= _createPermissionService();
    return _permissionService!;
  }

  static SpeakerServiceBase get speakerService {
    _speakerService ??= _createSpeakerService();
    return _speakerService!;
  }

  static VoiceAssistantServiceBase get voiceAssistantService {
    _voiceAssistantService ??= _createVoiceAssistantService();
    return _voiceAssistantService!;
  }

  static ProactiveVisionServiceBase get proactiveVisionService {
    _proactiveVisionService ??= _createProactiveVisionService();
    return _proactiveVisionService!;
  }

  static ProactiveVisionWatcher get proactiveVisionWatcher {
    _proactiveVisionWatcher ??= ProactiveVisionWatcher(
      configService: ConfigService(),
      visionService: proactiveVisionService,
      onLog: voiceAssistantService.addLog,
    );
    return _proactiveVisionWatcher!;
  }

  static PermissionServiceBase _createPermissionService() {
    if (Platform.isMacOS) return MacOSPermissionService();
    if (Platform.isWindows) return WindowsPermissionService();
    return LinuxPermissionService();
  }

  static SpeakerServiceBase _createSpeakerService() {
    if (Platform.isMacOS) return MacOSSpeakerService();
    if (Platform.isWindows) return WindowsSpeakerService();
    return LinuxSpeakerService();
  }

  static VoiceAssistantServiceBase _createVoiceAssistantService() {
    if (Platform.isMacOS) return MacOSVoiceAssistantService();
    if (Platform.isWindows) return WindowsVoiceAssistantService();
    return LinuxVoiceAssistantService();
  }

  static ProactiveVisionServiceBase _createProactiveVisionService() {
    if (Platform.isMacOS) return MacOSProactiveVisionService();
    return UnsupportedProactiveVisionService();
  }
}
