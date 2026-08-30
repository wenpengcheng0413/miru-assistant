class CapabilityStatus {
  const CapabilityStatus({
    required this.available,
    this.location = '',
    this.reason = '',
    this.provider = '',
  });

  final bool available;
  final String location;
  final String reason;
  final String provider;

  factory CapabilityStatus.fromJson(dynamic value) {
    if (value is String) {
      return CapabilityStatus(available: value == 'available');
    }
    if (value is! Map) return const CapabilityStatus(available: false);
    return CapabilityStatus(
      available: value['available'] == true || value['state'] == 'available',
      location: value['location'] as String? ?? '',
      reason: value['reason'] as String? ?? '',
      provider: value['provider'] as String? ?? '',
    );
  }
}

class MiruSystemStatus {
  const MiruSystemStatus({
    required this.cloudState,
    required this.homeNodeState,
    required this.capabilities,
    this.generatedAt,
    this.schemaVersion = 1,
  });

  final String cloudState;
  final String homeNodeState;
  final Map<String, CapabilityStatus> capabilities;
  final DateTime? generatedAt;
  final int schemaVersion;

  bool get cloudOnline => cloudState == 'online' || cloudState == 'ready';
  bool get homeNodeOnline => homeNodeState == 'online';

  String get cloudLabel => cloudOnline ? 'Cloud Online' : 'Cloud Offline';
  String get homeNodeLabel =>
      homeNodeOnline ? 'Home Node Online' : 'Home Node Offline';

  factory MiruSystemStatus.fromJson(Map<dynamic, dynamic> json) {
    final cloud = json['cloud'] is Map ? json['cloud'] as Map : const {};
    final node = json['home_node'] is Map ? json['home_node'] as Map : const {};
    final rawCapabilities = json['capabilities'] is Map
        ? json['capabilities'] as Map
        : const {};
    final capabilities = <String, CapabilityStatus>{};
    for (final entry in rawCapabilities.entries) {
      final key = entry.key.toString();
      if (key.endsWith('_reason')) continue;
      var parsed = CapabilityStatus.fromJson(entry.value);
      final legacyReason = rawCapabilities['${key}_reason'];
      if (parsed.reason.isEmpty && legacyReason is String) {
        parsed = CapabilityStatus(
          available: parsed.available,
          location: parsed.location,
          reason: legacyReason,
          provider: parsed.provider,
        );
      }
      capabilities[key] = parsed;
    }
    return MiruSystemStatus(
      cloudState: cloud['state'] as String? ?? 'offline',
      homeNodeState: node['state'] as String? ?? 'offline',
      capabilities: capabilities,
      generatedAt: DateTime.tryParse(json['generated_at'] as String? ?? ''),
      schemaVersion: (json['schema_version'] as num?)?.toInt() ?? 1,
    );
  }
}
