import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

/// Matched Q&A episode citation from the backend RAG pipeline.
class MatchedEpisode {
  final String sourceFile;
  final double score;

  const MatchedEpisode({
    required this.sourceFile,
    required this.score,
  });

  factory MatchedEpisode.fromJson(Map<String, dynamic> json) {
    return MatchedEpisode(
      sourceFile: json['source_file'] as String? ?? 'Episode',
      score: (json['score'] as num?)?.toDouble() ?? 0.0,
    );
  }

  Map<String, dynamic> toJson() => {
        'source_file': sourceFile,
        'score': score,
      };

  /// Clean display label for UI chip (e.g., "#1363" or short title)
  String get displayTitle {
    final clean = sourceFile
        .replaceAll('.mp3', '')
        .replaceAll('.wav', '')
        .replaceAll('.json', '');
    final parts = clean.split('_');
    if (parts.isNotEmpty && parts.first.trim().isNotEmpty) {
      return parts.first.trim();
    }
    return clean;
  }

  /// Formatted score percentage (e.g. "87%")
  String get formattedScore => '${(score * 100).toInt()}%';
}

/// Chat message model supporting multi-turn conversation history.
class ChatMessage {
  final String role; // 'user' or 'assistant'
  final String content;
  final bool isError;
  final List<MatchedEpisode> matchedEpisodes;

  const ChatMessage({
    required this.role,
    required this.content,
    this.isError = false,
    this.matchedEpisodes = const [],
  });

  factory ChatMessage.user(String text) => ChatMessage(
        role: 'user',
        content: text,
      );

  factory ChatMessage.assistant(
    String text, {
    List<MatchedEpisode> matchedEpisodes = const [],
    bool isError = false,
  }) =>
      ChatMessage(
        role: 'assistant',
        content: text,
        isError: isError,
        matchedEpisodes: matchedEpisodes,
      );

  bool get isUser => role == 'user';
  String get text => content;

  Map<String, dynamic> toJson() => {
        'role': role,
        'content': content,
        'isError': isError,
        'matchedEpisodes': matchedEpisodes.map((e) => e.toJson()).toList(),
      };

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final episodesRaw = json['matchedEpisodes'] as List<dynamic>? ?? [];
    final episodes = episodesRaw
        .whereType<Map<String, dynamic>>()
        .map(MatchedEpisode.fromJson)
        .toList();
    return ChatMessage(
      role: json['role'] as String? ?? 'assistant',
      content: json['content'] as String? ?? '',
      isError: json['isError'] as bool? ?? false,
      matchedEpisodes: episodes,
    );
  }

  Map<String, String> toHistoryMap() => {
        'role': role,
        'content': content,
      };
}

/// Response returned by the POST /chat endpoint.
class ChatResponse {
  final String answer;
  final List<MatchedEpisode> matchedEpisodes;
  final String? standaloneQuery;

  const ChatResponse({
    required this.answer,
    required this.matchedEpisodes,
    this.standaloneQuery,
  });

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    final episodesRaw = json['matched_episodes'] as List<dynamic>? ?? [];
    final episodes = episodesRaw
        .whereType<Map<String, dynamic>>()
        .map(MatchedEpisode.fromJson)
        .toList();

    return ChatResponse(
      answer: json['answer'] as String? ?? '',
      matchedEpisodes: episodes,
      standaloneQuery: json['standalone_query'] as String?,
    );
  }
}

/// Service handling API communication with the RAG FastAPI backend.
class ChatService {
  /// Base URL for the backend.
  /// - Use 'https://ekantit-chat.onrender.com' for local macOS / desktop / iOS simulator.
  /// - Use 'http://10.0.2.2:8000' for standard Android emulator.
  /// - Use `http://<LAN-IP>:8000` for physical mobile devices on the same Wi-Fi.
  static const String defaultBaseUrl = 'https://ekantit-chat.onrender.com';

  final String baseUrl;
  final http.Client _client;

  ChatService({
    String? baseUrl,
    http.Client? client,
  })  : baseUrl = baseUrl ?? defaultBaseUrl,
        _client = client ?? http.Client();

  /// Maximum conversation history messages sent to the backend.
  static const int maxHistoryMessages = 20;

  /// Send query and conversation history to POST /chat.
  Future<ChatResponse> sendChat({
    required String query,
    required List<ChatMessage> history,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    final cleanQuery = query.trim();
    if (cleanQuery.isEmpty) {
      throw ArgumentError('Query cannot be empty');
    }

    // Filter out errors and loading bubbles, keeping only legitimate turns
    final validHistory = history
        .where((m) => !m.isError && m.content.trim().isNotEmpty)
        .toList();

    // Cap to the most recent turns to maintain token budget
    final trimmedHistory = validHistory.length > maxHistoryMessages
        ? validHistory.sublist(validHistory.length - maxHistoryMessages)
        : validHistory;

    final requestBody = jsonEncode({
      'query': cleanQuery,
      'history': trimmedHistory.map((m) => m.toHistoryMap()).toList(),
    });

    final uri = Uri.parse('$baseUrl/chat');

    try {
      final response = await _client
          .post(
            uri,
            headers: {'Content-Type': 'application/json; charset=utf-8'},
            body: requestBody,
          )
          .timeout(timeout);

      final responseBody = utf8.decode(response.bodyBytes);
      dynamic decoded;
      try {
        decoded = jsonDecode(responseBody);
      } catch (_) {
        decoded = null;
      }

      if (response.statusCode == 200 && decoded is Map<String, dynamic>) {
        final chatResponse = ChatResponse.fromJson(decoded);
        if (chatResponse.answer.trim().isEmpty) {
          throw const HttpException('The spiritual guide returned an empty answer.');
        }
        return chatResponse;
      } else {
        String message = 'Server returned error (${response.statusCode})';
        if (decoded is Map<String, dynamic> && decoded['detail'] != null) {
          message = decoded['detail'].toString();
        }
        throw HttpException(message);
      }
    } on SocketException catch (_) {
      throw const SocketException(
        'Could not reach server. Please ensure the backend is running at https://ekantit-chat.onrender.com (or your LAN IP on physical devices).',
      );
    } on TimeoutException {
      throw TimeoutException('Request timed out after ${timeout.inSeconds} seconds. Please try again.');
    }
  }

  /// Ping the backend /health endpoint to check server availability.
  Future<bool> checkHealth({Duration timeout = const Duration(seconds: 4)}) async {
    try {
      final uri = Uri.parse('$baseUrl/health');
      final res = await _client.get(uri).timeout(timeout);
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  ChatService copyWith({String? baseUrl}) {
    return ChatService(
      baseUrl: baseUrl ?? this.baseUrl,
      client: _client,
    );
  }

  void dispose() {
    _client.close();
  }
}

