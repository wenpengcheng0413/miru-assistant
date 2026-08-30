enum DeploymentProfile { development, tailnet, public }

extension DeploymentProfileValue on DeploymentProfile {
  String get value => name;

  String get label => switch (this) {
    DeploymentProfile.development => '开发 / 局域网',
    DeploymentProfile.tailnet => '生产 / Tailscale',
    DeploymentProfile.public => '生产 / 公网 HTTPS',
  };

  bool get isCloud => this != DeploymentProfile.development;
  bool get allowsBonjour => this == DeploymentProfile.development;
}

DeploymentProfile parseDeploymentProfile(String? value) {
  return DeploymentProfile.values.firstWhere(
    (item) => item.value == value?.trim().toLowerCase(),
    orElse: () => DeploymentProfile.development,
  );
}
