/// Widget-тест экрана логина: валидация пустых полей, дефолтный URL,
/// появление TOTP-поля после totp_required.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:streams_app/api/client.dart';
import 'package:streams_app/l10n/app_localizations.dart';
import 'package:streams_app/screens/login_screen.dart';
import 'package:streams_app/state/session.dart';

Widget _wrap(SessionState session) => ChangeNotifierProvider.value(
      value: session,
      child: const MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: LoginScreen(),
      ),
    );

void main() {
  testWidgets('пустые поля не проходят валидацию', (tester) async {
    await tester.pumpWidget(_wrap(SessionState()));
    await tester.pumpAndSettle();

    // URL предзаполнен дефолтным сервером
    expect(find.text(kDefaultServerUrl), findsOneWidget);
    // TOTP-поле скрыто до ошибки totp_required
    expect(find.text('Authentication code'), findsNothing);

    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();

    // логин и пароль пустые → две ошибки, сетевых запросов не было
    expect(find.text('Required field'), findsNWidgets(2));
  });

  testWidgets('totp_required показывает поле кода', (tester) async {
    final session = SessionState(
      clientFactory: (baseUrl, token) => ApiClient(
        baseUrl: baseUrl,
        token: token,
        httpClient: MockClient((request) async => http.Response(
              '{"jsonrpc":"2.0","id":1,"result":'
              '{"error":{"code":"totp_required","message":"2FA"}}}',
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            )),
      ),
    );
    await tester.pumpWidget(_wrap(session));
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextFormField, 'Login'), 'alice');
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Password'), 'secret');
    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();

    expect(find.text('Authentication code'), findsOneWidget);
  });
}
