/// Разбор моделей из JSON-примеров контракта api-v1.md.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:streams_app/api/models.dart';
import 'package:streams_app/util/html_text.dart';

void main() {
  group('LoginResult', () {
    test('пример контракта /auth/login', () {
      final json = jsonDecode('''
      {
        "token": "42|u_kX...",
        "device_id": 42,
        "user": {"id": 6, "name": "Alice", "partner_id": 9},
        "server_version": "19.0.1.0.0"
      }
      ''') as Map<String, dynamic>;
      final result = LoginResult.fromJson(json);
      expect(result.device.id, 42);
      expect(result.device.token, '42|u_kX...');
      expect(result.user.id, 6);
      expect(result.user.name, 'Alice');
      expect(result.user.partnerId, 9);
      expect(result.serverVersion, '19.0.1.0.0');
    });
  });

  group('Message', () {
    test('пример контракта /channel/messages', () {
      final json = jsonDecode('''
      {
        "id": 101,
        "body": "<p>Привет</p>",
        "date": "2026-08-18 11:58:03",
        "kind": "comment",
        "author": {"id": 9, "name": "Alice"},
        "attachments": [
          {"id": 5, "name": "spec.pdf", "mimetype": "application/pdf", "size": 12345}
        ],
        "tracking": null,
        "reactions": [{"content": "👍", "count": 2, "me": true}],
        "parent_id": null
      }
      ''') as Map<String, dynamic>;
      final message = Message.fromJson(json);
      expect(message.id, 101);
      expect(message.kind, 'comment');
      expect(message.author?.id, 9);
      expect(message.date, DateTime.utc(2026, 8, 18, 11, 58, 3));
      expect(message.attachments, hasLength(1));
      expect(message.attachments.first.mimetype, 'application/pdf');
      expect(message.tracking, isNull);
      expect(message.reactions.single.content, '👍');
      expect(message.reactions.single.count, 2);
      expect(message.reactions.single.me, isTrue);
      expect(message.parentId, isNull);
    });

    test('change-сообщение с tracking; kind=false — прочее', () {
      final change = Message.fromJson(jsonDecode('''
      {
        "id": 120,
        "body": "",
        "date": "2026-08-18 11:20:00",
        "kind": "change",
        "author": {"id": 11, "name": "Bob"},
        "attachments": [],
        "tracking": [
          {"field": "email", "label": "Email", "old": "a@x", "new": "b@x"}
        ],
        "reactions": [],
        "parent_id": null
      }
      ''') as Map<String, dynamic>);
      expect(change.kind, 'change');
      expect(change.tracking, hasLength(1));
      expect(change.tracking!.single.field, 'email');
      expect(change.tracking!.single.label, 'Email');
      expect(change.tracking!.single.oldValue, 'a@x');
      expect(change.tracking!.single.newValue, 'b@x');

      final other = Message.fromJson({
        'id': 1,
        'body': 'x',
        'date': false,
        'kind': false,
        'author': false,
        'attachments': [],
        'tracking': null,
        'reactions': [],
        'parent_id': false,
      });
      expect(other.kind, isNull);
      expect(other.author, isNull);
      expect(other.date, isNull);
    });
  });

  group('Channel', () {
    test('пример контракта /channels', () {
      final channel = Channel.fromJson(jsonDecode('''
      {
        "id": 21,
        "name": "Deco Addict",
        "kind": "record",
        "res_model": "res.partner",
        "res_id": 14,
        "unread": 3,
        "last_message": null,
        "members_count": 4
      }
      ''') as Map<String, dynamic>);
      expect(channel.id, 21);
      expect(channel.kind, 'record');
      expect(channel.resModel, 'res.partner');
      expect(channel.resId, 14);
      expect(channel.unread, 3);
      expect(channel.lastMessage, isNull);
      expect(channel.membersCount, 4);
    });
  });

  group('NotifyItem', () {
    test('received: пример контракта /notify/feed', () {
      final item = NotifyItem.fromJson(jsonDecode('''
      {
        "id": 7,
        "date": "2026-08-18 10:00:00",
        "author": {"id": 6, "name": "Alice"},
        "body": "<p>Позвони клиенту</p>",
        "is_sticky": false,
        "timeout": 10,
        "res_model": "res.partner",
        "res_id": 14,
        "record_name": "Deco Addict",
        "attachments": [
          {"id": 5, "name": "spec.pdf", "mimetype": "application/pdf", "size": 1}
        ],
        "voice": {"id": 6, "mimetype": "audio/webm", "duration": 12},
        "transcript": null,
        "transcript_state": "none",
        "parent_id": null,
        "read_date": false,
        "popup_shown": true
      }
      ''') as Map<String, dynamic>);
      expect(item.id, 7);
      expect(item.author?.name, 'Alice');
      expect(item.isSticky, isFalse);
      expect(item.timeout, 10);
      expect(item.recordName, 'Deco Addict');
      expect(item.voice?.duration, 12);
      expect(item.transcript, isNull);
      expect(item.readDate, isNull); // false → нет значения
      expect(item.popupShown, isTrue);
      expect(item.recipients, isNull);
    });

    test('sent: recipients со статусом прочтения', () {
      final item = NotifyItem.fromJson(jsonDecode('''
      {
        "id": 8,
        "date": "2026-08-18 10:05:00",
        "author": {"id": 6, "name": "Alice"},
        "body": "<p>ok</p>",
        "is_sticky": true,
        "timeout": 10,
        "res_model": null,
        "res_id": null,
        "record_name": null,
        "attachments": [],
        "voice": null,
        "transcript": null,
        "transcript_state": "none",
        "parent_id": 7,
        "recipients": [
          {"user_id": 11, "name": "Bob", "read_date": "2026-08-18 10:06:00"},
          {"user_id": 12, "name": "Carl", "read_date": false}
        ]
      }
      ''') as Map<String, dynamic>);
      expect(item.isSticky, isTrue);
      expect(item.parentId, 7);
      expect(item.recipients, hasLength(2));
      expect(item.recipients![0].readDate, DateTime.utc(2026, 8, 18, 10, 6));
      expect(item.recipients![1].readDate, isNull);
    });
  });

  group('ChangesFeed', () {
    test('пример контракта /changes/feed', () {
      final feed = ChangesFeed.fromJson(jsonDecode('''
      {
        "channel_id": 33,
        "items": [
          {
            "res_model": "res.partner",
            "res_id": 14,
            "record_name": "Deco Addict",
            "last_message_id": 120,
            "unread": true,
            "changes": [
              {
                "message_id": 120,
                "date": "2026-08-18 11:20:00",
                "author": "Bob",
                "author_id": 11,
                "values": [
                  {"field_id": 77, "field_name": "email", "field_desc": "Email",
                   "old": "a@x.com", "new": "b@x.com"}
                ]
              }
            ]
          }
        ]
      }
      ''') as Map<String, dynamic>);
      expect(feed.channelId, 33);
      final entry = feed.items.single;
      expect(entry.recordName, 'Deco Addict');
      expect(entry.lastMessageId, 120);
      expect(entry.unread, isTrue);
      final event = entry.changes.single;
      expect(event.author, 'Bob');
      expect(event.values.single.fieldDesc, 'Email');
      expect(event.values.single.oldValue, 'a@x.com');
      expect(event.values.single.newValue, 'b@x.com');
    });

    test('личного канала ещё нет: channel_id null', () {
      final feed = ChangesFeed.fromJson({'channel_id': null, 'items': []});
      expect(feed.channelId, isNull);
      expect(feed.items, isEmpty);
    });
  });

  group('InitResult', () {
    test('пример контракта /init', () {
      final result = InitResult.fromJson(jsonDecode('''
      {
        "user": {"id": 6, "name": "Alice", "partner_id": 9},
        "notify": {
          "counter": 2,
          "channel_id": 15,
          "default_timeout": 10,
          "pending": []
        },
        "unread_total": 5,
        "filters_defaults": {"comment": true, "note": true, "message": true,
                             "change": false, "activity": true},
        "server_time": "2026-08-18 12:00:00"
      }
      ''') as Map<String, dynamic>);
      expect(result.user.partnerId, 9);
      expect(result.notify.counter, 2);
      expect(result.notify.channelId, 15);
      expect(result.notify.defaultTimeout, 10);
      expect(result.notify.pending, isEmpty);
      expect(result.unreadTotal, 5);
      expect(result.filtersDefaults['change'], isFalse);
      expect(result.filtersDefaults['comment'], isTrue);
      expect(result.serverTime, DateTime.utc(2026, 8, 18, 12));
    });
  });

  group('PollResult', () {
    test('пример контракта /poll', () {
      final result = PollResult.fromJson(jsonDecode('''
      {
        "last_bus_id": 512,
        "notifications": [
          {"id": 510, "type": "discuss.channel/new_message",
           "payload": {"id": 21, "data": {}}},
          {"id": 512, "type": "streams.changes/updated", "payload": {"id": 33}}
        ]
      }
      ''') as Map<String, dynamic>);
      expect(result.lastBusId, 512);
      expect(result.notifications, hasLength(2));
      expect(result.notifications.first.type, 'discuss.channel/new_message');
      expect(result.notifications.first.payloadMap['id'], 21);
      expect(result.notifications.last.payloadMap['id'], 33);
    });
  });

  group('htmlToPlainText', () {
    test('теги, сущности и переводы строк', () {
      expect(htmlToPlainText('<p>Привет</p>'), 'Привет');
      expect(htmlToPlainText('<p>a</p><p>b</p>'), 'a\nb');
      expect(htmlToPlainText('a<br/>b<br>c'), 'a\nb\nc');
      expect(htmlToPlainText('x &amp;&nbsp;&lt;tag&gt; &#39;q&#x27;'),
          "x & <tag> 'q'");
      expect(htmlToPlainText('<div>a</div>\n\n\n\n<div>b</div>'),
          isNot(contains('\n\n\n')));
      expect(htmlToPlainText(null), '');
      expect(htmlToPlainText(''), '');
    });
  });
}
