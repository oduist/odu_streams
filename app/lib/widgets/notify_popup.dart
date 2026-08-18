/// In-app попапы уведомлений (§12.4): не-sticky исчезают сами по таймауту,
/// sticky складываются в стек с пейджером и закрываются вручную. Host
/// вставляется через MaterialApp.builder — поверх Navigator, то есть
/// поверх любого экрана.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../l10n/app_localizations.dart';
import '../state/app_state.dart';
import '../state/session.dart';
import '../util/html_text.dart';

class NotifyPopupHost extends StatefulWidget {
  final Widget child;

  /// Открытие экрана уведомлений по тапу (навигация — забота main.dart).
  final VoidCallback? onOpenNotifications;

  const NotifyPopupHost({super.key, required this.child, this.onOpenNotifications});

  @override
  State<NotifyPopupHost> createState() => _NotifyPopupHostState();
}

class _NotifyPopupHostState extends State<NotifyPopupHost> {
  final Map<int, Timer> _timers = {};
  final Set<int> _reportedShown = {};
  int _stickyIndex = 0;

  @override
  void dispose() {
    for (final timer in _timers.values) {
      timer.cancel();
    }
    super.dispose();
  }

  void _reportShown(BuildContext context, NotifyItem item) {
    if (_reportedShown.contains(item.id)) return;
    _reportedShown.add(item.id);
    final session = context.read<SessionState>();
    if (!session.isLoggedIn) return;
    // ошибки не критичны: попап просто всплывёт ещё раз при логине
    session.api
        .notifyPopupShown([item.id]).catchError((Object _) {});
  }

  void _scheduleTimeout(AppState appState, NotifyItem item) {
    if (_timers.containsKey(item.id)) return;
    final seconds = item.timeout ?? appState.defaultTimeout;
    _timers[item.id] = Timer(Duration(seconds: seconds), () {
      _timers.remove(item.id);
      appState.removePopup(item.id);
    });
  }

  void _close(AppState appState, NotifyItem item) {
    _timers.remove(item.id)?.cancel();
    appState.removePopup(item.id);
  }

  @override
  Widget build(BuildContext context) {
    final appState = context.watch<AppState>();
    final transient = appState.popups.where((p) => !p.isSticky).toList();
    final sticky = appState.popups.where((p) => p.isSticky).toList();
    if (_stickyIndex >= sticky.length) {
      _stickyIndex = sticky.isEmpty ? 0 : sticky.length - 1;
    }
    for (final item in transient) {
      _scheduleTimeout(appState, item);
      _reportShown(context, item);
    }
    if (sticky.isNotEmpty) {
      _reportShown(context, sticky[_stickyIndex]);
    }
    return Stack(
      textDirection: TextDirection.ltr,
      children: [
        widget.child,
        if (transient.isNotEmpty || sticky.isNotEmpty)
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // не-sticky показываются поверх стека sticky (§12.4)
                  for (final item in transient)
                    _PopupCard(
                      item: item,
                      onClose: () => _close(appState, item),
                      onTap: widget.onOpenNotifications,
                    ),
                  if (sticky.isNotEmpty)
                    _PopupCard(
                      item: sticky[_stickyIndex],
                      sticky: true,
                      stackIndex: _stickyIndex,
                      stackTotal: sticky.length,
                      onPrev: _stickyIndex > 0
                          ? () => setState(() => _stickyIndex--)
                          : null,
                      onNext: _stickyIndex < sticky.length - 1
                          ? () => setState(() => _stickyIndex++)
                          : null,
                      onClose: () => setState(() {
                        _close(appState, sticky[_stickyIndex]);
                      }),
                      onTap: widget.onOpenNotifications,
                    ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _PopupCard extends StatelessWidget {
  final NotifyItem item;
  final bool sticky;
  final int stackIndex;
  final int stackTotal;
  final VoidCallback? onClose;
  final VoidCallback? onPrev;
  final VoidCallback? onNext;
  final VoidCallback? onTap;

  const _PopupCard({
    required this.item,
    this.sticky = false,
    this.stackIndex = 0,
    this.stackTotal = 0,
    this.onClose,
    this.onPrev,
    this.onNext,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      elevation: 6,
      color: colors.inverseSurface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 4, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    sticky ? Icons.push_pin : Icons.notifications_active,
                    size: 18,
                    color: colors.onInverseSurface,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      item.author?.name ?? l10n.notifyTitle,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(color: colors.onInverseSurface),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  if (sticky && stackTotal > 1) ...[
                    IconButton(
                      icon: const Icon(Icons.chevron_left),
                      color: colors.onInverseSurface,
                      onPressed: onPrev,
                      visualDensity: VisualDensity.compact,
                    ),
                    Text(
                      l10n.stickyCounter(stackIndex + 1, stackTotal),
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: colors.onInverseSurface),
                    ),
                    IconButton(
                      icon: const Icon(Icons.chevron_right),
                      color: colors.onInverseSurface,
                      onPressed: onNext,
                      visualDensity: VisualDensity.compact,
                    ),
                  ],
                  IconButton(
                    icon: const Icon(Icons.close),
                    color: colors.onInverseSurface,
                    onPressed: onClose,
                    visualDensity: VisualDensity.compact,
                    tooltip: l10n.closeButton,
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: Text(
                  htmlToPlainText(item.body),
                  maxLines: sticky ? 8 : 4,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: colors.onInverseSurface),
                ),
              ),
              if (item.recordName != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4, right: 12),
                  child: Text(
                    item.recordName!,
                    style: theme.textTheme.labelSmall?.copyWith(
                        color: colors.onInverseSurface.withValues(alpha: 0.7)),
                  ),
                ),
              if (item.voice != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4, right: 12),
                  child: Text(
                    l10n.voiceMessage(item.voice!.duration),
                    style: theme.textTheme.labelSmall?.copyWith(
                        color: colors.onInverseSurface.withValues(alpha: 0.7)),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
