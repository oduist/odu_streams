/// Точка входа мобильного клиента Streams (фаза 7).
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api/client.dart';
import 'l10n/app_localizations.dart';
import 'screens/channels_screen.dart';
import 'screens/login_screen.dart';
import 'screens/notify_screen.dart';
import 'state/app_state.dart';
import 'state/poll_service.dart';
import 'state/session.dart';
import 'widgets/notify_popup.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const StreamsApp());
}

class StreamsApp extends StatefulWidget {
  const StreamsApp({super.key});

  @override
  State<StreamsApp> createState() => _StreamsAppState();
}

class _StreamsAppState extends State<StreamsApp> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  late final SessionState _session;
  late final AppState _appState;
  late final PollService _pollService;
  bool _wasLoggedIn = false;

  @override
  void initState() {
    super.initState();
    _session = SessionState();
    _appState = AppState();
    _pollService = PollService(session: _session, appState: _appState);
    _session.addListener(_onSessionChanged);
    _session.load();
  }

  @override
  void dispose() {
    _session.removeListener(_onSessionChanged);
    _pollService.stop();
    super.dispose();
  }

  /// Реакция на вход/выход: запуск-останов poll и стартовый /init.
  void _onSessionChanged() {
    final loggedIn = _session.isLoggedIn;
    if (loggedIn == _wasLoggedIn) return;
    _wasLoggedIn = loggedIn;
    if (loggedIn) {
      _runInit();
      _pollService.start();
    } else {
      _pollService.stop();
      _appState.reset();
      // токен умер где-то в глубине стека — возвращаемся к root-гейту
      _navigatorKey.currentState?.popUntil((route) => route.isFirst);
    }
  }

  Future<void> _runInit() async {
    try {
      final result = await _session.api.init();
      _appState.applyInit(result);
    } on StreamsApiException catch (e) {
      if (e.isAuthFailed) await _session.forceLogout();
      // прочие ошибки не фатальны: poll и экраны доберут данные
    } catch (_) {
      // сетевые сбои /init переживаем молча
    }
  }

  void _openNotifications() {
    if (!_session.isLoggedIn) return;
    _navigatorKey.currentState?.push(
        MaterialPageRoute(builder: (_) => const NotifyScreen()));
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<SessionState>.value(value: _session),
        ChangeNotifierProvider<AppState>.value(value: _appState),
        Provider<PollService>.value(value: _pollService),
      ],
      child: MaterialApp(
        navigatorKey: _navigatorKey,
        onGenerateTitle: (context) => AppLocalizations.of(context).appTitle,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        ),
        // попапы уведомлений — поверх Navigator, то есть любого экрана
        builder: (context, child) => NotifyPopupHost(
          onOpenNotifications: _openNotifications,
          child: child ?? const SizedBox.shrink(),
        ),
        home: const _RootGate(),
      ),
    );
  }
}

/// Переключение login/основной экран по состоянию сессии.
class _RootGate extends StatelessWidget {
  const _RootGate();

  @override
  Widget build(BuildContext context) {
    final session = context.watch<SessionState>();
    if (!session.loaded) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return session.isLoggedIn ? const ChannelsScreen() : const LoginScreen();
  }
}
