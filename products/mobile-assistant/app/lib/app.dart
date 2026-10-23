import 'package:flutter/material.dart';

import 'core/audio/player_service.dart';
import 'core/audio/recorder_service.dart';
import 'core/config.dart';
import 'core/design/miru_theme.dart';
import 'core/design/miru_widgets.dart';
import 'core/server_discovery.dart';
import 'core/ws_client.dart';
import 'features/chat/chat_controller.dart';
import 'features/chat/chat_screen.dart';

class MiruApp extends StatelessWidget {
  const MiruApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: MiruThemeController.instance.mode,
      builder: (context, mode, _) => MaterialApp(
        title: 'Miru',
        debugShowCheckedModeBanner: false,
        theme: MiruTheme.light,
        darkTheme: MiruTheme.dark,
        themeMode: mode,
        themeAnimationDuration:
            MediaQuery.maybeOf(context)?.disableAnimations == true
                ? Duration.zero
                : const Duration(milliseconds: 180),
        home: const _Bootstrap(),
      ),
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
  late Future<AppConfig> _configFuture;
  ChatController? _controller;
  PlayerService? _player;

  @override
  void initState() {
    super.initState();
    _configFuture = AppConfig.load();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AppConfig>(
      future: _configFuture,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Scaffold(
              body: Center(
                  child: MiruEmptyState(
            icon: Icons.lock_outline,
            title: '暂时无法读取配置',
            description: '请稍后重试，已保存的数据会继续保留。',
            action: FilledButton(
                onPressed: () =>
                    setState(() => _configFuture = AppConfig.load()),
                child: const Text('重试')),
          )));
        }
        if (!snapshot.hasData) {
          return const Scaffold(
              body: Center(child: CircularProgressIndicator()));
        }
        final config = snapshot.data!;
        final player = _player ??= PlayerService();
        final controller = _controller ??= _buildController(config, player);
        return ChatScreen(controller: controller, player: player);
      },
    );
  }

  /// 聊天页与设置页共享同一个 controller（WS/录音/播放单例）
  ChatController _buildController(AppConfig config, PlayerService player) {
    final ws = WsClient(
      url: config.wsUri,
      token: config.token,
      hello: config.hello, // 含 synth_tts / auto_run 等当前设置
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
