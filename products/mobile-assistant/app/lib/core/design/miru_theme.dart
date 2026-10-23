import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Shared layout rhythm. Keep content readable on phones and wide windows.
abstract final class MiruSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 16;
  static const double page = 20;
  static const double lg = 24;
  static const double xl = 32;
  static const double contentWidth = 760;
  static const double wideBreakpoint = 1000;
  static const double radius = 20;
}

abstract final class MiruMotion {
  static Duration duration(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context)
          ? Duration.zero
          : const Duration(milliseconds: 180);
}

abstract final class MiruTheme {
  static ThemeData get light => _build(Brightness.light);
  static ThemeData get dark => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final dark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF246B5D),
      brightness: brightness,
    ).copyWith(
      primary: dark ? const Color(0xFF9CD9C3) : const Color(0xFF246B5D),
      onPrimary: dark ? const Color(0xFF123A31) : Colors.white,
      primaryContainer:
          dark ? const Color(0xFF21493E) : const Color(0xFFDDEDE5),
      onPrimaryContainer:
          dark ? const Color(0xFFDDEDE5) : const Color(0xFF183E33),
      surface: dark ? const Color(0xFF151C1A) : const Color(0xFFF8F9F5),
      surfaceContainerLowest: dark ? const Color(0xFF101613) : Colors.white,
      surfaceContainerLow:
          dark ? const Color(0xFF1B2420) : const Color(0xFFF0F3ED),
      surfaceContainer:
          dark ? const Color(0xFF202B25) : const Color(0xFFEBEFE8),
      surfaceContainerHigh:
          dark ? const Color(0xFF27322C) : const Color(0xFFE5EBE2),
      surfaceContainerHighest:
          dark ? const Color(0xFF2F3B33) : const Color(0xFFDFE6DB),
      onSurface: dark ? const Color(0xFFE4EBE4) : const Color(0xFF202B25),
      onSurfaceVariant:
          dark ? const Color(0xFFB1BEB4) : const Color(0xFF59665D),
      outlineVariant: dark ? const Color(0xFF3A483E) : const Color(0xFFD8E0D4),
    );
    final base = ThemeData(useMaterial3: true, colorScheme: scheme);
    final text = base.textTheme.copyWith(
      headlineLarge: base.textTheme.headlineLarge?.copyWith(
          fontSize: 32,
          fontWeight: FontWeight.w600,
          height: 1.25,
          letterSpacing: -0.8),
      headlineMedium: base.textTheme.headlineMedium?.copyWith(
          fontSize: 26,
          fontWeight: FontWeight.w600,
          height: 1.3,
          letterSpacing: -0.5),
      titleLarge: base.textTheme.titleLarge
          ?.copyWith(fontSize: 21, fontWeight: FontWeight.w600, height: 1.4),
      titleMedium: base.textTheme.titleMedium
          ?.copyWith(fontSize: 16, fontWeight: FontWeight.w600, height: 1.5),
      bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 16, height: 1.65),
      bodyMedium:
          base.textTheme.bodyMedium?.copyWith(fontSize: 14, height: 1.55),
      bodySmall: base.textTheme.bodySmall
          ?.copyWith(fontSize: 12, height: 1.5, color: scheme.onSurfaceVariant),
      labelLarge: base.textTheme.labelLarge
          ?.copyWith(fontSize: 14, fontWeight: FontWeight.w600),
    );
    final shape = RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(MiruSpacing.radius));
    return base.copyWith(
      textTheme: text,
      scaffoldBackgroundColor: scheme.surface,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: text.titleLarge,
      ),
      cardTheme: CardThemeData(
        clipBehavior: Clip.antiAlias,
        color: scheme.surfaceContainerLowest,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: shape.copyWith(side: BorderSide(color: scheme.outlineVariant)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surfaceContainerLowest,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: BorderSide(color: scheme.outlineVariant)),
        enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: BorderSide(color: scheme.outlineVariant)),
        focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: BorderSide(color: scheme.primary, width: 1.5)),
      ),
      filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
              minimumSize: const Size(48, 48),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14)))),
      outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
              minimumSize: const Size(48, 48),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14)))),
      textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48))),
      iconButtonTheme: IconButtonThemeData(
          style: IconButton.styleFrom(minimumSize: const Size(48, 48))),
      chipTheme: base.chipTheme.copyWith(
          side: BorderSide(color: scheme.outlineVariant),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
      dividerTheme: DividerThemeData(
          color: scheme.outlineVariant, thickness: 1, space: 1),
      expansionTileTheme: ExpansionTileThemeData(
        shape: const Border(),
        collapsedShape: const Border(),
        iconColor: scheme.primary,
        collapsedIconColor: scheme.onSurfaceVariant,
        textColor: scheme.onSurface,
        collapsedTextColor: scheme.onSurface,
      ),
      drawerTheme: DrawerThemeData(
          backgroundColor: scheme.surfaceContainerLow,
          elevation: 0,
          shape: const RoundedRectangleBorder()),
      dialogTheme: DialogThemeData(
          backgroundColor: scheme.surfaceContainerLowest, shape: shape),
      bottomSheetTheme: BottomSheetThemeData(
          backgroundColor: scheme.surfaceContainerLowest,
          showDragHandle: true,
          shape: shape),
      snackBarTheme: SnackBarThemeData(
          behavior: SnackBarBehavior.floating,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
      tooltipTheme:
          const TooltipThemeData(waitDuration: Duration(milliseconds: 400)),
    );
  }
}

/// UI-only preference: no changes to server credentials or conversation storage.
class MiruThemeController {
  MiruThemeController._();
  static final instance = MiruThemeController._();
  static const storageKey = 'miru_theme_mode';
  final mode = ValueNotifier<ThemeMode>(ThemeMode.system);

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final name = prefs.getString(storageKey);
    mode.value = ThemeMode.values.firstWhere((value) => value.name == name,
        orElse: () => ThemeMode.system);
  }

  Future<void> setMode(ThemeMode value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(storageKey, value.name);
    mode.value = value;
  }
}
