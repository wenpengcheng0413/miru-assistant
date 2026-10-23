import 'package:flutter/material.dart';
import 'miru_theme.dart';

class MiruBrandMark extends StatelessWidget {
  const MiruBrandMark({super.key, this.size = 40});
  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
            color: colors.primary,
            borderRadius: BorderRadius.circular(size * .34)),
        child: Center(
            child: Text('m',
                style: TextStyle(
                    fontSize: size * .7,
                    height: 1,
                    color: colors.onPrimary,
                    fontWeight: FontWeight.w500,
                    letterSpacing: -2))),
      ),
    );
  }
}

class MiruPageBody extends StatelessWidget {
  const MiruPageBody(
      {super.key,
      required this.child,
      this.maxWidth = MiruSpacing.contentWidth});
  final Widget child;
  final double maxWidth;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth), child: child),
      );
}

class MiruSection extends StatelessWidget {
  const MiruSection(
      {super.key, required this.title, this.subtitle, required this.child});
  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: MiruSpacing.lg),
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          if (subtitle != null)
            Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(subtitle!,
                    style: Theme.of(context).textTheme.bodySmall)),
          const SizedBox(height: 12),
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(MiruSpacing.md), child: child)),
        ]),
      );
}

class MiruEmptyState extends StatelessWidget {
  const MiruEmptyState(
      {super.key,
      required this.icon,
      required this.title,
      required this.description,
      this.action});
  final IconData icon;
  final String title;
  final String description;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(MiruSpacing.lg),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 36, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 16),
          Text(title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(description,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant)),
          if (action != null) ...[const SizedBox(height: 16), action!],
        ]),
      );
}
