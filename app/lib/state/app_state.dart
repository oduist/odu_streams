/// Общее состояние клиента: счётчики, очередь попапов и «ревизии» лент.
///
/// Ревизия — монотонный счётчик; экраны слушают его изменение и сами
/// перезапрашивают данные через API (bus-payload'ы Store-формата клиент
/// не разбирает — это осознанное решение MVP).
library;

import 'package:flutter/foundation.dart';

import '../api/models.dart';

class AppState extends ChangeNotifier {
  int notifyCounter = 0;
  int defaultTimeout = 10;
  int? notificationsChannelId;

  int channelsRevision = 0;
  int changesRevision = 0;
  int notifyRevision = 0;
  int messagesRevision = 0;

  /// Канал последнего события `discuss.channel/new_message`; null — событие
  /// без адреса (`mail.record/insert`), открытый экран обновляется всегда.
  int? messagesChannelId;

  /// Очередь попапов уведомлений (host-виджет поверх Navigator).
  final List<NotifyItem> popups = [];

  void applyInit(InitResult result) {
    notifyCounter = result.notify.counter;
    defaultTimeout = result.notify.defaultTimeout;
    notificationsChannelId = result.notify.channelId;
    // накопившиеся за офлайн попапы — стеком при логине (§12.4)
    for (final item in result.notify.pending) {
      if (!popups.any((p) => p.id == item.id)) {
        popups.add(item);
      }
    }
    notifyListeners();
  }

  void setNotifyCounter(int counter) {
    if (counter == notifyCounter) return;
    notifyCounter = counter;
    notifyListeners();
  }

  void onNotifyNew(NotifyItem item, {int? counter}) {
    if (counter != null) notifyCounter = counter;
    notifyRevision++;
    if (!item.popupShown && !popups.any((p) => p.id == item.id)) {
      popups.add(item);
    }
    notifyListeners();
  }

  void onNotifyUpdate() {
    notifyRevision++;
    notifyListeners();
  }

  void removePopup(int notifyId) {
    popups.removeWhere((p) => p.id == notifyId);
    notifyListeners();
  }

  void bumpChannels() {
    channelsRevision++;
    notifyListeners();
  }

  void bumpChanges() {
    changesRevision++;
    channelsRevision++; // бейдж Changes в списке каналов
    notifyListeners();
  }

  void bumpMessages(int? channelId) {
    messagesRevision++;
    messagesChannelId = channelId;
    channelsRevision++; // сортировка/unread списка каналов
    notifyListeners();
  }

  /// Сброс при выходе, чтобы чужие данные не мигнули после перелогина.
  void reset() {
    notifyCounter = 0;
    defaultTimeout = 10;
    notificationsChannelId = null;
    popups.clear();
    channelsRevision++;
    changesRevision++;
    notifyRevision++;
    messagesRevision++;
    messagesChannelId = null;
    notifyListeners();
  }
}
