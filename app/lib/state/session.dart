/// Сессия: URL сервера + Bearer-токен в shared_preferences, login/logout.
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/client.dart';
import '../api/models.dart';

/// Окружение по умолчанию; поле в форме логина редактируемое и персистится.
const kDefaultServerUrl = 'https://streams19.mirageflow.ca';
const kAppVersion = '1.0.0';

class SessionState extends ChangeNotifier {
  static const _prefServerUrl = 'server_url';
  static const _prefToken = 'auth_token';
  static const _prefUserId = 'user_id';
  static const _prefUserName = 'user_name';
  static const _prefUserPartnerId = 'user_partner_id';

  SharedPreferences? _prefs;
  String serverUrl = kDefaultServerUrl;
  UserInfo? user;
  ApiClient? _api;
  bool loaded = false;

  /// Заглушка транспорта для тестов.
  final ApiClient Function(String baseUrl, String? token) _clientFactory;

  SessionState({ApiClient Function(String baseUrl, String? token)? clientFactory})
      : _clientFactory = clientFactory ??
            ((baseUrl, token) => ApiClient(baseUrl: baseUrl, token: token));

  bool get isLoggedIn => _api?.token != null && user != null;

  /// Клиент доступен только после логина.
  ApiClient get api {
    final api = _api;
    if (api == null) {
      throw StateError('Not logged in');
    }
    return api;
  }

  Future<void> load() async {
    final prefs = _prefs = await SharedPreferences.getInstance();
    serverUrl = prefs.getString(_prefServerUrl) ?? kDefaultServerUrl;
    final token = prefs.getString(_prefToken);
    final userId = prefs.getInt(_prefUserId);
    if (token != null && userId != null) {
      user = UserInfo(
        id: userId,
        name: prefs.getString(_prefUserName) ?? '',
        partnerId: prefs.getInt(_prefUserPartnerId),
      );
      _api = _clientFactory(serverUrl, token);
    }
    loaded = true;
    notifyListeners();
  }

  static String _platformName() {
    try {
      if (Platform.isAndroid) return 'android';
      if (Platform.isIOS) return 'ios';
    } catch (_) {
      // Platform недоступен (web) — не критично
    }
    return 'other';
  }

  /// Бросает [StreamsApiException] (totp_required/totp_invalid/auth_failed…)
  /// наверх — форма логина сама решает, что показать.
  Future<void> login({
    required String url,
    required String login,
    required String password,
    String? totpCode,
  }) async {
    final normalized = url.trim().replaceFirst(RegExp(r'/+$'), '');
    final client = _clientFactory(normalized, null);
    try {
      final result = await client.login(
        login: login,
        password: password,
        totpCode: totpCode,
        deviceName: 'Streams App (${_platformName()})',
        platform: _platformName(),
        appVersion: kAppVersion,
      );
      serverUrl = normalized;
      user = result.user;
      client.token = result.device.token;
      _api = client;
      final prefs = _prefs;
      if (prefs != null) {
        await prefs.setString(_prefServerUrl, normalized);
        await prefs.setString(_prefToken, result.device.token);
        await prefs.setInt(_prefUserId, result.user.id);
        await prefs.setString(_prefUserName, result.user.name);
        final partnerId = result.user.partnerId;
        if (partnerId != null) {
          await prefs.setInt(_prefUserPartnerId, partnerId);
        }
      }
      notifyListeners();
    } catch (_) {
      client.close();
      rethrow;
    }
  }

  Future<void> logout() async {
    try {
      await _api?.logout();
    } on StreamsApiException {
      // Токен уже мёртв — локальный выход всё равно выполняем
    }
    await _clearLocal();
  }

  /// Принудительный локальный выход (auth_failed в любом запросе).
  Future<void> forceLogout() => _clearLocal();

  Future<void> _clearLocal() async {
    _api?.close();
    _api = null;
    user = null;
    final prefs = _prefs;
    if (prefs != null) {
      await prefs.remove(_prefToken);
      await prefs.remove(_prefUserId);
      await prefs.remove(_prefUserName);
      await prefs.remove(_prefUserPartnerId);
    }
    notifyListeners();
  }
}
