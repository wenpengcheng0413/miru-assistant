import 'dart:async';
import 'dart:io';

import 'package:bonsoir/bonsoir.dart';

/// Bonjour service published by the Windows backend.
const miruServiceType = '_miru._tcp';

/// Finds a Miru backend without assuming that the computer keeps one DHCP IP.
class ServerDiscovery {
  Future<Uri?> findServer({
    Duration timeout = const Duration(seconds: 6),
  }) async {
    final discovery = BonsoirDiscovery(
      type: miruServiceType,
      printLogs: false,
    );
    StreamSubscription<BonsoirDiscoveryEvent>? subscription;
    final result = Completer<Uri?>();

    try {
      await discovery.initialize();
      subscription = discovery.eventStream!.listen(
        (event) async {
          if (event is BonsoirDiscoveryServiceFoundEvent) {
            try {
              await event.service.resolve(discovery.serviceResolver);
            } catch (_) {
              // Another advertisement may still resolve successfully.
            }
            return;
          }
          if (event is! BonsoirDiscoveryServiceResolvedEvent ||
              result.isCompleted) {
            return;
          }
          final uri = _serviceUri(event.service);
          if (uri != null) result.complete(uri);
        },
        onError: (Object _) {
          if (!result.isCompleted) result.complete(null);
        },
      );
      await discovery.start();
      return await result.future.timeout(timeout, onTimeout: () => null);
    } catch (_) {
      return null;
    } finally {
      await subscription?.cancel();
      try {
        await discovery.stop();
      } catch (_) {
        // Discovery may not have reached the started state.
      }
    }
  }

  Uri? _serviceUri(BonsoirService service) {
    final addresses = service.hostAddresses
        .where(_isUsableAddress)
        .toList(growable: false);
    // Prefer IPv4 on a home LAN. It avoids scoped IPv6 link-local addresses.
    final ipv4 = addresses.where((value) => !value.contains(':'));
    final host = ipv4.isNotEmpty
        ? ipv4.first
        : (addresses.isNotEmpty ? addresses.first : service.hostname);
    if (host == null || host.trim().isEmpty || service.port <= 0) return null;
    return Uri(scheme: 'http', host: host.trim(), port: service.port);
  }

  bool _isUsableAddress(String value) {
    final address = InternetAddress.tryParse(value);
    if (address == null || address.isLoopback || address.isLinkLocal) {
      return false;
    }
    return address.type == InternetAddressType.IPv4 ||
        address.type == InternetAddressType.IPv6;
  }
}
