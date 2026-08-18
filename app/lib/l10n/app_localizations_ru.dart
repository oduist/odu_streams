// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Russian (`ru`).
class AppLocalizationsRu extends AppLocalizations {
  AppLocalizationsRu([String locale = 'ru']) : super(locale);

  @override
  String get appTitle => 'Streams';

  @override
  String get loginTitle => 'Вход';

  @override
  String get serverUrlLabel => 'Адрес сервера';

  @override
  String get loginLabel => 'Логин';

  @override
  String get passwordLabel => 'Пароль';

  @override
  String get totpLabel => 'Код аутентификации';

  @override
  String get totpHelp =>
      'Включена двухфакторная аутентификация. Введите код из приложения-аутентификатора.';

  @override
  String get signInButton => 'Войти';

  @override
  String get fieldRequired => 'Обязательное поле';

  @override
  String get errInvalidCredentials => 'Неверный логин или пароль';

  @override
  String get errTotpInvalid => 'Неверный код аутентификации';

  @override
  String get errNetwork =>
      'Ошибка сети. Проверьте адрес сервера и подключение.';

  @override
  String get errAccessDenied => 'Доступ запрещён';

  @override
  String errServer(String message) {
    return 'Ошибка сервера: $message';
  }

  @override
  String get sessionExpired => 'Сессия истекла, войдите заново';

  @override
  String get channelsSearchHint => 'Фильтр по имени';

  @override
  String get sectionNotifications => 'Уведомления';

  @override
  String get sectionChanges => 'Изменения';

  @override
  String get sectionMessages => 'Сообщения';

  @override
  String get sectionChats => 'Каналы';

  @override
  String get noChannels => 'Нет каналов';

  @override
  String membersCount(int count) {
    return 'Участников: $count';
  }

  @override
  String get filterComments => 'Комментарии';

  @override
  String get filterNotes => 'Заметки';

  @override
  String get filterCustomers => 'Клиенты';

  @override
  String get filterChanges => 'Изменения';

  @override
  String get filterActivities => 'Активности';

  @override
  String get composerHint => 'Сообщение…';

  @override
  String get kindComment => 'Комментарий';

  @override
  String get kindNote => 'Заметка';

  @override
  String get noMessages => 'Сообщений пока нет';

  @override
  String get activityLabel => 'Активность';

  @override
  String get changesTitle => 'Изменения';

  @override
  String get noChanges => 'Изменений полей пока нет';

  @override
  String get loadMore => 'Загрузить ещё';

  @override
  String get notifyTitle => 'Уведомления';

  @override
  String get tabReceived => 'Полученные';

  @override
  String get tabSent => 'Отправленные';

  @override
  String get noNotifications => 'Уведомлений нет';

  @override
  String get newNotifyTitle => 'Новое уведомление';

  @override
  String get notifyBodyHint => 'Текст уведомления';

  @override
  String get recipientsLabel => 'Получатели';

  @override
  String get recipientsEmpty => 'Выберите хотя бы одного получателя';

  @override
  String get recipientsManualLabel => 'Дополнительные ID пользователей';

  @override
  String get recipientsManualHint => 'ID пользователей через запятую';

  @override
  String get stickyLabel => 'Закреплённое (sticky)';

  @override
  String get stickyHelp =>
      'Попап висит на экране, пока получатель его не закроет';

  @override
  String get timeoutLabel => 'Таймаут, секунд';

  @override
  String get sendButton => 'Отправить';

  @override
  String get sentOk => 'Отправлено';

  @override
  String get cancelButton => 'Отмена';

  @override
  String get replyButton => 'Ответить';

  @override
  String get replyTitle => 'Ответ';

  @override
  String readAt(String time) {
    return 'прочитано $time';
  }

  @override
  String get unreadLabel => 'не прочитано';

  @override
  String voiceMessage(int duration) {
    return 'Голосовое сообщение, $duration с';
  }

  @override
  String get settingsTitle => 'Настройки';

  @override
  String get serverLabel => 'Сервер';

  @override
  String get userLabel => 'Пользователь';

  @override
  String get versionLabel => 'Версия приложения';

  @override
  String get logoutButton => 'Выйти';

  @override
  String get logoutConfirm => 'Выйти и отозвать токен этого устройства?';

  @override
  String get okButton => 'ОК';

  @override
  String get closeButton => 'Закрыть';

  @override
  String get retryButton => 'Повторить';

  @override
  String stickyCounter(int index, int total) {
    return '$index из $total';
  }
}
