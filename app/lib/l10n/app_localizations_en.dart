// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Streams';

  @override
  String get loginTitle => 'Sign in';

  @override
  String get serverUrlLabel => 'Server URL';

  @override
  String get loginLabel => 'Login';

  @override
  String get passwordLabel => 'Password';

  @override
  String get totpLabel => 'Authentication code';

  @override
  String get totpHelp =>
      'Two-factor authentication is enabled. Enter the code from your authenticator app.';

  @override
  String get signInButton => 'Sign in';

  @override
  String get fieldRequired => 'Required field';

  @override
  String get errInvalidCredentials => 'Invalid login or password';

  @override
  String get errTotpInvalid => 'Invalid authentication code';

  @override
  String get errNetwork =>
      'Network error. Check the server URL and your connection.';

  @override
  String get errAccessDenied => 'Access denied';

  @override
  String errServer(String message) {
    return 'Server error: $message';
  }

  @override
  String get sessionExpired => 'Session expired, please sign in again';

  @override
  String get channelsSearchHint => 'Filter by name';

  @override
  String get sectionNotifications => 'Notifications';

  @override
  String get sectionChanges => 'Changes';

  @override
  String get sectionMessages => 'Messages';

  @override
  String get sectionChats => 'Channels';

  @override
  String get noChannels => 'No channels';

  @override
  String membersCount(int count) {
    return '$count members';
  }

  @override
  String get filterComments => 'Comments';

  @override
  String get filterNotes => 'Notes';

  @override
  String get filterCustomers => 'Customers';

  @override
  String get filterChanges => 'Changes';

  @override
  String get filterActivities => 'Activities';

  @override
  String get composerHint => 'Message…';

  @override
  String get kindComment => 'Comment';

  @override
  String get kindNote => 'Note';

  @override
  String get noMessages => 'No messages yet';

  @override
  String get activityLabel => 'Activity';

  @override
  String get changesTitle => 'Changes';

  @override
  String get noChanges => 'No field changes yet';

  @override
  String get loadMore => 'Load more';

  @override
  String get notifyTitle => 'Notifications';

  @override
  String get tabReceived => 'Received';

  @override
  String get tabSent => 'Sent';

  @override
  String get noNotifications => 'No notifications';

  @override
  String get newNotifyTitle => 'New notification';

  @override
  String get notifyBodyHint => 'Notification text';

  @override
  String get recipientsLabel => 'Recipients';

  @override
  String get recipientsEmpty => 'Select at least one recipient';

  @override
  String get recipientsManualLabel => 'Additional user IDs';

  @override
  String get recipientsManualHint => 'User IDs, comma-separated';

  @override
  String get stickyLabel => 'Sticky';

  @override
  String get stickyHelp =>
      'The popup stays on screen until the recipient closes it';

  @override
  String get timeoutLabel => 'Timeout, seconds';

  @override
  String get sendButton => 'Send';

  @override
  String get sentOk => 'Sent';

  @override
  String get cancelButton => 'Cancel';

  @override
  String get replyButton => 'Reply';

  @override
  String get replyTitle => 'Reply';

  @override
  String readAt(String time) {
    return 'read $time';
  }

  @override
  String get unreadLabel => 'unread';

  @override
  String voiceMessage(int duration) {
    return 'Voice message, $duration s';
  }

  @override
  String get settingsTitle => 'Settings';

  @override
  String get serverLabel => 'Server';

  @override
  String get userLabel => 'User';

  @override
  String get versionLabel => 'Application version';

  @override
  String get logoutButton => 'Sign out';

  @override
  String get logoutConfirm => 'Sign out and revoke this device token?';

  @override
  String get okButton => 'OK';

  @override
  String get closeButton => 'Close';

  @override
  String get retryButton => 'Retry';

  @override
  String stickyCounter(int index, int total) {
    return '$index of $total';
  }
}
