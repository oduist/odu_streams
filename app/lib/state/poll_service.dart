/// Периодический /v1/poll — замена longpolling для мобильного клиента.
///
/// Каждые 10 секунд в foreground; при уходе приложения в background таймер
/// останавливается (WidgetsBindingObserver), при возврате — немедленный
/// запрос. Неизвестные типы шины молча пропускаются (контракт v1).
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../api/client.dart';
import '../api/models.dart';
import 'app_state.dart';
import 'session.dart';

class PollService with WidgetsBindingObserver {
  static const pollInterval = Duration(seconds: 10);

  final SessionState session;
  final AppState appState;

  Timer? _timer;
  int _lastBusId = 0;
  bool _polling = false;
  bool _foreground = true;

  PollService({required this.session, required this.appState});

  void start() {
    WidgetsBinding.instance.addObserver(this);
    _timer ??= Timer.periodic(pollInterval, (_) => tick());
    tick();
  }

  void stop() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _timer = null;
    _lastBusId = 0;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.resumed:
        _foreground = true;
        tick();
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
      case AppLifecycleState.hidden:
        _foreground = false;
      case AppLifecycleState.inactive:
        // переходное состояние — poll не трогаем
        break;
    }
  }

  Future<void> tick() async {
    if (_polling || !_foreground || !session.isLoggedIn) return;
    _polling = true;
    try {
      // ровно 100 уведомлений — на сервере могли остаться ещё, повторяем
      for (var i = 0; i < 5; i++) {
        final result = await session.api.poll(_lastBusId);
        _lastBusId = result.lastBusId;
        for (final notification in result.notifications) {
          _dispatch(notification);
        }
        if (result.notifications.length < 100) break;
      }
    } on StreamsApiException catch (e) {
      if (e.isAuthFailed) {
        await session.forceLogout();
      }
      // сетевые/прочие ошибки poll молча ждут следующего тика
    } finally {
      _polling = false;
    }
  }

  void _dispatch(BusNotification notification) {
    final payload = notification.payloadMap;
    switch (notification.type) {
      case 'discuss.channel/new_message':
        appState.bumpMessages(asIntOrNull(payload['id']));
      case 'streams.notify/new':
        // payload — элемент /notify/feed + counter (серверный контракт)
        appState.onNotifyNew(
          NotifyItem.fromJson(payload),
          counter: asIntOrNull(payload['counter']),
        );
      case 'streams.notify/update':
        appState.onNotifyUpdate();
      case 'streams.notify/counter':
        appState.setNotifyCounter(asInt(payload['counter']));
      case 'streams.changes/updated':
        appState.bumpChanges();
      case 'mail.record/insert':
        // Store-payload не разбираем — обновляем открытый канал целиком
        appState.bumpMessages(null);
      default:
        break; // неизвестный тип — пропустить
    }
  }
}
