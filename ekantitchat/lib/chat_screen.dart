import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app_theme.dart';
import 'chat_history_service.dart';
import 'chat_service.dart';
import 'chat_session.dart';

/// Formats raw bot response by removing '**' markers and converting
/// leading '* ' bullets at the beginning of any line to '• '.
String formatBotAnswer(String raw) {
  final noBold = raw.replaceAll('**', '');
  final lines = noBold.split('\n');
  final formatted = lines.map((line) {
    if (line.startsWith('* ')) {
      return '• ${line.substring(2)}';
    }
    return line;
  }).join('\n');
  return formatted;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final List<ChatMessage> _messages = [];
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final FocusNode _focusNode = FocusNode();

  final ChatHistoryService _historyService = ChatHistoryService();
  ChatService _chatService = ChatService();

  ChatSession _currentSession = ChatSession.createEmpty();
  List<ChatSession> _historySessions = [];

  bool _isLoading = false;
  bool _isLoadingHistory = true;
  bool _isBackendConnected = false;
  String? _copiedMessageContent;

  // Spiritual prompt suggestions for empty state
  static const List<String> _suggestedPrompts = [
    'मन को शांत कैसे करें?',
    'क्रोध पर नियंत्रण कैसे पाएं?',
    'नाम जप की सही विधि और महत्व क्या है?',
    'संसार और भक्ति में संतुलन कैसे बनाएं?',
  ];

  @override
  void initState() {
    super.initState();
    _loadHistorySessions();
    _checkBackendHealth();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _focusNode.dispose();
    _chatService.dispose();
    super.dispose();
  }

  Future<void> _checkBackendHealth() async {
    final connected = await _chatService.checkHealth();
    if (mounted) {
      setState(() {
        _isBackendConnected = connected;
      });
    }
  }

  Future<void> _loadHistorySessions() async {
    try {
      final sessions = await _historyService.loadSessions();
      if (mounted) {
        setState(() {
          _historySessions = sessions;
          _isLoadingHistory = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _isLoadingHistory = false;
        });
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _startNewSession() async {
    // If the active session has messages, save it first
    if (_messages.isNotEmpty) {
      await _persistCurrentSession();
    }

    setState(() {
      _currentSession = ChatSession.createEmpty();
      _messages.clear();
      _controller.clear();
    });
    await _loadHistorySessions();
  }

  Future<void> _switchToSession(ChatSession session) async {
    // Save current session before switching if it has messages
    if (_messages.isNotEmpty && _currentSession.id != session.id) {
      await _persistCurrentSession();
    }

    setState(() {
      _currentSession = session;
      _messages.clear();
      _messages.addAll(session.messages);
      _controller.clear();
    });

    _scrollToBottom();
  }

  Future<void> _deleteSession(String sessionId) async {
    await _historyService.deleteSession(sessionId);
    if (_currentSession.id == sessionId) {
      setState(() {
        _currentSession = ChatSession.createEmpty();
        _messages.clear();
      });
    }
    await _loadHistorySessions();
  }

  Future<void> _clearAllSessions() async {
    await _historyService.clearAll();
    setState(() {
      _currentSession = ChatSession.createEmpty();
      _messages.clear();
      _historySessions.clear();
    });
  }

  Future<void> _persistCurrentSession() async {
    if (_messages.isEmpty) return;

    final firstUserMsg = _messages.firstWhere(
      (m) => m.isUser,
      orElse: () => _messages.first,
    );

    String title = _currentSession.title;
    if (title == 'New Conversation' || title.isEmpty) {
      title = firstUserMsg.text.trim();
      if (title.length > 36) {
        title = '${title.substring(0, 36)}...';
      }
    }

    final lastMsg = _messages.last;
    String snippet = lastMsg.text.replaceAll('\n', ' ').trim();
    if (snippet.length > 55) {
      snippet = '${snippet.substring(0, 55)}...';
    }

    final updated = _currentSession.copyWith(
      title: title,
      lastSnippet: snippet,
      updatedAt: DateTime.now(),
      messages: List.from(_messages),
    );

    _currentSession = updated;
    await _historyService.saveSession(updated);
    await _loadHistorySessions();
  }

  Future<void> _sendPrompt(String prompt) async {
    _controller.text = prompt;
    await _sendMessage();
  }

  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

    _controller.clear();
    final userMessage = ChatMessage.user(text);
    setState(() {
      _messages.add(userMessage);
      _isLoading = true;
    });
    _scrollToBottom();

    try {
      final response = await _chatService.sendChat(
        query: text,
        history: _messages,
      );

      final formattedAnswer = formatBotAnswer(response.answer);
      if (mounted) {
        setState(() {
          _messages.add(ChatMessage.assistant(
            formattedAnswer,
            matchedEpisodes: response.matchedEpisodes,
          ));
          _isLoading = false;
          _isBackendConnected = true;
        });
        _scrollToBottom();
        await _persistCurrentSession();
      }
    } on TimeoutException catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(ChatMessage.assistant(
            e.message ?? 'Request timed out after 90 seconds. Please try again.',
            isError: true,
          ));
          _isLoading = false;
        });
        _scrollToBottom();
      }
    } on SocketException catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(ChatMessage.assistant(
            e.message,
            isError: true,
          ));
          _isLoading = false;
          _isBackendConnected = false;
        });
        _scrollToBottom();
      }
    } catch (e) {
      if (mounted) {
        final errorText = e.toString()
            .replaceAll('Exception: ', '')
            .replaceAll('HttpException: ', '');
        setState(() {
          _messages.add(ChatMessage.assistant(
            errorText.isEmpty ? 'Unexpected error occurred. Please try again.' : errorText,
            isError: true,
          ));
          _isLoading = false;
        });
        _scrollToBottom();
      }
    }
  }

  void _copyToClipboard(String content) {
    Clipboard.setData(ClipboardData(text: content));
    setState(() {
      _copiedMessageContent = content;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('उत्तर कॉपी हो गया (Copied to clipboard)'),
        duration: Duration(seconds: 2),
        behavior: SnackBarBehavior.floating,
      ),
    );
    Future.delayed(const Duration(seconds: 3), () {
      if (mounted && _copiedMessageContent == content) {
        setState(() {
          _copiedMessageContent = null;
        });
      }
    });
  }

  void _showBackendSettingsDialog() {
    final urlController = TextEditingController(text: _chatService.baseUrl);
    bool testing = false;
    String? statusMessage;

    showDialog(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Row(
            children: [
              Icon(Icons.dns_outlined, color: AppColors.accentStrong, size: 22),
              SizedBox(width: 8),
              Text(
                'Backend API Server',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Configure the FastAPI RAG backend endpoint. Use localhost for local runs or your deployed HTTPS URL for web.',
                style: TextStyle(fontSize: 13, color: AppColors.mutedText, height: 1.4),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: urlController,
                decoration: InputDecoration(
                  labelText: 'API Base URL',
                  hintText: 'http://localhost:8000',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                ),
                style: const TextStyle(fontSize: 14),
              ),
              if (statusMessage != null) ...[
                const SizedBox(height: 10),
                Text(
                  statusMessage!,
                  style: TextStyle(
                    fontSize: 12.5,
                    color: statusMessage!.contains('Success')
                        ? Colors.green[700]
                        : Colors.red[700],
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ],
          ),
          actions: [
            TextButton(
              onPressed: testing
                  ? null
                  : () async {
                      setDialogState(() {
                        testing = true;
                        statusMessage = 'Checking connection...';
                      });
                      final testService = ChatService(baseUrl: urlController.text.trim());
                      final ok = await testService.checkHealth();
                      setDialogState(() {
                        testing = false;
                        statusMessage = ok
                            ? '✓ Successfully connected to backend!'
                            : '✕ Could not reach server. Verify server is running and CORS is enabled.';
                      });
                    },
              child: const Text('Test Connection'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onPressed: () {
                final newUrl = urlController.text.trim();
                if (newUrl.isNotEmpty) {
                  setState(() {
                    _chatService = _chatService.copyWith(baseUrl: newUrl);
                  });
                  _checkBackendHealth();
                }
                Navigator.of(dialogContext).pop();
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.pageBackground,
      endDrawer: _buildHistoryDrawer(context),
      body: SafeArea(
        child: Column(
          children: [
            // Full-width header spanning 100% horizontally
            _buildFullWidthHeader(),

            // Content area
            Expanded(
              child: _messages.isEmpty && !_isLoading
                  ? _buildEmptyStateView()
                  : _buildChatView(),
            ),
          ],
        ),
      ),
    );
  }

  /// Full-width header matching Figma: left floral logo + titles, right server status & history clock button
  Widget _buildFullWidthHeader() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
      decoration: const BoxDecoration(
        color: AppColors.headerBackground,
        border: Border(
          bottom: BorderSide(color: AppColors.headerBorder, width: 1),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.botBubble,
              shape: BoxShape.circle,
              border: Border.all(color: AppColors.border, width: 1),
            ),
            child: const Icon(
              Icons.filter_vintage_outlined,
              color: AppColors.accentStrong,
              size: 18,
            ),
          ),
          const SizedBox(width: 12),
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Ekantit Chat',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: AppColors.botText,
                ),
              ),
              SizedBox(height: 2),
              Text(
                'A quiet space for heartfelt reflection',
                style: TextStyle(
                  fontSize: 12,
                  color: AppColors.mutedText,
                ),
              ),
            ],
          ),
          const Spacer(),

          // Backend connection badge with click-to-configure dialog
          InkWell(
            onTap: _showBackendSettingsDialog,
            borderRadius: BorderRadius.circular(16),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppColors.headerBorder, width: 1),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: _isBackendConnected ? Colors.green[600] : Colors.amber[700],
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _isBackendConnected ? 'Connected' : 'Backend URL',
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w500,
                      color: _isBackendConnected ? Colors.green[800] : AppColors.accentStrong,
                    ),
                  ),
                ],
              ),
            ),
          ),

          // History button that opens the drawer
          Builder(
            builder: (ctx) => InkWell(
              onTap: () {
                _loadHistorySessions();
                Scaffold.of(ctx).openEndDrawer();
              },
              borderRadius: BorderRadius.circular(18),
              child: Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.headerBorder, width: 1),
                ),
                child: const Icon(
                  Icons.access_time,
                  size: 16,
                  color: AppColors.accentStrong,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Dynamic history drawer backed by ChatHistoryService (Local + Firestore)
  Widget _buildHistoryDrawer(BuildContext context) {
    return Drawer(
      width: 330,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Drawer header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
              decoration: const BoxDecoration(
                border: Border(
                  bottom: BorderSide(color: AppColors.headerBorder, width: 1),
                ),
              ),
              child: Row(
                children: [
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: AppColors.botBubble,
                      shape: BoxShape.circle,
                      border: Border.all(color: AppColors.border, width: 1),
                    ),
                    child: const Icon(
                      Icons.filter_vintage_outlined,
                      color: AppColors.accentStrong,
                      size: 14,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Text(
                    'Chat History',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.botText,
                    ),
                  ),
                  const Spacer(),
                  InkWell(
                    onTap: () => Navigator.of(context).pop(),
                    borderRadius: BorderRadius.circular(14),
                    child: Container(
                      width: 26,
                      height: 26,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(color: AppColors.border, width: 1),
                      ),
                      child: const Icon(
                        Icons.close,
                        size: 14,
                        color: AppColors.mutedText,
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // "+ New Session" button
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
              child: InkWell(
                onTap: () async {
                  Navigator.of(context).pop();
                  await _startNewSession();
                },
                borderRadius: BorderRadius.circular(24),
                child: Container(
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.accent,
                    borderRadius: BorderRadius.circular(22),
                  ),
                  alignment: Alignment.center,
                  child: const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.add, color: Colors.white, size: 18),
                      SizedBox(width: 8),
                      Text(
                        'New Session',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w600,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),

            // "RECENT" Section title
            const Padding(
              padding: EdgeInsets.fromLTRB(18, 10, 18, 8),
              child: Text(
                'RECENT',
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.1,
                  color: AppColors.accentStrong,
                ),
              ),
            ),

            // History items list (or empty placeholder)
            Expanded(
              child: _isLoadingHistory
                  ? const Center(
                      child: CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation(AppColors.accent),
                        strokeWidth: 2,
                      ),
                    )
                  : _historySessions.isEmpty
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 24),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.chat_bubble_outline_rounded,
                                  size: 36,
                                  color: AppColors.mutedText.withValues(alpha: 0.5),
                                ),
                                const SizedBox(height: 10),
                                const Text(
                                  'No previous chats yet',
                                  style: TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w500,
                                    color: AppColors.mutedText,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                const Text(
                                  'Ask a question to start your first spiritual dialogue.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    fontSize: 11.5,
                                    color: AppColors.mutedText,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          itemCount: _historySessions.length,
                          separatorBuilder: (context, index) => const Divider(
                            height: 1,
                            thickness: 0.5,
                            color: AppColors.headerBorder,
                          ),
                          itemBuilder: (context, index) {
                            final session = _historySessions[index];
                            final isActive = session.id == _currentSession.id;

                            return Dismissible(
                              key: Key(session.id),
                              direction: DismissDirection.endToStart,
                              background: Container(
                                alignment: Alignment.centerRight,
                                padding: const EdgeInsets.only(right: 16),
                                color: Colors.red[100],
                                child: Icon(Icons.delete_outline, color: Colors.red[700]),
                              ),
                              onDismissed: (_) => _deleteSession(session.id),
                              child: InkWell(
                                onTap: () {
                                  Navigator.of(context).pop();
                                  _switchToSession(session);
                                },
                                borderRadius: BorderRadius.circular(6),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 12,
                                    vertical: 10,
                                  ),
                                  decoration: BoxDecoration(
                                    color: isActive
                                        ? const Color(0xFFFCEFDE)
                                        : Colors.transparent,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Row(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              session.title,
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                              style: TextStyle(
                                                fontSize: 13,
                                                fontWeight: isActive
                                                    ? FontWeight.w600
                                                    : FontWeight.w500,
                                                color: AppColors.botText,
                                              ),
                                            ),
                                            const SizedBox(height: 2),
                                            Text(
                                              session.lastSnippet,
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                              style: const TextStyle(
                                                fontSize: 11.5,
                                                color: AppColors.mutedText,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                      const SizedBox(width: 8),
                                      Column(
                                        crossAxisAlignment: CrossAxisAlignment.end,
                                        children: [
                                          Text(
                                            ChatHistoryService.formatDisplayDate(session.updatedAt),
                                            style: TextStyle(
                                              fontSize: 11,
                                              color: isActive
                                                  ? AppColors.accentStrong
                                                  : AppColors.mutedText,
                                            ),
                                          ),
                                          const SizedBox(height: 4),
                                          InkWell(
                                            onTap: () => _deleteSession(session.id),
                                            child: const Icon(
                                              Icons.delete_outline,
                                              size: 14,
                                              color: AppColors.mutedText,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            );
                          },
                        ),
            ),

            // Clear all history action
            if (_historySessions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 6),
                child: TextButton.icon(
                  onPressed: () {
                    showDialog(
                      context: context,
                      builder: (dialogCtx) => AlertDialog(
                        title: const Text('Clear all history?'),
                        content: const Text(
                          'This will delete all previous conversations from your device and cloud storage.',
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.of(dialogCtx).pop(),
                            child: const Text('Cancel'),
                          ),
                          TextButton(
                            onPressed: () {
                              Navigator.of(dialogCtx).pop();
                              _clearAllSessions();
                            },
                            style: TextButton.styleFrom(foregroundColor: Colors.red),
                            child: const Text('Clear All'),
                          ),
                        ],
                      ),
                    );
                  },
                  icon: const Icon(Icons.delete_sweep_outlined, size: 16, color: AppColors.mutedText),
                  label: const Text(
                    'Clear History',
                    style: TextStyle(fontSize: 12, color: AppColors.mutedText),
                  ),
                ),
              ),

            // Footer at bottom of drawer
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 14),
              decoration: const BoxDecoration(
                border: Border(
                  top: BorderSide(color: AppColors.headerBorder, width: 1),
                ),
              ),
              child: const Text(
                'Satsang AI • Ancient wisdom, modern clarity',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 10.5,
                  color: AppColors.mutedText,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Empty state matching Figma design + spiritual quick prompt suggestions
  Widget _buildEmptyStateView() {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Avatar with soft gold glow and ring
              Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.avatarRing, width: 3),
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.avatarRing.withValues(alpha: 0.35),
                      blurRadius: 18,
                      spreadRadius: 2,
                    ),
                  ],
                ),
                child: ClipOval(
                  child: Image.asset(
                    'assets/images/radha_keli.jpeg',
                    fit: BoxFit.cover,
                    errorBuilder: (context, error, stackTrace) => Container(
                      color: AppColors.botBubble,
                      child: const Icon(
                        Icons.spa,
                        size: 48,
                        color: AppColors.accentStrong,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                'राधे राधे',
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w600,
                  color: AppColors.accentStrong,
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                'आज आपके मन में क्या है? / What\'s on your mind today?',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 15,
                  color: AppColors.mutedText,
                ),
              ),
              const SizedBox(height: 26),

              // Quick spiritual prompt chips
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: _suggestedPrompts.map((prompt) {
                  return ActionChip(
                    label: Text(
                      prompt,
                      style: const TextStyle(
                        fontSize: 12.5,
                        color: AppColors.accentStrong,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    backgroundColor: Colors.white,
                    side: const BorderSide(color: AppColors.border, width: 0.8),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(18),
                    ),
                    onPressed: () => _sendPrompt(prompt),
                  );
                }).toList(),
              ),

              const SizedBox(height: 24),

              // Centered input bar in empty state
              _buildInputBar(),

              const SizedBox(height: 24),
              // Disclaimer text in orange
              const Text(
                'यह उत्तर महाराज जी के सत्संगों में दिए गए वास्तविक उपदेशों पर आधारित है - इनकी वाणी, भाव और शिक्षाओं को समझकर,\nआपकी स्थिति के अनुरूप प्रस्तुत किया गया है',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: AppColors.accentStrong,
                ),
              ),
              const SizedBox(height: 36),

              // Bottom footer caption
              _buildFooterCaption(),
            ],
          ),
        ),
      ),
    );
  }

  /// Chat view matching Figma: scrollable bubbles in 640px column + input bar + footer caption
  Widget _buildChatView() {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640),
        child: Column(
          children: [
            Expanded(
              child: ListView.builder(
                controller: _scrollController,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                itemCount: _messages.length + (_isLoading ? 1 : 0),
                itemBuilder: (context, index) {
                  if (index == _messages.length && _isLoading) {
                    return _buildTypingBubble();
                  }
                  final message = _messages[index];
                  return _buildMessageBubble(message);
                },
              ),
            ),
            _buildInputBar(),
            const SizedBox(height: 10),
            _buildFooterCaption(),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }

  Widget _buildFooterCaption() {
    return const Text(
      'Satsang AI • Reflective wisdom powered by ancient values and modern clarity',
      textAlign: TextAlign.center,
      style: TextStyle(
        fontSize: 11.5,
        color: AppColors.mutedText,
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage message) {
    if (message.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 14, left: 56),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
          decoration: BoxDecoration(
            color: AppColors.userBubble,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: AppColors.border, width: 1),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.02),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Text(
            message.text,
            style: const TextStyle(
              fontSize: 15,
              height: 1.45,
              color: AppColors.userText,
            ),
          ),
        ),
      );
    }

    final isCopied = _copiedMessageContent == message.text;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            margin: const EdgeInsets.only(top: 2, right: 10),
            decoration: BoxDecoration(
              color: AppColors.botBubble,
              shape: BoxShape.circle,
              border: Border.all(color: AppColors.border, width: 1),
            ),
            child: const Icon(
              Icons.share_outlined,
              color: AppColors.accentStrong,
              size: 15,
            ),
          ),
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: Container(
                margin: const EdgeInsets.only(right: 36),
                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                decoration: BoxDecoration(
                  color: message.isError ? AppColors.errorBubble : AppColors.botBubble,
                  borderRadius: BorderRadius.circular(18),
                  border: message.isError
                      ? Border.all(color: AppColors.errorBorder, width: 1)
                      : null,
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 8,
                      offset: const Offset(0, 2),
                    ),
                  ],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SelectableText(
                      message.text,
                      style: TextStyle(
                        fontSize: 15,
                        height: 1.5,
                        color: message.isError ? AppColors.errorText : AppColors.botText,
                      ),
                    ),
                    if (!message.isError && message.matchedEpisodes.isNotEmpty)
                      _buildSourcesSection(message.matchedEpisodes),

                    // Copy action button
                    if (!message.isError)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            InkWell(
                              onTap: () => _copyToClipboard(message.text),
                              borderRadius: BorderRadius.circular(6),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                      isCopied ? Icons.check : Icons.copy_rounded,
                                      size: 13,
                                      color: isCopied ? Colors.green[700] : AppColors.mutedText,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      isCopied ? 'Copied' : 'Copy',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w500,
                                        color: isCopied ? Colors.green[700] : AppColors.mutedText,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Compact, elegant citations widget for matched satsang episodes
  Widget _buildSourcesSection(List<MatchedEpisode> episodes) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.pageBackground.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border, width: 0.8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.auto_stories_outlined,
                size: 13,
                color: AppColors.accentStrong,
              ),
              SizedBox(width: 5),
              Text(
                'Satsang References',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: AppColors.accentStrong,
                  letterSpacing: 0.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: episodes.map((ep) {
              return Tooltip(
                message: ep.sourceFile,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: AppColors.border, width: 0.6),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        ep.displayTitle,
                        style: const TextStyle(
                          fontSize: 10.5,
                          color: AppColors.botText,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.botBubble,
                          borderRadius: BorderRadius.circular(3),
                        ),
                        child: Text(
                          ep.formattedScore,
                          style: const TextStyle(
                            fontSize: 9.5,
                            color: AppColors.accentStrong,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildTypingBubble() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            margin: const EdgeInsets.only(top: 2, right: 10),
            decoration: BoxDecoration(
              color: AppColors.botBubble,
              shape: BoxShape.circle,
              border: Border.all(color: AppColors.border, width: 1),
            ),
            child: const Icon(
              Icons.share_outlined,
              color: AppColors.accentStrong,
              size: 15,
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
            decoration: BoxDecoration(
              color: AppColors.botBubble,
              borderRadius: BorderRadius.circular(18),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 8,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            child: const _TypingDots(),
          ),
        ],
      ),
    );
  }

  Widget _buildInputBar() {
    return Container(
      constraints: const BoxConstraints(maxWidth: 640),
      margin: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: AppColors.inputBackground,
        borderRadius: BorderRadius.circular(32),
        border: Border.all(color: AppColors.border, width: 1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      padding: const EdgeInsets.only(left: 14, right: 6, top: 4, bottom: 4),
      child: Row(
        children: [
          const Padding(
            padding: EdgeInsets.only(left: 4, right: 6),
            child: Icon(
              Icons.wb_sunny_outlined,
              size: 20,
              color: AppColors.accentStrong,
            ),
          ),
          Expanded(
            child: TextField(
              controller: _controller,
              focusNode: _focusNode,
              enabled: !_isLoading,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _sendMessage(),
              style: const TextStyle(
                fontSize: 15,
                color: AppColors.botText,
              ),
              decoration: const InputDecoration(
                hintText: 'Apna sawaal poochein...',
                hintStyle: TextStyle(
                  fontSize: 15,
                  color: AppColors.mutedText,
                ),
                border: InputBorder.none,
                isDense: true,
                contentPadding: EdgeInsets.symmetric(vertical: 10),
              ),
            ),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: _isLoading ? null : _sendMessage,
            child: Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _isLoading
                    ? AppColors.accent.withValues(alpha: 0.4)
                    : AppColors.accent,
              ),
              child: const Icon(
                Icons.north_east,
                color: Colors.white,
                size: 19,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (index) {
            final delay = index * 0.2;
            final progress = (_controller.value - delay) % 1.0;
            final opacity = (0.3 + 0.7 * (1.0 - (progress - 0.5).abs() * 2))
                .clamp(0.2, 1.0);
            return Container(
              margin: EdgeInsets.only(left: index == 0 ? 0 : 5),
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accentStrong.withValues(alpha: opacity),
              ),
            );
          }),
        );
      },
    );
  }
}
