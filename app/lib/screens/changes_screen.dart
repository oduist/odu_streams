/// Лента личного канала Changes (/v1/changes/feed): изменения полей,
/// сгруппированные по записям-источникам. Прочтение — через
/// /v1/channel/mark_read собственного канала при загрузке свежей страницы.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../l10n/app_localizations.dart';
import '../state/app_state.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _pageSize = 30;

class ChangesScreen extends StatefulWidget {
  const ChangesScreen({super.key});

  @override
  State<ChangesScreen> createState() => _ChangesScreenState();
}

class _ChangesScreenState extends State<ChangesScreen> {
  final _scrollController = ScrollController();

  List<ChangesEntry> _items = [];
  int? _channelId;
  bool _loading = true;
  bool _loadingMore = false;
  bool _hasMore = true;
  String? _error;
  int _seenRevision = -1;
  int _lastReadId = 0;
  AppState? _appState;

  @override
  void initState() {
    super.initState();
    _appState = context.read<AppState>();
    _seenRevision = _appState!.changesRevision;
    _appState!.addListener(_onAppState);
    _scrollController.addListener(_onScroll);
    _load();
  }

  @override
  void dispose() {
    _appState?.removeListener(_onAppState);
    _scrollController.dispose();
    super.dispose();
  }

  void _onAppState() {
    final appState = _appState;
    if (appState == null || !mounted) return;
    if (appState.changesRevision != _seenRevision) {
      _seenRevision = appState.changesRevision;
      _load(silent: true);
    }
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    if (_scrollController.position.extentAfter < 200 &&
        _hasMore &&
        !_loadingMore &&
        !_loading) {
      _loadMore();
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
      final feed = await session.api.changesFeed(limit: _pageSize);
      if (!mounted) return;
      setState(() {
        _items = feed.items;
        _channelId = feed.channelId;
        _hasMore = feed.items.length >= _pageSize;
        _loading = false;
        _error = null;
      });
      _markRead();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (!silent) _error = apiErrorText(AppLocalizations.of(context), e);
      });
    }
  }

  Future<void> _loadMore() async {
    if (_items.isEmpty) return;
    final session = context.read<SessionState>();
    setState(() => _loadingMore = true);
    try {
      final feed = await session.api.changesFeed(
        beforeId: _items.last.lastMessageId,
        limit: _pageSize,
      );
      if (!mounted) return;
      setState(() {
        _items = [..._items, ...feed.items];
        _hasMore = feed.items.length >= _pageSize;
        _loadingMore = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  /// Просмотр ленты гасит непрочитанное личного канала Changes.
  Future<void> _markRead() async {
    final channelId = _channelId;
    if (channelId == null || _items.isEmpty) return;
    final newestId =
        _items.map((e) => e.lastMessageId).reduce(math.max);
    if (newestId <= _lastReadId) return;
    _lastReadId = newestId;
    final session = context.read<SessionState>();
    try {
      await session.api
          .channelMarkRead(channelId: channelId, lastMessageId: newestId);
      _appState?.bumpChannels();
    } catch (_) {
      _lastReadId = 0;
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.changesTitle)),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? ErrorRetry(
                  message: _error!,
                  retryLabel: l10n.retryButton,
                  onRetry: _load,
                )
              : _items.isEmpty
                  ? Center(child: Text(l10n.noChanges))
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.all(8),
                        itemCount: _items.length + (_loadingMore ? 1 : 0),
                        itemBuilder: (context, index) {
                          if (index >= _items.length) {
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
                          return _ChangesCard(entry: _items[index]);
                        },
                      ),
                    ),
    );
  }
}

class _ChangesCard extends StatelessWidget {
  final ChangesEntry entry;

  const _ChangesCard({required this.entry});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (entry.unread)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: Icon(Icons.circle, size: 10, color: colors.primary),
                  ),
                Expanded(
                  child: Text(
                    entry.recordName,
                    style: theme.textTheme.titleSmall,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  entry.resModel,
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: colors.outline),
                ),
              ],
            ),
            for (final event in entry.changes) ...[
              const SizedBox(height: 8),
              Text(
                '${event.author} · ${formatDateTime(context, event.date)}',
                style: theme.textTheme.labelSmall,
              ),
              for (final value in event.values)
                Padding(
                  padding: const EdgeInsets.only(left: 8, top: 2),
                  child: Text.rich(
                    TextSpan(children: [
                      TextSpan(
                        text: '${value.fieldDesc}: ',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(fontWeight: FontWeight.w600),
                      ),
                      TextSpan(
                        text: value.oldValue,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(decoration: TextDecoration.lineThrough),
                      ),
                      const TextSpan(text: ' → '),
                      TextSpan(
                          text: value.newValue,
                          style: theme.textTheme.bodySmall),
                    ]),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
