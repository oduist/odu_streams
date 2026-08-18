/// Список каналов с секциями по kind: Notifications, Changes,
/// Messages (record-каналы), обычные каналы/DM. Быстрый фильтр по имени —
/// локальный, по уже загруженному списку.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../l10n/app_localizations.dart';
import '../state/app_state.dart';
import '../state/session.dart';
import '../util/html_text.dart';
import '../widgets/common.dart';
import 'changes_screen.dart';
import 'channel_screen.dart';
import 'notify_screen.dart';
import 'settings_screen.dart';

class ChannelsScreen extends StatefulWidget {
  const ChannelsScreen({super.key});

  @override
  State<ChannelsScreen> createState() => _ChannelsScreenState();
}

class _ChannelsScreenState extends State<ChannelsScreen> {
  List<Channel> _channels = [];
  bool _loading = true;
  String? _error;
  String _search = '';
  int _seenRevision = -1;
  AppState? _appState;

  @override
  void initState() {
    super.initState();
    _appState = context.read<AppState>();
    _seenRevision = _appState!.channelsRevision;
    _appState!.addListener(_onAppState);
    _load();
  }

  @override
  void dispose() {
    _appState?.removeListener(_onAppState);
    super.dispose();
  }

  void _onAppState() {
    final appState = _appState;
    if (appState == null || !mounted) return;
    if (appState.channelsRevision != _seenRevision) {
      _seenRevision = appState.channelsRevision;
      _load(silent: true);
    }
  }

  Future<void> _load({bool silent = false}) async {
    final session = context.read<SessionState>();
    if (!session.isLoggedIn) return;
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final channels = await session.api.channels(limit: 100);
      if (!mounted) return;
      setState(() {
        _channels = channels;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (!silent) _error = apiErrorText(AppLocalizations.of(context), e);
      });
    }
  }

  List<Channel> get _filtered {
    if (_search.isEmpty) return _channels;
    final needle = _search.toLowerCase();
    return _channels
        .where((c) => c.name.toLowerCase().contains(needle))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final appState = context.watch<AppState>();
    final channels = _filtered;
    final notifications =
        channels.where((c) => c.kind == 'notifications').toList();
    final changes = channels.where((c) => c.kind == 'changes').toList();
    final records = channels.where((c) => c.kind == 'record').toList();
    final chats = channels
        .where((c) => !const {'notifications', 'changes', 'record'}
            .contains(c.kind))
        .toList();

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.appTitle),
        actions: [
          IconButton(
            tooltip: l10n.settingsTitle,
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => const SettingsScreen())),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: TextField(
              decoration: InputDecoration(
                hintText: l10n.channelsSearchHint,
                prefixIcon: const Icon(Icons.search),
                border:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                contentPadding: EdgeInsets.zero,
                isDense: true,
              ),
              onChanged: (v) => setState(() => _search = v),
            ),
          ),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? ErrorRetry(
                  message: _error!,
                  retryLabel: l10n.retryButton,
                  onRetry: _load,
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    children: [
                      // личные разделы показываются всегда: канал может
                      // ещё не существовать на сервере (создаётся лениво)
                      if (_search.isEmpty || notifications.isNotEmpty)
                        _sectionHeader(l10n.sectionNotifications),
                      if (_search.isEmpty || notifications.isNotEmpty)
                        _personalTile(
                          icon: Icons.notifications_outlined,
                          name: l10n.sectionNotifications,
                          unread: appState.notifyCounter,
                          channel: notifications.isEmpty
                              ? null
                              : notifications.first,
                          onTap: () => Navigator.of(context).push(
                              MaterialPageRoute(
                                  builder: (_) => const NotifyScreen())),
                        ),
                      if (_search.isEmpty || changes.isNotEmpty)
                        _sectionHeader(l10n.sectionChanges),
                      if (_search.isEmpty || changes.isNotEmpty)
                        _personalTile(
                          icon: Icons.track_changes_outlined,
                          name: l10n.sectionChanges,
                          unread:
                              changes.isEmpty ? 0 : changes.first.unread,
                          channel: changes.isEmpty ? null : changes.first,
                          onTap: () => Navigator.of(context).push(
                              MaterialPageRoute(
                                  builder: (_) => const ChangesScreen())),
                        ),
                      if (records.isNotEmpty)
                        _sectionHeader(l10n.sectionMessages),
                      ...records.map(_channelTile),
                      if (chats.isNotEmpty) _sectionHeader(l10n.sectionChats),
                      ...chats.map(_channelTile),
                      if (records.isEmpty && chats.isEmpty)
                        Padding(
                          padding: const EdgeInsets.all(32),
                          child: Center(child: Text(l10n.noChannels)),
                        ),
                    ],
                  ),
                ),
    );
  }

  Widget _sectionHeader(String title) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        child: Text(
          title.toUpperCase(),
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.primary,
                letterSpacing: 1.1,
              ),
        ),
      );

  Widget _personalTile({
    required IconData icon,
    required String name,
    required int unread,
    required VoidCallback onTap,
    Channel? channel,
  }) {
    final last = channel?.lastMessage;
    return ListTile(
      leading: CircleAvatar(child: Icon(icon)),
      title: Text(name),
      subtitle: last == null ? null : _lastMessagePreview(last),
      trailing: UnreadBadge(count: unread),
      onTap: onTap,
    );
  }

  Widget _channelTile(Channel channel) {
    final last = channel.lastMessage;
    return ListTile(
      leading: CircleAvatar(
        child: Icon(switch (channel.kind) {
          'record' => Icons.description_outlined,
          'chat' => Icons.person_outline,
          'group' => Icons.group_outlined,
          _ => Icons.tag,
        }),
      ),
      title: Text(channel.name, overflow: TextOverflow.ellipsis),
      subtitle: last == null ? null : _lastMessagePreview(last),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatDateTime(context, last.date),
              style: Theme.of(context).textTheme.labelSmall,
            ),
          const SizedBox(height: 4),
          UnreadBadge(count: channel.unread),
        ],
      ),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => ChannelScreen(channel: channel))),
    );
  }

  Widget _lastMessagePreview(Message message) {
    final author = message.author?.name;
    final body = htmlToPlainText(message.body).replaceAll('\n', ' ');
    return Text(
      author == null || author.isEmpty ? body : '$author: $body',
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
    );
  }
}
