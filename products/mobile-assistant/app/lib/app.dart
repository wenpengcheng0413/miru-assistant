import 'package:flutter/material.dart';

import 'core/audio/player_service.dart';
import 'core/audio/recorder_service.dart';
import 'core/config.dart';
import 'core/server_discovery.dart';
import 'core/ws_client.dart';
import 'features/chat/chat_controller.dart';
import 'features/chat/chat_screen.dart';
import 'features/settings/settings_screen.dart';

class MiruApp extends StatelessWidget {
  const MiruApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Miru',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF7C6FF0),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const _Bootstrap(),
    );
  }
}

/// 先加载配置，再进入主页
class _Bootstrap extends StatefulWidget {
  const _Bootstrap();

  @override
  State<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<_Bootstrap> {
  late final Future<AppConfig> _configFuture;

  @override
  void initState() {
    super.initState();
    _configFuture = AppConfig.load();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AppConfig>(
      future: _configFuture,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        final config = snapshot.data!;
        final player = PlayerService();
        return ChatScreen(controller: _buildController(config, player), player: player);
      },
    );
  }

  /// 聊天页与设置页共享同一个 controller（WS/录音/播放单例）
  ChatController _buildController(AppConfig config, PlayerService player) {
    final ws = WsClient(
      url: config.wsUri,
      token: config.token,
      hello: config.hello,   // 含 synth_tts / auto_run 等当前设置
    );
    final controller = ChatController(
      config: config,
      ws: ws,
      recorder: RecorderService(),
      player: player,
      discovery: ServerDiscovery(),
    )..init();
    ws.connect();
    return controller;
  }
}
