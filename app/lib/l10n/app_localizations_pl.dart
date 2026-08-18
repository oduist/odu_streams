// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Polish (`pl`).
class AppLocalizationsPl extends AppLocalizations {
  AppLocalizationsPl([String locale = 'pl']) : super(locale);

  @override
  String get appTitle => 'Streams';

  @override
  String get loginTitle => 'Logowanie';

  @override
  String get serverUrlLabel => 'Adres serwera';

  @override
  String get loginLabel => 'Login';

  @override
  String get passwordLabel => 'Hasło';

  @override
  String get totpLabel => 'Kod uwierzytelniania';

  @override
  String get totpHelp =>
      'Włączone jest uwierzytelnianie dwuskładnikowe. Wpisz kod z aplikacji uwierzytelniającej.';

  @override
  String get signInButton => 'Zaloguj się';

  @override
  String get fieldRequired => 'Pole wymagane';

  @override
  String get errInvalidCredentials => 'Nieprawidłowy login lub hasło';

  @override
  String get errTotpInvalid => 'Nieprawidłowy kod uwierzytelniania';

  @override
  String get errNetwork => 'Błąd sieci. Sprawdź adres serwera i połączenie.';

  @override
  String get errAccessDenied => 'Brak dostępu';

  @override
  String errServer(String message) {
    return 'Błąd serwera: $message';
  }

  @override
  String get sessionExpired => 'Sesja wygasła, zaloguj się ponownie';

  @override
  String get channelsSearchHint => 'Filtruj po nazwie';

  @override
  String get sectionNotifications => 'Powiadomienia';

  @override
  String get sectionChanges => 'Zmiany';

  @override
  String get sectionMessages => 'Wiadomości';

  @override
  String get sectionChats => 'Kanały';

  @override
  String get noChannels => 'Brak kanałów';

  @override
  String membersCount(int count) {
    return 'Uczestników: $count';
  }

  @override
  String get filterComments => 'Komentarze';

  @override
  String get filterNotes => 'Notatki';

  @override
  String get filterCustomers => 'Klienci';

  @override
  String get filterChanges => 'Zmiany';

  @override
  String get filterActivities => 'Aktywności';

  @override
  String get composerHint => 'Wiadomość…';

  @override
  String get kindComment => 'Komentarz';

  @override
  String get kindNote => 'Notatka';

  @override
  String get noMessages => 'Brak wiadomości';

  @override
  String get activityLabel => 'Aktywność';

  @override
  String get changesTitle => 'Zmiany';

  @override
  String get noChanges => 'Brak zmian pól';

  @override
  String get loadMore => 'Załaduj więcej';

  @override
  String get notifyTitle => 'Powiadomienia';

  @override
  String get tabReceived => 'Otrzymane';

  @override
  String get tabSent => 'Wysłane';

  @override
  String get noNotifications => 'Brak powiadomień';

  @override
  String get newNotifyTitle => 'Nowe powiadomienie';

  @override
  String get notifyBodyHint => 'Treść powiadomienia';

  @override
  String get recipientsLabel => 'Odbiorcy';

  @override
  String get recipientsEmpty => 'Wybierz co najmniej jednego odbiorcę';

  @override
  String get recipientsManualLabel => 'Dodatkowe ID użytkowników';

  @override
  String get recipientsManualHint => 'ID użytkowników po przecinku';

  @override
  String get stickyLabel => 'Przypięte (sticky)';

  @override
  String get stickyHelp =>
      'Okienko pozostaje na ekranie, dopóki odbiorca go nie zamknie';

  @override
  String get timeoutLabel => 'Limit czasu, sekundy';

  @override
  String get sendButton => 'Wyślij';

  @override
  String get sentOk => 'Wysłano';

  @override
  String get cancelButton => 'Anuluj';

  @override
  String get replyButton => 'Odpowiedz';

  @override
  String get replyTitle => 'Odpowiedź';

  @override
  String readAt(String time) {
    return 'przeczytano $time';
  }

  @override
  String get unreadLabel => 'nieprzeczytane';

  @override
  String voiceMessage(int duration) {
    return 'Wiadomość głosowa, $duration s';
  }

  @override
  String get settingsTitle => 'Ustawienia';

  @override
  String get serverLabel => 'Serwer';

  @override
  String get userLabel => 'Użytkownik';

  @override
  String get versionLabel => 'Wersja aplikacji';

  @override
  String get logoutButton => 'Wyloguj się';

  @override
  String get logoutConfirm =>
      'Wylogować się i unieważnić token tego urządzenia?';

  @override
  String get okButton => 'OK';

  @override
  String get closeButton => 'Zamknij';

  @override
  String get retryButton => 'Ponów';

  @override
  String stickyCounter(int index, int total) {
    return '$index z $total';
  }
}
