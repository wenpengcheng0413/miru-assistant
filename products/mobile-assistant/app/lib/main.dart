import 'package:flutter/material.dart';

import 'app.dart';
import 'core/design/miru_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await MiruThemeController.instance.load();
  } catch (_) {
    // A missing appearance preference must never block access to the app.
  }
  runApp(const MiruApp());
}
