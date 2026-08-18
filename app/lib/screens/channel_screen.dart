/// Лента канала: фильтры потоков (record-каналы), композер Comment/Note,
/// отметка прочтения при доскролле до свежих сообщений, рендер
/// change-сообщений «поле: было → стало», реакции read-only.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../l10n/app_localizations.dart';
import '../state/app_state.dart';
import '../state/session.dart';
import '../util/html_text.dart';
import '../widgets/common.dart';

const _pageSize = 30;

/// Порядок и ключи фильтров потоков (§6 roadmap: фильтр — настройка
/// отображения, ключи совпадают с kind сообщений).
const _filterKeys = ['comment', 'note', 'message', 'change', 'activity'];

class ChannelScreen extends StatefulWidget {
  final Channel channel;

  const ChannelScreen({super.key, required this.channel});

  @override
  State<ChannelScreen> createState() => _ChannelScreenState();
}

class _ChannelScreenState extends State<ChannelScreen> {
  final _scrollController = ScrollController();
  final _composerController = TextEditingController();

  List<Message> _messages = [];
  bool _loading = true;
  bool _loadingMore = false;
  bool _hasMore = true;
  String? _error;
  Map<String, bool>? _filters; // только record-каналы
  String _postKind = 'comment';
  bool _sending = false;
  int _lastReadId = 0;
  int _seenRevision = -1;
  AppState? _appState;

  bool get _isRecord => widget.channel.kind == 'record';

  /// Личные каналы Changes/Notifications — только чтение.
  bool get _canPost =>
      !const {'changes', 'notifications'}.contains(widget.channel.kind);

  @override
  void initState() {
    super.initState();
    _appState = context.read<AppState>();
    _seenRevision = _appState!.messagesRevision;
    _appState!.addListener(_onAppState);
    _scrollController.addListener(_onScroll);
    _load();
    if (_isRecord) _loadFilters();
  }

  @override
  void dispose() {
    _appState?.removeListener(_onAppState);
    _scrollController.dispose();
    _composerController.dispose();
    super.dispose();
  }

  void _onAppState() {
    final appState = _appState;
    if (appState == null || !mounted) return;
    if (appState.messagesRevision == _seenRevision) return;
    _seenRevision = appState.messagesRevision;
    // событие адресовано другому каналу — открытую ленту не трогаем
    final target = appState.messagesChannelId;
    if (target != null && target != widget.channel.id) return;
    _refreshLatest();
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    final position = _scrollController.position;
    // reverse-список: pixels≈0 — визуальный низ, свежие сообщения
    if (position.pixels <= 40) _markRead();
    if (position.extentAfter < 200 && _hasMore && !_loadingMore && !_loading) {
      _loadMore();
    }
  }

  Future<void> _load() async {
    final session = context.read<SessionState>();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final messages = await session.api
          .channelMessages(channelId: widget.channel.id, limit: _pageSize);
      if (!mounted) return;
      setState(() {
        _messages = messages;
        _hasMore = messages.length >= _pageSize;
        _loading = false;
      });
      // экран открыт на свежих сообщениях — сразу отмечаем прочтение
      WidgetsBinding.instance.addPostFrameCallback((_) => _markRead());
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = apiErrorText(AppLocalizations.of(context), e);
      });
    }
  }

  Future<void> _loadMore() async {
    if (_messages.isEmpty) return;
    final session = context.read<SessionState>();
    setState(() => _loadingMore = true);
    try {
      final older = await session.api.channelMessages(
        channelId: widget.channel.id,
        beforeId: _messages.last.id,
        limit: _pageSize,
      );
      if (!mounted) return;
      setState(() {
        _messages = [..._messages, ...older];
        _hasMore = older.length >= _pageSize;
        _loadingMore = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  /// Подтянуть свежую страницу после события шины: новые — в начало,
  /// пересёкшиеся — заменить (обновления тел/реакций).
  Future<void> _refreshLatest() async {
    final session = context.read<SessionState>();
    if (!session.isLoggedIn) return;
    try {
      final latest = await session.api
          .channelMessages(channelId: widget.channel.id, limit: _pageSize);
      if (!mounted) return;
      final byId = {for (final m in latest) m.id: m};
      final merged = [
        ...latest.where(
            (m) => _messages.isEmpty || m.id > _messages.first.id),
        for (final old in _messages) byId[old.id] ?? old,
      ];
      setState(() => _messages = merged);
      if (_scrollController.hasClients &&
          _scrollController.position.pixels <= 40) {
        _markRead();
      }
    } catch (_) {
      // молча: следующий poll повторит
    }
  }

  Future<void> _markRead() async {
    if (_messages.isEmpty) return;
    final newestId = _messages.first.id;
    if (newestId <= _lastReadId) return;
    _lastReadId = newestId;
    final session = context.read<SessionState>();
    try {
      await session.api.channelMarkRead(
          channelId: widget.channel.id, lastMessageId: newestId);
      _appState?.bumpChannels();
    } catch (_) {
      _lastReadId = 0; // не удалось — попробуем при следующем доскролле
    }
  }

  Future<void> _loadFilters() async {
    final session = context.read<SessionState>();
    try {
      final filters =
          await session.api.channelFilters(channelId: widget.channel.id);
      if (mounted) setState(() => _filters = filters);
    } catch (_) {
      // фильтры не критичны — лента останется без тумблеров
    }
  }

  Future<void> _toggleFilter(String key, bool value) async {
    final session = context.read<SessionState>();
    final previous = _filters;
    setState(() => _filters = {...?_filters, key: value});
    try {
      final saved = await session.api
          .channelFilters(channelId: widget.channel.id, filters: {key: value});
      if (mounted) setState(() => _filters = saved);
    } catch (_) {
      if (mounted) setState(() => _filters = previous);
    }
  }

  Future<void> _send() async {
    final body = _composerController.text.trim();
    if (body.isEmpty || _sending) return;
    final session = context.read<SessionState>();
    final l10n = AppLocalizations.of(context);
    setState(() => _sending = true);
    try {
      final message = await session.api.channelPost(
        channelId: widget.channel.id,
        body: body,
        kind: _postKind,
      );
      if (!mounted) return;
      setState(() {
        _messages = [message, ..._messages];
        _sending = false;
      });
      _composerController.clear();
      _markRead();
    } catch (e) {
      if (!mounted) return;
      setState(() => _sending = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorText(l10n, e))));
    }
  }

  String _filterLabel(AppLocalizations l10n, String key) => switch (key) {
        'comment' => l10n.filterComments,
        'note' => l10n.filterNotes,
        'message' => l10n.filterCustomers,
        'change' => l10n.filterChanges,
        _ => l10n.filterActivities,
      };

  List<Message> get _visibleMessages {
    final filters = _filters;
    if (filters == null) return _messages;
    return _messages.where((m) {
      final kind = m.kind;
      if (kind == null || !filters.containsKey(kind)) return true;
      return filters[kind] ?? true;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final messages = _visibleMessages;
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.channel.name,
                style: const TextStyle(fontSize: 17),
                overflow: TextOverflow.ellipsis),
            if (widget.channel.membersCount > 0)
              Text(
                l10n.membersCount(widget.channel.membersCount),
                style: Theme.of(context).textTheme.labelSmall,
              ),
          ],
        ),
        bottom: _isRecord && _filters != null
            ? PreferredSize(
                preferredSize: const Size.fromHeight(48),
                child: SizedBox(
                  height: 48,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    children: [
                      for (final key in _filterKeys)
                        Padding(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 4, vertical: 6),
                          child: FilterChip(
                            label: Text(_filterLabel(l10n, key)),
                            selected: _filters![key] ?? true,
                            onSelected: (v) => _toggleFilter(key, v),
                            visualDensity: VisualDensity.compact,
                          ),
                        ),
                    ],
                  ),
                ),
              )
            : null,
      ),
      body: Column(
        children: [
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? ErrorRetry(
                        message: _error!,
                        retryLabel: l10n.retryButton,
                        onRetry: _load,
                      )
                    : messages.isEmpty
                        ? Center(child: Text(l10n.noMessages))
                        : ListView.builder(
                            controller: _scrollController,
                            reverse: true,
                            padding: const EdgeInsets.symmetric(vertical: 8),
                            itemCount:
                                messages.length + (_loadingMore ? 1 : 0),
                            itemBuilder: (context, index) {
                              if (index >= messages.length) {
                                return const Padding(
                                  padding: EdgeInsets.all(12),
                                  child: Center(
                                      child: SizedBox(
                                          width: 20,
                                          height: 20,
                                          child: CircularProgressIndicator(
                                              strokeWidth: 2))),
                                );
                              }
                              return _MessageTile(message: messages[index]);
                            },
                          ),
          ),
          if (_canPost) _composer(l10n),
        ],
      ),
    );
  }

  Widget _composer(AppLocalizations l10n) {
    final isNote = _postKind == 'note';
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
        decoration: BoxDecoration(
          color: isNote
              ? colors.tertiaryContainer.withValues(alpha: 0.4)
              : colors.surface,
          border: Border(top: BorderSide(color: colors.outlineVariant)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                SegmentedButton<String>(
                  segments: [
                    ButtonSegment(
                        value: 'comment', label: Text(l10n.kindComment)),
                    ButtonSegment(value: 'note', label: Text(l10n.kindNote)),
                  ],
                  selected: {_postKind},
                  onSelectionChanged: (s) =>
                      setState(() => _postKind = s.first),
                  style: const ButtonStyle(
                      visualDensity: VisualDensity.compact),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: _composerController,
                    decoration: InputDecoration(
                      hintText: l10n.composerHint,
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24)),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 10),
                      isDense: true,
                    ),
                    minLines: 1,
                    maxLines: 5,
                    textInputAction: TextInputAction.newline,
                  ),
                ),
                const SizedBox(width: 6),
                IconButton.filled(
                  icon: _sending
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.send),
                  onPressed: _sending ? null : _send,
                  tooltip: l10n.sendButton,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MessageTile extends StatelessWidget {
  final Message message;

  const _MessageTile({required this.message});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final kind = message.kind;

    final (icon, tint) = switch (kind) {
      'note' => (Icons.sticky_note_2_outlined, colors.tertiaryContainer),
      'message' => (Icons.mail_outline, colors.secondaryContainer),
      'change' => (Icons.track_changes_outlined, null),
      'activity' => (Icons.event_note_outlined, null),
      _ => (Icons.chat_bubble_outline, null),
    };

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: tint?.withValues(alpha: 0.35) ??
              colors.surfaceContainerHighest.withValues(alpha: 0.35),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 15, color: colors.primary),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    message.author?.name ?? '',
                    style: theme.textTheme.titleSmall,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  formatDateTime(context, message.date),
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
            const SizedBox(height: 4),
            if (kind == 'change' &&
                message.tracking != null &&
                message.tracking!.isNotEmpty)
              // «поле: было → стало»
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final value in message.tracking!)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text.rich(
                        TextSpan(children: [
                          TextSpan(
                            text: '${value.label}: ',
                            style: theme.textTheme.bodySmall
                                ?.copyWith(fontWeight: FontWeight.w600),
                          ),
                          TextSpan(
                            text: value.oldValue,
                            style: theme.textTheme.bodySmall?.copyWith(
                                decoration: TextDecoration.lineThrough),
                          ),
                          const TextSpan(text: ' → '),
                          TextSpan(
                              text: value.newValue,
                              style: theme.textTheme.bodySmall),
                        ]),
                      ),
                    ),
                ],
              )
            else if (htmlToPlainText(message.body).isNotEmpty)
              Text(
                htmlToPlainText(message.body),
                style: kind == 'activity'
                    ? theme.textTheme.bodyMedium
                        ?.copyWith(fontStyle: FontStyle.italic)
                    : theme.textTheme.bodyMedium,
              )
            else if (kind == 'activity')
              Text(l10n.activityLabel,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(fontStyle: FontStyle.italic)),
            AttachmentChips(attachments: message.attachments),
            if (message.reactions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Wrap(
                  spacing: 6,
                  children: [
                    for (final reaction in message.reactions)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: reaction.me
                              ? colors.primaryContainer
                              : colors.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          '${reaction.content} ${reaction.count}',
                          style: theme.textTheme.labelSmall,
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
