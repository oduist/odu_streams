/// JSON-RPC 2.0 клиент streams_mobile API v1 поверх пакета http.
///
/// Конверт запроса: `{"jsonrpc":"2.0","method":"call","id":N,"params":{}}`,
/// полезный ответ — в `result`. Прикладные ошибки сервер кладёт в result
/// как `{"error": {"code", "message"}}` — они превращаются в
/// [StreamsApiException] с исходным кодом.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class StreamsApiException implements Exception {
  /// auth_failed | access_denied | not_found | bad_request | totp_required |
  /// totp_invalid — коды контракта; network / bad_response / server_error —
  /// клиентские коды транспортного уровня.
  final String code;
  final String message;

  const StreamsApiException(this.code, this.message);

  bool get isAuthFailed => code == 'auth_failed';

  @override
  String toString() => 'StreamsApiException($code): $message';
}

class ApiClient {
  static const apiBase = '/streams/mobile/v1';

  String baseUrl;
  String? token;
  final http.Client _http;
  int _rpcId = 0;

  ApiClient({required String baseUrl, this.token, http.Client? httpClient})
      // без завершающего слэша, чтобы конкатенация путей была однозначной
      : baseUrl = baseUrl.replaceFirst(RegExp(r'/+$'), ''),
        _http = httpClient ?? http.Client();

  Uri _uri(String path) => Uri.parse('$baseUrl$apiBase$path');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  /// Ссылка для скачивания вложения (требует Bearer-заголовка, в MVP
  /// используется только для отображения).
  String attachmentUrl(int attachmentId) =>
      '$baseUrl$apiBase/attachment/$attachmentId';

  Future<dynamic> _call(String path, [Map<String, dynamic>? params]) async {
    final envelope = jsonEncode({
      'jsonrpc': '2.0',
      'method': 'call',
      'id': ++_rpcId,
      'params': params ?? <String, dynamic>{},
    });
    http.Response response;
    try {
      response = await _http
          .post(_uri(path), headers: _headers, body: envelope)
          .timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw const StreamsApiException('network', 'Request timed out');
    } on http.ClientException catch (e) {
      throw StreamsApiException('network', e.message);
    } catch (e) {
      // SocketException и прочие ошибки транспорта без зависимости от dart:io
      throw StreamsApiException('network', e.toString());
    }
    if (response.statusCode != 200) {
      throw StreamsApiException(
          'network', 'HTTP ${response.statusCode} for $path');
    }
    dynamic decoded;
    try {
      decoded = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw const StreamsApiException('bad_response', 'Malformed JSON');
    }
    if (decoded is! Map) {
      throw const StreamsApiException('bad_response', 'Not a JSON object');
    }
    // Ошибка уровня JSON-RPC (необработанное исключение Odoo)
    if (decoded['error'] != null) {
      final err = decoded['error'];
      final message = err is Map
          ? asString(err['message'], 'Internal server error')
          : err.toString();
      throw StreamsApiException('server_error', message);
    }
    final result = decoded['result'];
    // Прикладная ошибка контракта: result = {"error": {"code", "message"}}
    if (result is Map && result['error'] is Map) {
      final err = (result['error'] as Map).cast<String, dynamic>();
      throw StreamsApiException(
          asString(err['code'], 'unknown'), asString(err['message']));
    }
    return result;
  }

  Map<String, dynamic> _asMap(dynamic result) => result is Map
      ? result.cast<String, dynamic>()
      : throw const StreamsApiException('bad_response', 'Expected object');

  // ------------------------------------------------------------
  // Аутентификация
  // ------------------------------------------------------------

  Future<LoginResult> login({
    required String login,
    required String password,
    String? totpCode,
    String? deviceName,
    String? platform,
    String? appVersion,
  }) async {
    final result = await _call('/auth/login', {
      'login': login,
      'password': password,
      if (totpCode != null && totpCode.isNotEmpty) 'totp_code': totpCode,
      'device_name': ?deviceName,
      'platform': ?platform,
      'app_version': ?appVersion,
    });
    return LoginResult.fromJson(_asMap(result));
  }

  Future<void> logout() => _call('/auth/logout');

  Future<void> pushRegister({
    required String pushToken,
    required bool pushEnabled,
  }) =>
      _call('/push/register',
          {'push_token': pushToken, 'push_enabled': pushEnabled});

  // ------------------------------------------------------------
  // Старт клиента
  // ------------------------------------------------------------

  Future<InitResult> init() async =>
      InitResult.fromJson(_asMap(await _call('/init')));

  // ------------------------------------------------------------
  // Каналы
  // ------------------------------------------------------------

  Future<List<Channel>> channels({
    List<String>? kinds,
    String? search,
    int? limit,
    int? offset,
  }) async {
    final result = _asMap(await _call('/channels', {
      'kinds': ?kinds,
      if (search != null && search.isNotEmpty) 'search': search,
      'limit': ?limit,
      'offset': ?offset,
    }));
    return asMapList(result['channels']).map(Channel.fromJson).toList();
  }

  Future<List<Message>> channelMessages({
    required int channelId,
    int? beforeId,
    int? limit,
  }) async {
    final result = _asMap(await _call('/channel/messages', {
      'channel_id': channelId,
      'before_id': ?beforeId,
      'limit': ?limit,
    }));
    return asMapList(result['messages']).map(Message.fromJson).toList();
  }

  Future<Message> channelPost({
    required int channelId,
    required String body,
    required String kind,
    List<int>? attachmentIds,
    List<int>? mentionedPartnerIds,
  }) async {
    final result = await _call('/channel/post', {
      'channel_id': channelId,
      'body': body,
      'kind': kind,
      'attachment_ids': ?attachmentIds,
      'mentioned_partner_ids': ?mentionedPartnerIds,
    });
    return Message.fromJson(_asMap(result));
  }

  Future<int> channelMarkRead({
    required int channelId,
    required int lastMessageId,
  }) async {
    final result = _asMap(await _call('/channel/mark_read', {
      'channel_id': channelId,
      'last_message_id': lastMessageId,
    }));
    return asInt(result['unread']);
  }

  /// filters == null — чтение, иначе дозапись переданных ключей.
  Future<Map<String, bool>> channelFilters({
    required int channelId,
    Map<String, bool>? filters,
  }) async {
    final result = _asMap(await _call('/channel/filters', {
      'channel_id': channelId,
      'filters': ?filters,
    }));
    final raw = result['filters'];
    if (raw is! Map) return const {};
    return raw.map((k, v) => MapEntry(k.toString(), v == true));
  }

  // ------------------------------------------------------------
  // Changes / подписка на поля
  // ------------------------------------------------------------

  Future<ChangesFeed> changesFeed({int? beforeId, int? limit}) async =>
      ChangesFeed.fromJson(_asMap(await _call('/changes/feed', {
        'before_id': ?beforeId,
        'limit': ?limit,
      })));

  Future<Map<String, dynamic>> fieldsSubscription({
    required String resModel,
    required int resId,
    List<int>? fieldIds,
  }) async =>
      _asMap(await _call('/fields/subscription', {
        'res_model': resModel,
        'res_id': resId,
        'field_ids': ?fieldIds,
      }));

  // ------------------------------------------------------------
  // Notify
  // ------------------------------------------------------------

  Future<List<NotifyItem>> notifyFeed({
    required String box,
    int? beforeId,
    int? limit,
  }) async {
    final result = _asMap(await _call('/notify/feed', {
      'box': box,
      'before_id': ?beforeId,
      'limit': ?limit,
    }));
    return asMapList(result['items']).map(NotifyItem.fromJson).toList();
  }

  Future<int> notifySend({
    required String body,
    required List<int> userIds,
    List<int>? attachmentIds,
    bool? isSticky,
    int? timeout,
    String? resModel,
    int? resId,
  }) async {
    final result = _asMap(await _call('/notify/send', {
      'body': body,
      'user_ids': userIds,
      'attachment_ids': ?attachmentIds,
      'is_sticky': ?isSticky,
      'timeout': ?timeout,
      'res_model': ?resModel,
      'res_id': ?resId,
    }));
    return asInt(result['id']);
  }

  Future<int> notifyReply({
    required int parentId,
    required String body,
    List<int>? attachmentIds,
    bool? isSticky,
    int? timeout,
  }) async {
    final result = _asMap(await _call('/notify/reply', {
      'parent_id': parentId,
      'body': body,
      'attachment_ids': ?attachmentIds,
      'is_sticky': ?isSticky,
      'timeout': ?timeout,
    }));
    return asInt(result['id']);
  }

  /// Возвращает актуальный счётчик непрочитанных.
  Future<int> notifyMarkRead(List<int> notifyIds) async {
    final result = _asMap(await _call('/notify/mark_read', {
      'notify_ids': notifyIds,
    }));
    return asInt(result['counter']);
  }

  Future<void> notifyPopupShown(List<int> notifyIds) =>
      _call('/notify/popup_shown', {'notify_ids': notifyIds});

  // ------------------------------------------------------------
  // Poll
  // ------------------------------------------------------------

  Future<PollResult> poll(int lastBusId) async =>
      PollResult.fromJson(_asMap(await _call('/poll', {
        'last_bus_id': lastBusId,
      })));

  void close() => _http.close();
}
