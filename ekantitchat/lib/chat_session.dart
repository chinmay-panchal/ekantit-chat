import 'chat_service.dart';

/// Represents a single conversation session with full history and metadata.
class ChatSession {
  final String id;
  final String title;
  final String lastSnippet;
  final DateTime updatedAt;
  final DateTime createdAt;
  final List<ChatMessage> messages;

  const ChatSession({
    required this.id,
    required this.title,
    required this.lastSnippet,
    required this.updatedAt,
    required this.createdAt,
    this.messages = const [],
  });

  ChatSession copyWith({
    String? id,
    String? title,
    String? lastSnippet,
    DateTime? updatedAt,
    DateTime? createdAt,
    List<ChatMessage>? messages,
  }) {
    return ChatSession(
      id: id ?? this.id,
      title: title ?? this.title,
      lastSnippet: lastSnippet ?? this.lastSnippet,
      updatedAt: updatedAt ?? this.updatedAt,
      createdAt: createdAt ?? this.createdAt,
      messages: messages ?? this.messages,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'lastSnippet': lastSnippet,
        'updatedAt': updatedAt.toIso8601String(),
        'createdAt': createdAt.toIso8601String(),
        'messages': messages.map((m) => m.toJson()).toList(),
      };

  factory ChatSession.fromJson(Map<String, dynamic> json) {
    final msgsRaw = json['messages'] as List<dynamic>? ?? [];
    final msgs = msgsRaw
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();

    return ChatSession(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? 'New Conversation',
      lastSnippet: json['lastSnippet'] as String? ?? '',
      updatedAt: DateTime.tryParse(json['updatedAt'] as String? ?? '') ?? DateTime.now(),
      createdAt: DateTime.tryParse(json['createdAt'] as String? ?? '') ?? DateTime.now(),
      messages: msgs,
    );
  }

  /// Create a fresh empty session
  factory ChatSession.createEmpty({String? id}) {
    final now = DateTime.now();
    return ChatSession(
      id: id ?? now.millisecondsSinceEpoch.toString(),
      title: 'New Conversation',
      lastSnippet: 'Start a conversation...',
      updatedAt: now,
      createdAt: now,
      messages: const [],
    );
  }
}
