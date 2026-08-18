/// Упрощённое превращение HTML-тел сообщений в plain-text (MVP: без
/// пакета flutter_html — серверные тела простые, обычно `<p>…</p>`).
library;

final _reBlockBreak = RegExp(
  r'<(?:br\s*/?|/p|/div|/li|/tr|/h[1-6])\s*>',
  caseSensitive: false,
);
final _reTag = RegExp(r'<[^>]*>');
final _reDecEntity = RegExp(r'&#(\d+);');
final _reHexEntity = RegExp(r'&#x([0-9a-fA-F]+);');
final _reBlankLines = RegExp(r'\n{3,}');

const _namedEntities = <String, String>{
  '&nbsp;': ' ',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&apos;': "'",
  '&#39;': "'",
};

/// Убирает теги, переводит блочные разрывы в `\n`, декодирует частые
/// HTML-сущности. `&amp;` декодируется последним, чтобы не породить
/// ложные сущности из уже декодированного текста.
String htmlToPlainText(String? html) {
  if (html == null || html.isEmpty) {
    return '';
  }
  var text = html
      .replaceAll(_reBlockBreak, '\n')
      .replaceAll(_reTag, '');
  _namedEntities.forEach((entity, char) {
    text = text.replaceAll(entity, char);
  });
  text = text.replaceAllMapped(
    _reDecEntity,
    (m) => String.fromCharCode(int.parse(m.group(1)!)),
  );
  text = text.replaceAllMapped(
    _reHexEntity,
    (m) => String.fromCharCode(int.parse(m.group(1)!, radix: 16)),
  );
  text = text.replaceAll('&amp;', '&');
  return text.replaceAll(_reBlankLines, '\n\n').trim();
}
