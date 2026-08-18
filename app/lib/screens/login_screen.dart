/// Экран входа: URL сервера + логин/пароль; поле TOTP появляется после
/// ошибки totp_required (2FA включён у пользователя).
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../l10n/app_localizations.dart';
import '../state/session.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _urlController;
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();
  final _totpController = TextEditingController();

  bool _showTotp = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _urlController =
        TextEditingController(text: context.read<SessionState>().serverUrl);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _loginController.dispose();
    _passwordController.dispose();
    _totpController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context);
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<SessionState>().login(
            url: _urlController.text,
            login: _loginController.text.trim(),
            password: _passwordController.text,
            totpCode: _showTotp ? _totpController.text.trim() : null,
          );
      // успех — root-гейт сам переключит экран
    } on StreamsApiException catch (e) {
      if (!mounted) return;
      setState(() {
        switch (e.code) {
          case 'totp_required':
            _showTotp = true;
            _error = l10n.totpHelp;
          case 'totp_invalid':
            _showTotp = true;
            _error = l10n.errTotpInvalid;
          case 'auth_failed':
            _error = l10n.errInvalidCredentials;
          case 'network':
            _error = l10n.errNetwork;
          default:
            _error = l10n.errServer(e.message);
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = l10n.errServer(e.toString()));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Icon(Icons.forum_outlined,
                      size: 56, color: Theme.of(context).colorScheme.primary),
                  const SizedBox(height: 8),
                  Text(
                    l10n.appTitle,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 24),
                  TextFormField(
                    controller: _urlController,
                    decoration: InputDecoration(
                      labelText: l10n.serverUrlLabel,
                      border: const OutlineInputBorder(),
                      prefixIcon: const Icon(Icons.dns_outlined),
                    ),
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? l10n.fieldRequired : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _loginController,
                    decoration: InputDecoration(
                      labelText: l10n.loginLabel,
                      border: const OutlineInputBorder(),
                      prefixIcon: const Icon(Icons.person_outline),
                    ),
                    autocorrect: false,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? l10n.fieldRequired : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _passwordController,
                    decoration: InputDecoration(
                      labelText: l10n.passwordLabel,
                      border: const OutlineInputBorder(),
                      prefixIcon: const Icon(Icons.lock_outline),
                    ),
                    obscureText: true,
                    validator: (v) =>
                        (v == null || v.isEmpty) ? l10n.fieldRequired : null,
                    onFieldSubmitted: (_) => _submit(),
                  ),
                  if (_showTotp) ...[
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _totpController,
                      decoration: InputDecoration(
                        labelText: l10n.totpLabel,
                        border: const OutlineInputBorder(),
                        prefixIcon: const Icon(Icons.pin_outlined),
                      ),
                      keyboardType: TextInputType.number,
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? l10n.fieldRequired : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      _error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error),
                    ),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(l10n.signInButton),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
