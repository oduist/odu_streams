/// Тесты JSON-RPC клиента: конверт запроса, разбор result и наших ошибок
/// `{"error": {"code","message"}}` → StreamsApiException.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:streams_app/api/client.dart';

http.Response _jsonResponse(Map<String, dynamic> body, [int status = 200]) =>
    http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

void main() {
  test('конверт запроса: jsonrpc 2.0 + Bearer-токен', () async {
    late http.Request captured;
    final client = ApiClient(
      baseUrl: 'https://example.com/',
      token: '42|secret',
      httpClient: MockClient((request) async {
        captured = request;
        return _jsonResponse({
          'jsonrpc': '2.0',
          'id': 1,
          'result': {'ok': true, 'unread': 0},
        });
      }),
    );
    await client.channelMarkRead(channelId: 21, lastMessageId: 101);

    expect(captured.url.toString(),
        'https://example.com/streams/mobile/v1/channel/mark_read');
    expect(captured.headers['Authorization'], 'Bearer 42|secret');
    final envelope = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(envelope['jsonrpc'], '2.0');
    expect(envelope['method'], 'call');
    expect(envelope['id'], isA<int>());
    expect(envelope['params'],
        {'channel_id': 21, 'last_message_id': 101});
  });

  test('auth_failed → исключение с кодом', () async {
    final client = ApiClient(
      baseUrl: 'https://example.com',
      token: 'dead|token',
      httpClient: MockClient((request) async => _jsonResponse({
            'jsonrpc': '2.0',
            'id': 1,
            'result': {
              'error': {'code': 'auth_failed', 'message': 'Invalid token'},
            },
          })),
    );
    try {
      await client.init();
      fail('должно было бросить StreamsApiException');
    } on StreamsApiException catch (e) {
      expect(e.code, 'auth_failed');
      expect(e.isAuthFailed, isTrue);
      expect(e.message, 'Invalid token');
    }
  });

  test('totp_required при логине', () async {
    final client = ApiClient(
      baseUrl: 'https://example.com',
      httpClient: MockClient((request) async => _jsonResponse({
            'jsonrpc': '2.0',
            'id': 1,
            'result': {
              'error': {'code': 'totp_required', 'message': '2FA enabled'},
            },
          })),
    );
    await expectLater(
      client.login(login: 'alice', password: 'pw'),
      throwsA(isA<StreamsApiException>()
          .having((e) => e.code, 'code', 'totp_required')),
    );
  });

  test('ошибка уровня JSON-RPC → server_error', () async {
    final client = ApiClient(
      baseUrl: 'https://example.com',
      token: 't',
      httpClient: MockClient((request) async => _jsonResponse({
            'jsonrpc': '2.0',
            'id': 1,
            'error': {'code': 200, 'message': 'Odoo Server Error'},
          })),
    );
    await expectLater(
      client.init(),
      throwsA(isA<StreamsApiException>()
          .having((e) => e.code, 'code', 'server_error')
          .having((e) => e.message, 'message', 'Odoo Server Error')),
    );
  });

  test('HTTP != 200 → network', () async {
    final client = ApiClient(
      baseUrl: 'https://example.com',
      token: 't',
      httpClient: MockClient(
          (request) async => http.Response('Bad Gateway', 502)),
    );
    await expectLater(
      client.init(),
      throwsA(isA<StreamsApiException>()
          .having((e) => e.code, 'code', 'network')),
    );
  });

  test('успешный разбор: /channels и /notify/mark_read', () async {
    final client = ApiClient(
      baseUrl: 'https://example.com',
      token: 't',
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/channels')) {
          return _jsonResponse({
            'jsonrpc': '2.0',
            'id': 1,
            'result': {
              'channels': [
                {
                  'id': 21,
                  'name': 'Deco Addict',
                  'kind': 'record',
                  'res_model': 'res.partner',
                  'res_id': 14,
                  'unread': 3,
                  'last_message': null,
                  'members_count': 4,
                }
              ],
            },
          });
        }
        return _jsonResponse({
          'jsonrpc': '2.0',
          'id': 2,
          'result': {'counter': 0},
        });
      }),
    );
    final channels = await client.channels(kinds: ['record']);
    expect(channels.single.name, 'Deco Addict');
    expect(channels.single.unread, 3);

    final counter = await client.notifyMarkRead([7, 8]);
    expect(counter, 0);
  });
}
