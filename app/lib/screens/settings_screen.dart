/// Настройки: сервер, текущий пользователь, версия, выход.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/app_localizations.dart';
import '../state/session.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  Future<void> _logout(BuildContext context) async {
    final l10n = AppLocalizations.of(context);
    final session = context.read<SessionState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(l10n.logoutConfirm),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.cancelButton),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(l10n.logoutButton),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    // до logout: root-гейт заменит стек экранов сам после notify
    Navigator.of(context).popUntil((route) => route.isFirst);
    await session.logout();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final session = context.watch<SessionState>();
    final user = session.user;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.settingsTitle)),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: Text(l10n.serverLabel),
            subtitle: Text(session.serverUrl),
          ),
          if (user != null)
            ListTile(
              leading: const Icon(Icons.person_outline),
              title: Text(l10n.userLabel),
              subtitle: Text('${user.name} (#${user.id})'),
            ),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: Text(l10n.versionLabel),
            subtitle: const Text(kAppVersion),
          ),
          const Divider(),
          ListTile(
            leading: Icon(Icons.logout,
                color: Theme.of(context).colorScheme.error),
            title: Text(
              l10n.logoutButton,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
            onTap: () => _logout(context),
          ),
        ],
      ),
    );
  }
}
