/// Модели данных по контракту streams_mobile API v1
/// (addons/streams_mobile/docs/api-v1.md). Особенность Odoo-JSON:
/// «пустые» значения приходят как `false`, а не `null`, поэтому все
/// разборы идут через хелперы, трактующие false как отсутствие значения.
library;

int? asIntOrNull(dynamic value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return null; // false / null / прочий мусор
}

int asInt(dynamic value, [int fallback = 0]) => asIntOrNull(value) ?? fallback;

String? asStringOrNull(dynamic value) {
  if (value is String) return value;
  return null;
}

String asString(dynamic value, [String fallback = '']) =>
    asStringOrNull(value) ?? fallback;

bool asBool(dynamic value) => value == true;

/// Даты контракта — строки UTC `"2026-08-18 12:00:00"`.
DateTime? asDateTime(dynamic value) {
  final raw = asStringOrNull(value);
  if (raw == null || raw.isEmpty) return null;
  return DateTime.tryParse('${raw.replaceFirst(' ', 'T')}Z');
}

List<Map<String, dynamic>> asMapList(dynamic value) {
  if (value is! List) return const [];
  return value.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();
}

/// Текущий пользователь (login / init).
class UserInfo {
  final int id;
  final String name;
  final int? partnerId;

  const UserInfo({required this.id, required this.name, this.partnerId});

  factory UserInfo.fromJson(Map<String, dynamic> json) => UserInfo(
        id: asInt(json['id']),
        name: asString(json['name']),
        partnerId: asIntOrNull(json['partner_id']),
      );

  Map<String, dynamic> toJson() =>
      {'id': id, 'name': name, 'partner_id': partnerId};
}

/// Мобильное устройство, выданное логином.
class Device {
  final int id;
  final String token;

  const Device({required this.id, required this.token});
}

/// Ответ /auth/login.
class LoginResult {
  final Device device;
  final UserInfo user;
  final String serverVersion;

  const LoginResult({
    required this.device,
    required this.user,
    required this.serverVersion,
  });

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
        device: Device(
          id: asInt(json['device_id']),
          token: asString(json['token']),
        ),
        user: UserInfo.fromJson((json['user'] as Map).cast<String, dynamic>()),
        serverVersion: asString(json['server_version']),
      );
}

/// Автор сообщения/уведомления: {id, name}.
class Author {
  final int id;
  final String name;

  const Author({required this.id, required this.name});

  factory Author.fromJson(Map<String, dynamic> json) =>
      Author(id: asInt(json['id']), name: asString(json['name']));
}

class Attachment {
  final int id;
  final String name;
  final String mimetype;
  final int size;

  const Attachment({
    required this.id,
    required this.name,
    required this.mimetype,
    required this.size,
  });

  factory Attachment.fromJson(Map<String, dynamic> json) => Attachment(
        id: asInt(json['id']),
        name: asString(json['name']),
        mimetype: asString(json['mimetype']),
        size: asInt(json['size']),
      );
}

/// Значение трекинга change-сообщения: {field, label, old, new}.
class TrackingValue {
  final String field;
  final String label;
  final String oldValue;
  final String newValue;

  const TrackingValue({
    required this.field,
    required this.label,
    required this.oldValue,
    required this.newValue,
  });

  factory TrackingValue.fromJson(Map<String, dynamic> json) => TrackingValue(
        field: asString(json['field']),
        label: asString(json['label']),
        oldValue: asString(json['old']),
        newValue: asString(json['new']),
      );
}

class Reaction {
  final String content;
  final int count;
  final bool me;

  const Reaction({required this.content, required this.count, required this.me});

  factory Reaction.fromJson(Map<String, dynamic> json) => Reaction(
        content: asString(json['content']),
        count: asInt(json['count']),
        me: asBool(json['me']),
      );
}

class Message {
  final int id;
  final String body;
  final DateTime? date;

  /// comment | note | message | change | activity | null (прочее).
  final String? kind;
  final Author? author;
  final List<Attachment> attachments;

  /// Только у change-сообщений, иначе null.
  final List<TrackingValue>? tracking;
  final List<Reaction> reactions;
  final int? parentId;

  const Message({
    required this.id,
    required this.body,
    required this.date,
    required this.kind,
    required this.author,
    required this.attachments,
    required this.tracking,
    required this.reactions,
    required this.parentId,
  });

  factory Message.fromJson(Map<String, dynamic> json) => Message(
        id: asInt(json['id']),
        body: asString(json['body']),
        date: asDateTime(json['date']),
        kind: asStringOrNull(json['kind']),
        author: json['author'] is Map
            ? Author.fromJson((json['author'] as Map).cast<String, dynamic>())
            : null,
        attachments:
            asMapList(json['attachments']).map(Attachment.fromJson).toList(),
        tracking: json['tracking'] is List
            ? asMapList(json['tracking']).map(TrackingValue.fromJson).toList()
            : null,
        reactions:
            asMapList(json['reactions']).map(Reaction.fromJson).toList(),
        parentId: asIntOrNull(json['parent_id']),
      );
}

class Channel {
  final int id;
  final String name;

  /// record | changes | notifications | chat | channel | group.
  final String kind;
  final String? resModel;
  final int? resId;
  final int unread;
  final Message? lastMessage;
  final int membersCount;

  const Channel({
    required this.id,
    required this.name,
    required this.kind,
    required this.resModel,
    required this.resId,
    required this.unread,
    required this.lastMessage,
    required this.membersCount,
  });

  factory Channel.fromJson(Map<String, dynamic> json) => Channel(
        id: asInt(json['id']),
        name: asString(json['name']),
        kind: asString(json['kind']),
        resModel: asStringOrNull(json['res_model']),
        resId: asIntOrNull(json['res_id']),
        unread: asInt(json['unread']),
        lastMessage: json['last_message'] is Map
            ? Message.fromJson(
                (json['last_message'] as Map).cast<String, dynamic>())
            : null,
        membersCount: asInt(json['members_count']),
      );
}

/// Голосовое вложение уведомления.
class VoiceInfo {
  final int id;
  final String mimetype;
  final int duration;

  const VoiceInfo({
    required this.id,
    required this.mimetype,
    required this.duration,
  });

  factory VoiceInfo.fromJson(Map<String, dynamic> json) => VoiceInfo(
        id: asInt(json['id']),
        mimetype: asString(json['mimetype']),
        duration: asInt(json['duration']),
      );
}

/// Получатель в sent-ленте: {user_id, name, read_date}.
class NotifyRecipient {
  final int userId;
  final String name;
  final DateTime? readDate;

  const NotifyRecipient({
    required this.userId,
    required this.name,
    required this.readDate,
  });

  factory NotifyRecipient.fromJson(Map<String, dynamic> json) =>
      NotifyRecipient(
        userId: asInt(json['user_id']),
        name: asString(json['name']),
        readDate: asDateTime(json['read_date']),
      );
}

class NotifyItem {
  final int id;
  final DateTime? date;
  final Author? author;
  final String body;
  final bool isSticky;
  final int? timeout;
  final String? resModel;
  final int? resId;
  final String? recordName;
  final List<Attachment> attachments;
  final VoiceInfo? voice;
  final String? transcript;
  final String transcriptState;
  final int? parentId;

  // Поля received-ленты.
  final DateTime? readDate;
  final bool popupShown;

  // Поле sent-ленты.
  final List<NotifyRecipient>? recipients;

  const NotifyItem({
    required this.id,
    required this.date,
    required this.author,
    required this.body,
    required this.isSticky,
    required this.timeout,
    required this.resModel,
    required this.resId,
    required this.recordName,
    required this.attachments,
    required this.voice,
    required this.transcript,
    required this.transcriptState,
    required this.parentId,
    required this.readDate,
    required this.popupShown,
    required this.recipients,
  });

  factory NotifyItem.fromJson(Map<String, dynamic> json) => NotifyItem(
        id: asInt(json['id']),
        date: asDateTime(json['date']),
        author: json['author'] is Map
            ? Author.fromJson((json['author'] as Map).cast<String, dynamic>())
            : null,
        body: asString(json['body']),
        isSticky: asBool(json['is_sticky']),
        timeout: asIntOrNull(json['timeout']),
        resModel: asStringOrNull(json['res_model']),
        resId: asIntOrNull(json['res_id']),
        recordName: asStringOrNull(json['record_name']),
        attachments:
            asMapList(json['attachments']).map(Attachment.fromJson).toList(),
        voice: json['voice'] is Map
            ? VoiceInfo.fromJson((json['voice'] as Map).cast<String, dynamic>())
            : null,
        transcript: asStringOrNull(json['transcript']),
        transcriptState: asString(json['transcript_state'], 'none'),
        parentId: asIntOrNull(json['parent_id']),
        readDate: asDateTime(json['read_date']),
        popupShown: asBool(json['popup_shown']),
        recipients: json['recipients'] is List
            ? asMapList(json['recipients'])
                .map(NotifyRecipient.fromJson)
                .toList()
            : null,
      );

  NotifyItem copyWith({DateTime? readDate}) => NotifyItem(
        id: id,
        date: date,
        author: author,
        body: body,
        isSticky: isSticky,
        timeout: timeout,
        resModel: resModel,
        resId: resId,
        recordName: recordName,
        attachments: attachments,
        voice: voice,
        transcript: transcript,
        transcriptState: transcriptState,
        parentId: parentId,
        readDate: readDate ?? this.readDate,
        popupShown: popupShown,
        recipients: recipients,
      );
}

/// Одно значение из ленты Changes.
class ChangeValue {
  final int fieldId;
  final String fieldName;
  final String fieldDesc;
  final String oldValue;
  final String newValue;

  const ChangeValue({
    required this.fieldId,
    required this.fieldName,
    required this.fieldDesc,
    required this.oldValue,
    required this.newValue,
  });

  factory ChangeValue.fromJson(Map<String, dynamic> json) => ChangeValue(
        fieldId: asInt(json['field_id']),
        fieldName: asString(json['field_name']),
        fieldDesc: asString(json['field_desc']),
        oldValue: asString(json['old']),
        newValue: asString(json['new']),
      );
}

/// Одно change-сообщение внутри группы записи.
class ChangeEvent {
  final int messageId;
  final DateTime? date;
  final String author;
  final int? authorId;
  final List<ChangeValue> values;

  const ChangeEvent({
    required this.messageId,
    required this.date,
    required this.author,
    required this.authorId,
    required this.values,
  });

  factory ChangeEvent.fromJson(Map<String, dynamic> json) => ChangeEvent(
        messageId: asInt(json['message_id']),
        date: asDateTime(json['date']),
        author: asString(json['author']),
        authorId: asIntOrNull(json['author_id']),
        values: asMapList(json['values']).map(ChangeValue.fromJson).toList(),
      );
}

/// Элемент ленты Changes — группа изменений одной записи.
class ChangesEntry {
  final String resModel;
  final int resId;
  final String recordName;
  final int lastMessageId;
  final bool unread;
  final List<ChangeEvent> changes;

  const ChangesEntry({
    required this.resModel,
    required this.resId,
    required this.recordName,
    required this.lastMessageId,
    required this.unread,
    required this.changes,
  });

  factory ChangesEntry.fromJson(Map<String, dynamic> json) => ChangesEntry(
        resModel: asString(json['res_model']),
        resId: asInt(json['res_id']),
        recordName: asString(json['record_name']),
        lastMessageId: asInt(json['last_message_id']),
        unread: asBool(json['unread']),
        changes: asMapList(json['changes']).map(ChangeEvent.fromJson).toList(),
      );
}

class ChangesFeed {
  final int? channelId;
  final List<ChangesEntry> items;

  const ChangesFeed({required this.channelId, required this.items});

  factory ChangesFeed.fromJson(Map<String, dynamic> json) => ChangesFeed(
        channelId: asIntOrNull(json['channel_id']),
        items: asMapList(json['items']).map(ChangesEntry.fromJson).toList(),
      );
}

/// Блок notify из /init (payload `_streams_init_messaging`).
class NotifyInit {
  final int counter;
  final int? channelId;
  final int defaultTimeout;
  final List<NotifyItem> pending;

  const NotifyInit({
    required this.counter,
    required this.channelId,
    required this.defaultTimeout,
    required this.pending,
  });

  factory NotifyInit.fromJson(Map<String, dynamic> json) => NotifyInit(
        counter: asInt(json['counter']),
        channelId: asIntOrNull(json['channel_id']),
        defaultTimeout: asInt(json['default_timeout'], 10),
        pending: asMapList(json['pending']).map(NotifyItem.fromJson).toList(),
      );
}

class InitResult {
  final UserInfo user;
  final NotifyInit notify;
  final int unreadTotal;
  final Map<String, bool> filtersDefaults;
  final DateTime? serverTime;

  const InitResult({
    required this.user,
    required this.notify,
    required this.unreadTotal,
    required this.filtersDefaults,
    required this.serverTime,
  });

  factory InitResult.fromJson(Map<String, dynamic> json) => InitResult(
        user: UserInfo.fromJson((json['user'] as Map).cast<String, dynamic>()),
        notify: NotifyInit.fromJson(
            (json['notify'] as Map).cast<String, dynamic>()),
        unreadTotal: asInt(json['unread_total']),
        filtersDefaults: json['filters_defaults'] is Map
            ? (json['filters_defaults'] as Map)
                .map((k, v) => MapEntry(k.toString(), v == true))
            : const {},
        serverTime: asDateTime(json['server_time']),
      );
}

/// Уведомление шины из /poll.
class BusNotification {
  final int id;
  final String type;
  final dynamic payload;

  const BusNotification({
    required this.id,
    required this.type,
    required this.payload,
  });

  factory BusNotification.fromJson(Map<String, dynamic> json) =>
      BusNotification(
        id: asInt(json['id']),
        type: asString(json['type']),
        payload: json['payload'],
      );

  Map<String, dynamic> get payloadMap =>
      payload is Map ? (payload as Map).cast<String, dynamic>() : const {};
}

class PollResult {
  final int lastBusId;
  final List<BusNotification> notifications;

  const PollResult({required this.lastBusId, required this.notifications});

  factory PollResult.fromJson(Map<String, dynamic> json) => PollResult(
        lastBusId: asInt(json['last_bus_id']),
        notifications: asMapList(json['notifications'])
            .map(BusNotification.fromJson)
            .toList(),
      );
}
