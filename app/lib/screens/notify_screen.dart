/// Уведомления (§12): вкладки Received/Sent, отправка новых, ответы.
/// Прочтение — когда элемент показан на экране (построение тайла в ленте),
/// пачкой с дебаунсом, как «проскроллил на экране» из ТЗ.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../l10n/app_localizations.dart';
import '../state/app_state.dart';
import '../state/session.dart';
import '../util/html_text.dart';
import '../widgets/common.dart';

const _pageSize = 30;

class NotifyScreen extends StatefulWidget {
  const NotifyScreen({super.key});

  @override
  State<NotifyScreen> createState() => _NotifyScreenState();
}

class _NotifyScreenState extends State<NotifyScreen> {
  List<NotifyItem> _received = [];
  List<NotifyItem> _sent = [];
  bool _loadingReceived = true;
  bool _loadingSent = true;
  String? _error;

  final Set<int> _pendingRead = {};
  Timer? _readDebounce;
  int _seenRevision = -1;
  AppState? _appState;

  @override
  void initState() {
    super.initState();
    _appState = context.read<AppState>();
    _seenRevision = _appState!.notifyRevision;
    _appState!.addListener(_onAppState);
    _load();
  }

  @override
  void dispose() {
    _appState?.removeListener(_onAppState);
    _readDebounce?.cancel();
    super.dispose();
  }

  void _onAppState() {
    final appState = _appState;
    if (appState == null || !mounted) return;
    if (appState.notifyRevision != _seenRevision) {
      _seenRevision = appState.notifyRevision;
      _load(silent: true);
    }
  }

  Future<void> _load({bool silent = false}) async {
    final session = context.read<SessionState>();
    if (!session.isLoggedIn) return;
    if (!silent) {
      setState(() {
        _loadingReceived = true;
        _loadingSent = true;
        _error = null;
      });
    }
    try {
      final results = await Future.wait([
        session.api.notifyFeed(box: 'received', limit: _pageSize),
        session.api.notifyFeed(box: 'sent', limit: _pageSize),
      ]);
      if (!mounted) return;
      setState(() {
        _received = results[0];
        _sent = results[1];
        _loadingReceived = false;
        _loadingSent = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingReceived = false;
        _loadingSent = false;
        if (!silent) _error = apiErrorText(AppLocalizations.of(context), e);
      });
    }
  }

  /// Известные пользователи для выбора получателей: авторы полученных и
  /// получатели отправленных (в v1 нет справочника пользователей).
  Map<int, String> get _knownUsers {
    final users = <int, String>{};
    for (final item in _received) {
      final author = item.author;
      if (author != null) users[author.id] = author.name;
    }
    for (final item in _sent) {
      for (final recipient in item.recipients ?? const <NotifyRecipient>[]) {
        users[recipient.userId] = recipient.name;
      }
    }
    final myId = context.read<SessionState>().user?.id;
    users.remove(myId);
    return users;
  }

  /// Тайл построен — значит элемент был показан на экране.
  void _onSeen(NotifyItem item) {
    if (item.readDate != null || _pendingRead.contains(item.id)) return;
    _pendingRead.add(item.id);
    _readDebounce?.cancel();
    _readDebounce = Timer(const Duration(milliseconds: 600), _flushRead);
  }

  Future<void> _flushRead() async {
    if (_pendingRead.isEmpty || !mounted) return;
    final ids = _pendingRead.toList();
    final session = context.read<SessionState>();
    try {
      final counter = await session.api.notifyMarkRead(ids);
      if (!mounted) return;
      _appState?.setNotifyCounter(counter);
      setState(() {
        _received = [
          for (final item in _received)
            ids.contains(item.id) && item.readDate == null
                ? item.copyWith(readDate: DateTime.now().toUtc())
                : item,
        ];
      });
    } catch (_) {
      _pendingRead.removeWhere(ids.contains); // повторим при новом показе
    }
  }

  Future<void> _reply(NotifyItem parent) async {
    final l10n = AppLocalizations.of(context);
    final controller = TextEditingController();
    final body = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l10n.replyTitle),
        content: TextField(
          controller: controller,
          autofocus: true,
          minLines: 2,
          maxLines: 5,
          decoration: InputDecoration(
            hintText: l10n.notifyBodyHint,
            border: const OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(l10n.cancelButton),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.of(context).pop(controller.text.trim()),
            child: Text(l10n.sendButton),
          ),
        ],
      ),
    );
    controller.dispose();
    if (body == null || body.isEmpty || !mounted) return;
    final session = context.read<SessionState>();
    try {
      // sticky/timeout не передаём — наследуются от родителя (контракт)
      await session.api.notifyReply(parentId: parent.id, body: body);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(l10n.sentOk)));
      _load(silent: true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorText(l10n, e))));
    }
  }

  Future<void> _openSendSheet() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _NotifySendSheet(knownUsers: _knownUsers),
    );
    if (sent == true && mounted) {
      final l10n = AppLocalizations.of(context);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(l10n.sentOk)));
      _load(silent: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l10n.notifyTitle),
          bottom: TabBar(tabs: [
            Tab(text: l10n.tabReceived),
            Tab(text: l10n.tabSent),
          ]),
        ),
        floatingActionButton: FloatingActionButton(
          onPressed: _openSendSheet,
          tooltip: l10n.newNotifyTitle,
          child: const Icon(Icons.add_comment_outlined),
        ),
        body: TabBarView(
          children: [
            _feedList(l10n, _received, _loadingReceived, received: true),
            _feedList(l10n, _sent, _loadingSent, received: false),
          ],
        ),
      ),
    );
  }

  Widget _feedList(
    AppLocalizations l10n,
    List<NotifyItem> items,
    bool loading, {
    required bool received,
  }) {
    if (loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return ErrorRetry(
        message: _error!,
        retryLabel: l10n.retryButton,
        onRetry: _load,
      );
    }
    if (items.isEmpty) return Center(child: Text(l10n.noNotifications));
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        padding: const EdgeInsets.all(8),
        itemCount: items.length,
        itemBuilder: (context, index) {
          final item = items[index];
          if (received) {
            // построение тайла ≈ показ на экране → отметка прочтения
            WidgetsBinding.instance
                .addPostFrameCallback((_) => _onSeen(item));
          }
          return _NotifyTile(
            item: item,
            received: received,
            onReply: received ? () => _reply(item) : null,
          );
        },
      ),
    );
  }
}

class _NotifyTile extends StatelessWidget {
  final NotifyItem item;
  final bool received;
  final VoidCallback? onReply;

  const _NotifyTile({required this.item, required this.received, this.onReply});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final unread = received && item.readDate == null;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      color: unread ? colors.primaryContainer.withValues(alpha: 0.25) : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (item.isSticky)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child:
                        Icon(Icons.push_pin, size: 14, color: colors.primary),
                  ),
                Expanded(
                  child: Text(
                    received
                        ? (item.author?.name ?? '')
                        : (item.recipients ?? [])
                            .map((r) => r.name)
                            .join(', '),
                    style: theme.textTheme.titleSmall,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  formatDateTime(context, item.date),
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(htmlToPlainText(item.body)),
            if (item.voice != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Row(
                  children: [
                    Icon(Icons.mic, size: 16, color: colors.primary),
                    const SizedBox(width: 4),
                    Text(
                      l10n.voiceMessage(item.voice!.duration),
                      style: theme.textTheme.labelMedium,
                    ),
                  ],
                ),
              ),
            if (item.transcript != null && item.transcript!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  item.transcript!,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(fontStyle: FontStyle.italic),
                ),
              ),
            if (item.recordName != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  item.recordName!,
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: colors.outline),
                ),
              ),
            AttachmentChips(attachments: item.attachments),
            if (!received && item.recipients != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // статус прочтения по каждому получателю (§12.5)
                    for (final recipient in item.recipients!)
                      Text(
                        recipient.readDate != null
                            ? '${recipient.name} — ${l10n.readAt(formatDateTime(context, recipient.readDate))}'
                            : '${recipient.name} — ${l10n.unreadLabel}',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: recipient.readDate != null
                              ? colors.primary
                              : colors.outline,
                        ),
                      ),
                  ],
                ),
              ),
            if (onReply != null)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: onReply,
                  icon: const Icon(Icons.reply, size: 16),
                  label: Text(l10n.replyButton),
                  style: TextButton.styleFrom(
                      visualDensity: VisualDensity.compact),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Форма отправки уведомления: текст, получатели, sticky, timeout
/// (timeout виден только при выключенном sticky — §12.2).
class _NotifySendSheet extends StatefulWidget {
  final Map<int, String> knownUsers;

  const _NotifySendSheet({required this.knownUsers});

  @override
  State<_NotifySendSheet> createState() => _NotifySendSheetState();
}

class _NotifySendSheetState extends State<_NotifySendSheet> {
  final _bodyController = TextEditingController();
  final _manualIdsController = TextEditingController();
  late final TextEditingController _timeoutController;
  final Set<int> _selected = {};
  bool _sticky = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _timeoutController = TextEditingController(
        text: '${context.read<AppState>().defaultTimeout}');
  }

  @override
  void dispose() {
    _bodyController.dispose();
    _manualIdsController.dispose();
    _timeoutController.dispose();
    super.dispose();
  }

  List<int> get _userIds {
    final ids = {..._selected};
    // запасной ввод ID вручную: в v1 нет справочника пользователей
    for (final part in _manualIdsController.text.split(',')) {
      final id = int.tryParse(part.trim());
      if (id != null && id > 0) ids.add(id);
    }
    return ids.toList();
  }

  Future<void> _send() async {
    final l10n = AppLocalizations.of(context);
    final body = _bodyController.text.trim();
    if (body.isEmpty) {
      setState(() => _error = l10n.fieldRequired);
      return;
    }
    final userIds = _userIds;
    if (userIds.isEmpty) {
      setState(() => _error = l10n.recipientsEmpty);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final session = context.read<SessionState>();
    try {
      await session.api.notifySend(
        body: body,
        userIds: userIds,
        isSticky: _sticky,
        timeout: _sticky
            ? null
            : int.tryParse(_timeoutController.text.trim()),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = apiErrorText(l10n, e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(l10n.newNotifyTitle,
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(
              controller: _bodyController,
              minLines: 2,
              maxLines: 6,
              decoration: InputDecoration(
                labelText: l10n.notifyBodyHint,
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            if (widget.knownUsers.isNotEmpty) ...[
              Text(l10n.recipientsLabel,
                  style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 4),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  for (final entry in widget.knownUsers.entries)
                    FilterChip(
                      label: Text(entry.value),
                      selected: _selected.contains(entry.key),
                      onSelected: (v) => setState(() {
                        v
                            ? _selected.add(entry.key)
                            : _selected.remove(entry.key);
                      }),
                      visualDensity: VisualDensity.compact,
                    ),
                ],
              ),
              const SizedBox(height: 8),
            ],
            TextField(
              controller: _manualIdsController,
              decoration: InputDecoration(
                labelText: l10n.recipientsManualLabel,
                hintText: l10n.recipientsManualHint,
                border: const OutlineInputBorder(),
                isDense: true,
              ),
              keyboardType: TextInputType.text,
            ),
            SwitchListTile(
              value: _sticky,
              onChanged: (v) => setState(() => _sticky = v),
              title: Text(l10n.stickyLabel),
              subtitle: _sticky ? Text(l10n.stickyHelp) : null,
              contentPadding: EdgeInsets.zero,
            ),
            if (!_sticky)
              TextField(
                controller: _timeoutController,
                decoration: InputDecoration(
                  labelText: l10n.timeoutLabel,
                  border: const OutlineInputBorder(),
                  isDense: true,
                ),
                keyboardType: TextInputType.number,
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  _error!,
                  style:
                      TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : _send,
              child: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(l10n.sendButton),
            ),
          ],
        ),
      ),
    );
  }
}
