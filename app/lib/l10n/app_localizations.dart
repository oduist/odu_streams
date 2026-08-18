import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_pl.dart';
import 'app_localizations_ru.dart';
import 'app_localizations_uk.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('pl'),
    Locale('ru'),
    Locale('uk'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'Streams'**
  String get appTitle;

  /// No description provided for @loginTitle.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get loginTitle;

  /// No description provided for @serverUrlLabel.
  ///
  /// In en, this message translates to:
  /// **'Server URL'**
  String get serverUrlLabel;

  /// No description provided for @loginLabel.
  ///
  /// In en, this message translates to:
  /// **'Login'**
  String get loginLabel;

  /// No description provided for @passwordLabel.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get passwordLabel;

  /// No description provided for @totpLabel.
  ///
  /// In en, this message translates to:
  /// **'Authentication code'**
  String get totpLabel;

  /// No description provided for @totpHelp.
  ///
  /// In en, this message translates to:
  /// **'Two-factor authentication is enabled. Enter the code from your authenticator app.'**
  String get totpHelp;

  /// No description provided for @signInButton.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get signInButton;

  /// No description provided for @fieldRequired.
  ///
  /// In en, this message translates to:
  /// **'Required field'**
  String get fieldRequired;

  /// No description provided for @errInvalidCredentials.
  ///
  /// In en, this message translates to:
  /// **'Invalid login or password'**
  String get errInvalidCredentials;

  /// No description provided for @errTotpInvalid.
  ///
  /// In en, this message translates to:
  /// **'Invalid authentication code'**
  String get errTotpInvalid;

  /// No description provided for @errNetwork.
  ///
  /// In en, this message translates to:
  /// **'Network error. Check the server URL and your connection.'**
  String get errNetwork;

  /// No description provided for @errAccessDenied.
  ///
  /// In en, this message translates to:
  /// **'Access denied'**
  String get errAccessDenied;

  /// No description provided for @errServer.
  ///
  /// In en, this message translates to:
  /// **'Server error: {message}'**
  String errServer(String message);

  /// No description provided for @sessionExpired.
  ///
  /// In en, this message translates to:
  /// **'Session expired, please sign in again'**
  String get sessionExpired;

  /// No description provided for @channelsSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Filter by name'**
  String get channelsSearchHint;

  /// No description provided for @sectionNotifications.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get sectionNotifications;

  /// No description provided for @sectionChanges.
  ///
  /// In en, this message translates to:
  /// **'Changes'**
  String get sectionChanges;

  /// No description provided for @sectionMessages.
  ///
  /// In en, this message translates to:
  /// **'Messages'**
  String get sectionMessages;

  /// No description provided for @sectionChats.
  ///
  /// In en, this message translates to:
  /// **'Channels'**
  String get sectionChats;

  /// No description provided for @noChannels.
  ///
  /// In en, this message translates to:
  /// **'No channels'**
  String get noChannels;

  /// No description provided for @membersCount.
  ///
  /// In en, this message translates to:
  /// **'{count} members'**
  String membersCount(int count);

  /// No description provided for @filterComments.
  ///
  /// In en, this message translates to:
  /// **'Comments'**
  String get filterComments;

  /// No description provided for @filterNotes.
  ///
  /// In en, this message translates to:
  /// **'Notes'**
  String get filterNotes;

  /// No description provided for @filterCustomers.
  ///
  /// In en, this message translates to:
  /// **'Customers'**
  String get filterCustomers;

  /// No description provided for @filterChanges.
  ///
  /// In en, this message translates to:
  /// **'Changes'**
  String get filterChanges;

  /// No description provided for @filterActivities.
  ///
  /// In en, this message translates to:
  /// **'Activities'**
  String get filterActivities;

  /// No description provided for @composerHint.
  ///
  /// In en, this message translates to:
  /// **'Message…'**
  String get composerHint;

  /// No description provided for @kindComment.
  ///
  /// In en, this message translates to:
  /// **'Comment'**
  String get kindComment;

  /// No description provided for @kindNote.
  ///
  /// In en, this message translates to:
  /// **'Note'**
  String get kindNote;

  /// No description provided for @noMessages.
  ///
  /// In en, this message translates to:
  /// **'No messages yet'**
  String get noMessages;

  /// No description provided for @activityLabel.
  ///
  /// In en, this message translates to:
  /// **'Activity'**
  String get activityLabel;

  /// No description provided for @changesTitle.
  ///
  /// In en, this message translates to:
  /// **'Changes'**
  String get changesTitle;

  /// No description provided for @noChanges.
  ///
  /// In en, this message translates to:
  /// **'No field changes yet'**
  String get noChanges;

  /// No description provided for @loadMore.
  ///
  /// In en, this message translates to:
  /// **'Load more'**
  String get loadMore;

  /// No description provided for @notifyTitle.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get notifyTitle;

  /// No description provided for @tabReceived.
  ///
  /// In en, this message translates to:
  /// **'Received'**
  String get tabReceived;

  /// No description provided for @tabSent.
  ///
  /// In en, this message translates to:
  /// **'Sent'**
  String get tabSent;

  /// No description provided for @noNotifications.
  ///
  /// In en, this message translates to:
  /// **'No notifications'**
  String get noNotifications;

  /// No description provided for @newNotifyTitle.
  ///
  /// In en, this message translates to:
  /// **'New notification'**
  String get newNotifyTitle;

  /// No description provided for @notifyBodyHint.
  ///
  /// In en, this message translates to:
  /// **'Notification text'**
  String get notifyBodyHint;

  /// No description provided for @recipientsLabel.
  ///
  /// In en, this message translates to:
  /// **'Recipients'**
  String get recipientsLabel;

  /// No description provided for @recipientsEmpty.
  ///
  /// In en, this message translates to:
  /// **'Select at least one recipient'**
  String get recipientsEmpty;

  /// No description provided for @recipientsManualLabel.
  ///
  /// In en, this message translates to:
  /// **'Additional user IDs'**
  String get recipientsManualLabel;

  /// No description provided for @recipientsManualHint.
  ///
  /// In en, this message translates to:
  /// **'User IDs, comma-separated'**
  String get recipientsManualHint;

  /// No description provided for @stickyLabel.
  ///
  /// In en, this message translates to:
  /// **'Sticky'**
  String get stickyLabel;

  /// No description provided for @stickyHelp.
  ///
  /// In en, this message translates to:
  /// **'The popup stays on screen until the recipient closes it'**
  String get stickyHelp;

  /// No description provided for @timeoutLabel.
  ///
  /// In en, this message translates to:
  /// **'Timeout, seconds'**
  String get timeoutLabel;

  /// No description provided for @sendButton.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get sendButton;

  /// No description provided for @sentOk.
  ///
  /// In en, this message translates to:
  /// **'Sent'**
  String get sentOk;

  /// No description provided for @cancelButton.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancelButton;

  /// No description provided for @replyButton.
  ///
  /// In en, this message translates to:
  /// **'Reply'**
  String get replyButton;

  /// No description provided for @replyTitle.
  ///
  /// In en, this message translates to:
  /// **'Reply'**
  String get replyTitle;

  /// No description provided for @readAt.
  ///
  /// In en, this message translates to:
  /// **'read {time}'**
  String readAt(String time);

  /// No description provided for @unreadLabel.
  ///
  /// In en, this message translates to:
  /// **'unread'**
  String get unreadLabel;

  /// No description provided for @voiceMessage.
  ///
  /// In en, this message translates to:
  /// **'Voice message, {duration} s'**
  String voiceMessage(int duration);

  /// No description provided for @settingsTitle.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settingsTitle;

  /// No description provided for @serverLabel.
  ///
  /// In en, this message translates to:
  /// **'Server'**
  String get serverLabel;

  /// No description provided for @userLabel.
  ///
  /// In en, this message translates to:
  /// **'User'**
  String get userLabel;

  /// No description provided for @versionLabel.
  ///
  /// In en, this message translates to:
  /// **'Application version'**
  String get versionLabel;

  /// No description provided for @logoutButton.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get logoutButton;

  /// No description provided for @logoutConfirm.
  ///
  /// In en, this message translates to:
  /// **'Sign out and revoke this device token?'**
  String get logoutConfirm;

  /// No description provided for @okButton.
  ///
  /// In en, this message translates to:
  /// **'OK'**
  String get okButton;

  /// No description provided for @closeButton.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get closeButton;

  /// No description provided for @retryButton.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retryButton;

  /// No description provided for @stickyCounter.
  ///
  /// In en, this message translates to:
  /// **'{index} of {total}'**
  String stickyCounter(int index, int total);
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'pl', 'ru', 'uk'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'pl':
      return AppLocalizationsPl();
    case 'ru':
      return AppLocalizationsRu();
    case 'uk':
      return AppLocalizationsUk();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
