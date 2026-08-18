/// Мелкие общие виджеты и форматирование.
library;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../l10n/app_localizations.dart';

/// Человекочитаемый текст ошибки API для снекбаров/заглушек.
String apiErrorText(AppLocalizations l10n, Object error) {
  if (error is StreamsApiException) {
    switch (error.code) {
      case 'auth_failed':
        return l10n.sessionExpired;
      case 'access_denied':
        return l10n.errAccessDenied;
      case 'network':
        return l10n.errNetwork;
      default:
        return l10n.errServer(error.message);
    }
  }
  return l10n.errServer(error.toString());
}

/// Серверные даты — UTC; показываем локальное время: сегодня — «14:32»,
/// иначе — «18 Aug, 14:32».
String formatDateTime(BuildContext context, DateTime? date) {
  if (date == null) return '';
  final local = date.toLocal();
  final locale = Localizations.localeOf(context).toString();
  final now = DateTime.now();
  final sameDay = local.year == now.year &&
      local.month == now.month &&
      local.day == now.day;
  if (sameDay) {
    return DateFormat.Hm(locale).format(local);
  }
  return '${DateFormat.MMMd(locale).format(local)}, '
      '${DateFormat.Hm(locale).format(local)}';
}

String formatFileSize(int size) {
  if (size < 1024) return '$size B';
  if (size < 1024 * 1024) return '${(size / 1024).toStringAsFixed(1)} KB';
  return '${(size / 1024 / 1024).toStringAsFixed(1)} MB';
}

IconData attachmentIcon(String mimetype) {
  if (mimetype.startsWith('image/')) return Icons.image_outlined;
  if (mimetype.startsWith('audio/')) return Icons.audiotrack_outlined;
  if (mimetype.startsWith('video/')) return Icons.videocam_outlined;
  if (mimetype.contains('pdf')) return Icons.picture_as_pdf_outlined;
  return Icons.attach_file;
}

/// Read-only список вложений (MVP: без скачивания — download требует
/// Bearer-заголовка, которого нет у системного открывателя ссылок).
class AttachmentChips extends StatelessWidget {
  final List<Attachment> attachments;

  const AttachmentChips({super.key, required this.attachments});

  @override
  Widget build(BuildContext context) {
    if (attachments.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Wrap(
        spacing: 6,
        runSpacing: 4,
        children: [
          for (final attachment in attachments)
            Chip(
              avatar: Icon(attachmentIcon(attachment.mimetype), size: 16),
              label: Text(
                '${attachment.name} · ${formatFileSize(attachment.size)}',
                style: Theme.of(context).textTheme.labelSmall,
              ),
              visualDensity: VisualDensity.compact,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
        ],
      ),
    );
  }
}

class UnreadBadge extends StatelessWidget {
  final int count;

  const UnreadBadge({super.key, required this.count});

  @override
  Widget build(BuildContext context) {
    if (count <= 0) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: colors.primary,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        count > 99 ? '99+' : '$count',
        style: Theme.of(context)
            .textTheme
            .labelSmall
            ?.copyWith(color: colors.onPrimary),
      ),
    );
  }
}

/// Ошибка загрузки с кнопкой повтора.
class ErrorRetry extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  final String retryLabel;

  const ErrorRetry({
    super.key,
    required this.message,
    required this.onRetry,
    required this.retryLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton.tonal(onPressed: onRetry, child: Text(retryLabel)),
          ],
        ),
      ),
    );
  }
}
