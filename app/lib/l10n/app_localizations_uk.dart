// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Ukrainian (`uk`).
class AppLocalizationsUk extends AppLocalizations {
  AppLocalizationsUk([String locale = 'uk']) : super(locale);

  @override
  String get appTitle => 'Streams';

  @override
  String get loginTitle => 'Вхід';

  @override
  String get serverUrlLabel => 'Адреса сервера';

  @override
  String get loginLabel => 'Логін';

  @override
  String get passwordLabel => 'Пароль';

  @override
  String get totpLabel => 'Код автентифікації';

  @override
  String get totpHelp =>
      'Увімкнено двофакторну автентифікацію. Введіть код із застосунку-автентифікатора.';

  @override
  String get signInButton => 'Увійти';

  @override
  String get fieldRequired => 'Обов\'язкове поле';

  @override
  String get errInvalidCredentials => 'Невірний логін або пароль';

  @override
  String get errTotpInvalid => 'Невірний код автентифікації';

  @override
  String get errNetwork =>
      'Помилка мережі. Перевірте адресу сервера та з\'єднання.';

  @override
  String get errAccessDenied => 'Доступ заборонено';

  @override
  String errServer(String message) {
    return 'Помилка сервера: $message';
  }

  @override
  String get sessionExpired => 'Сесія завершилася, увійдіть знову';

  @override
  String get channelsSearchHint => 'Фільтр за назвою';

  @override
  String get sectionNotifications => 'Сповіщення';

  @override
  String get sectionChanges => 'Зміни';

  @override
  String get sectionMessages => 'Повідомлення';

  @override
  String get sectionChats => 'Канали';

  @override
  String get noChannels => 'Немає каналів';

  @override
  String membersCount(int count) {
    return 'Учасників: $count';
  }

  @override
  String get filterComments => 'Коментарі';

  @override
  String get filterNotes => 'Нотатки';

  @override
  String get filterCustomers => 'Клієнти';

  @override
  String get filterChanges => 'Зміни';

  @override
  String get filterActivities => 'Активності';

  @override
  String get composerHint => 'Повідомлення…';

  @override
  String get kindComment => 'Коментар';

  @override
  String get kindNote => 'Нотатка';

  @override
  String get noMessages => 'Повідомлень поки немає';

  @override
  String get activityLabel => 'Активність';

  @override
  String get changesTitle => 'Зміни';

  @override
  String get noChanges => 'Змін полів поки немає';

  @override
  String get loadMore => 'Завантажити ще';

  @override
  String get notifyTitle => 'Сповіщення';

  @override
  String get tabReceived => 'Отримані';

  @override
  String get tabSent => 'Надіслані';

  @override
  String get noNotifications => 'Сповіщень немає';

  @override
  String get newNotifyTitle => 'Нове сповіщення';

  @override
  String get notifyBodyHint => 'Текст сповіщення';

  @override
  String get recipientsLabel => 'Отримувачі';

  @override
  String get recipientsEmpty => 'Оберіть хоча б одного отримувача';

  @override
  String get recipientsManualLabel => 'Додаткові ID користувачів';

  @override
  String get recipientsManualHint => 'ID користувачів через кому';

  @override
  String get stickyLabel => 'Закріплене (sticky)';

  @override
  String get stickyHelp =>
      'Попап висить на екрані, доки отримувач його не закриє';

  @override
  String get timeoutLabel => 'Таймаут, секунд';

  @override
  String get sendButton => 'Надіслати';

  @override
  String get sentOk => 'Надіслано';

  @override
  String get cancelButton => 'Скасувати';

  @override
  String get replyButton => 'Відповісти';

  @override
  String get replyTitle => 'Відповідь';

  @override
  String readAt(String time) {
    return 'прочитано $time';
  }

  @override
  String get unreadLabel => 'не прочитано';

  @override
  String voiceMessage(int duration) {
    return 'Голосове повідомлення, $duration с';
  }

  @override
  String get settingsTitle => 'Налаштування';

  @override
  String get serverLabel => 'Сервер';

  @override
  String get userLabel => 'Користувач';

  @override
  String get versionLabel => 'Версія застосунку';

  @override
  String get logoutButton => 'Вийти';

  @override
  String get logoutConfirm => 'Вийти та відкликати токен цього пристрою?';

  @override
  String get okButton => 'ОК';

  @override
  String get closeButton => 'Закрити';

  @override
  String get retryButton => 'Повторити';

  @override
  String stickyCounter(int index, int total) {
    return '$index з $total';
  }
}
